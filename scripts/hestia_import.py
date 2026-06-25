"""
Importador de backups de HestiaCP (y Vesta) para SVQPanel.

Un backup de Hestia es un .tar por usuario (lo genera `v-backup-user`) con esta
estructura (los .conf son líneas KEY='value', NO se hacen source de shell):

    ./hestia            (o ./vesta)  → identificador del sistema de origen
    ./web/{domain}/hestia/web.conf            DOMAIN, IP, ALIAS, CUSTOM_DOCROOT,
                                              REDIRECT, SSL, LETSENCRYPT, BACKEND…
    ./web/{domain}/domain_data.tar.{gz,zst}   contenido del dominio (public_html…)
    ./web/{domain}/conf/  + *.crt/*.key/*.pem certificados SSL
    ./db/{database}/hestia/db.conf            DB, DBUSER, MD5(hash), HOST, TYPE,
                                              CHARSET
    ./db/{database}/{db}.{type}.sql.{gz,zst}  dump SQL
    ./mail/{domain}/hestia/mail.conf          líneas ACCOUNT='' MD5='' QUOTA=''…
    ./mail/{domain}/accounts.tar.{gz,zst}     maildirs de las cuentas
    ./dns/{domain}/hestia/dns.conf            DOMAIN, IP, TPL, TTL, SOA…
    ./dns/{domain}/hestia/{domain}.conf       registros DNS (RECORD='' TYPE=''…)

Esta primera fase implementa SOLO el análisis (parse + manifiesto + detección de
conflictos). NO toca el sistema. La importación real se añade en fases siguientes.

Seguridad: el .tar viene de una fuente no confiable. La extracción valida que
ningún miembro escape del directorio destino (path traversal).
"""

import os
import re
import shutil
import tarfile
import tempfile
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class HestiaImportError(RuntimeError):
    """Error legible del importador (el endpoint lo traduce a 4xx)."""


# ─────────────────────────────────────────────────────────────────────────────
# Parser de ficheros .conf de Hestia (KEY='value' KEY2='value2' …)
# ─────────────────────────────────────────────────────────────────────────────
# Una línea puede contener varios pares KEY='value' (p. ej. mail.conf por cuenta)
# o un único par por línea. Capturamos todos los pares de la línea.
_KV_RE = re.compile(r"([A-Z0-9_]+)='((?:[^'\\]|\\.)*)'")


def parse_conf_line(line: str) -> Dict[str, str]:
    """Devuelve {KEY: value} de todos los pares KEY='value' de una línea."""
    out: Dict[str, str] = {}
    for m in _KV_RE.finditer(line):
        out[m.group(1)] = m.group(2).replace("\\'", "'")
    return out


def parse_conf_single(text: str) -> Dict[str, str]:
    """Parsea un .conf de un solo objeto (web.conf, db.conf, dns.conf).

    Junta los pares de TODAS las líneas en un único dict (estos ficheros suelen
    tener una sola línea, pero por robustez recorremos todas).
    """
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.update(parse_conf_line(line))
    return out


def parse_conf_multi(text: str, key_field: str) -> List[Dict[str, str]]:
    """Parsea un .conf con varios objetos (uno por línea), p. ej. mail accounts.

    Devuelve una lista de dicts; solo las líneas que contienen `key_field`.
    """
    items: List[Dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kv = parse_conf_line(line)
        if key_field in kv:
            items.append(kv)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Parser de ficheros de zona BIND (cPanel guarda dnszones/{dominio}.db así)
# ─────────────────────────────────────────────────────────────────────────────
_BIND_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA", "PTR", "SPF")


def parse_bind_zone(text: str, domain: str):
    """Parsea un fichero de zona BIND a (records, old_ip).

    `records`: lista de dicts {RECORD, TYPE, VALUE, PRIORITY, TTL} (mismo formato
    que produce el parser de Hestia, para reutilizar todo el pipeline DNS).
    `old_ip`: la IP del registro A del dominio raíz (@), para sugerir reescritura.

    Es tolerante: maneja $TTL, $ORIGIN, nombres relativos/FQDN/@, TTL por línea,
    el "nombre heredado" (líneas que empiezan con espacios reusan el último
    nombre), y SOA multilínea (que se ignora — el SOA lo genera SVQPanel).
    """
    records = []
    old_ip = None
    default_ttl = 14400
    origin = domain.rstrip(".") + "."
    last_name = "@"
    in_soa = False
    soa_paren_depth = 0

    fqdn = domain.rstrip(".") + "."

    def _rel_name(name: str) -> str:
        """Convierte un nombre a relativo al dominio (@ para la raíz)."""
        if name in ("@", origin):
            return "@"
        n = name.rstrip(".")
        d = domain.rstrip(".")
        if n == d:
            return "@"
        if n.endswith("." + d):
            return n[: -(len(d) + 1)]
        return name  # ya relativo o de otra zona

    for raw in text.splitlines():
        line = raw.rstrip()
        # Quitar comentarios (; …) respetando que no estén dentro de comillas.
        if ";" in line and '"' not in line.split(";", 1)[0]:
            line = line.split(";", 1)[0].rstrip()
        if not line.strip():
            continue

        # Directivas
        up = line.strip()
        if up.startswith("$TTL"):
            m = re.search(r"\$TTL\s+(\d+)", up)
            if m:
                default_ttl = int(m.group(1))
            continue
        if up.startswith("$ORIGIN"):
            m = re.search(r"\$ORIGIN\s+(\S+)", up)
            if m:
                origin = m.group(1)
            continue

        # Gestionar SOA multilínea entre paréntesis (lo ignoramos por completo).
        if in_soa:
            soa_paren_depth += line.count("(") - line.count(")")
            if soa_paren_depth <= 0:
                in_soa = False
            continue
        if re.search(r"\bSOA\b", line):
            soa_paren_depth = line.count("(") - line.count(")")
            if soa_paren_depth > 0:
                in_soa = True
            continue

        # Tokenizar respetando comillas (para TXT con espacios).
        tokens = _tokenize_zone_line(line)
        if not tokens:
            continue

        # Determinar si la línea empieza con un nombre o hereda el anterior.
        starts_with_ws = raw[:1] in (" ", "\t")
        idx = 0
        if starts_with_ws:
            name = last_name
        else:
            name = tokens[0]
            last_name = name
            idx = 1

        # Saltar TTL y clase (IN) hasta encontrar el tipo.
        ttl = default_ttl
        rtype = None
        while idx < len(tokens):
            tok = tokens[idx].upper()
            if tok.isdigit():
                ttl = int(tokens[idx]); idx += 1; continue
            if tok in ("IN", "CH", "HS"):
                idx += 1; continue
            if tok in _BIND_TYPES:
                rtype = tok; idx += 1; break
            # token desconocido en posición de tipo → abortar esta línea
            break

        if not rtype or idx > len(tokens):
            continue
        value_tokens = tokens[idx:]
        if not value_tokens:
            continue

        priority = 0
        if rtype in ("MX", "SRV") and value_tokens and value_tokens[0].isdigit():
            priority = int(value_tokens[0])
            value_tokens = value_tokens[1:]
        value = " ".join(value_tokens).strip()
        if rtype == "TXT":
            value = value.strip('"')
        else:
            value = value.rstrip(".") if value.endswith(".") and rtype in ("CNAME", "NS", "MX", "SRV", "PTR") else value

        rel = _rel_name(name)
        if rtype == "A" and rel == "@" and old_ip is None:
            old_ip = value

        records.append({
            "RECORD": rel, "TYPE": rtype, "VALUE": value,
            "PRIORITY": str(priority), "TTL": str(ttl),
        })

    return records, old_ip


def _tokenize_zone_line(line: str) -> List[str]:
    """Tokeniza una línea de zona BIND respetando comillas dobles (TXT)."""
    tokens = []
    for m in re.finditer(r'"[^"]*"|\S+', line.strip()):
        tokens.append(m.group(0))
    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# Extracción segura de tar (anti path-traversal)
# ─────────────────────────────────────────────────────────────────────────────
def _is_within(base: str, target: str) -> bool:
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


# Sufijos de los archivos de DATOS pesados de un backup Hestia: los datos web,
# los buzones y los dumps de BD. Para el ANÁLISIS (leer el manifiesto) no hacen
# falta — solo los .conf pequeños —, así que se omiten al extraer en modo
# config_only. Extraerlos de un backup de varios GB es lo que provocaba el 504.
_DATA_ARCHIVE_HINTS = ("domain_data.tar", "accounts.tar")


def _is_heavy_data_member(name: str) -> bool:
    base = os.path.basename(name)
    if any(h in base for h in _DATA_ARCHIVE_HINTS):
        return True
    # dumps de BD: {db}.{type}.sql(.gz|.zst|…)
    if ".sql" in base and (base.endswith((".gz", ".zst", ".zstd", ".sql", ".bz2", ".xz"))):
        return True
    return False


def safe_extract_tar(tar_path: str, dest: str, config_only: bool = False) -> list:
    """Extrae un .tar(.gz) validando que ningún miembro escape de `dest`.

    Soporta el filtro 'data' de Python 3.12+; en versiones previas valida a mano.
    Si `config_only`, omite los archivos de datos pesados (web data, buzones,
    dumps de BD): basta para analizar el manifiesto y evita extraer varios GB.
    Devuelve la lista de TODOS los nombres del tar (extraídos u omitidos), para
    que el análisis pueda saber qué datos existen sin haberlos extraído.
    """
    mode = "r:*"  # autodetecta gz/bz2/xz/plano
    try:
        tar = tarfile.open(tar_path, mode)
    except (tarfile.ReadError, tarfile.CompressionError, OSError):
        raise HestiaImportError(
            "El archivo no es un .tar válido de HestiaCP. Sube el backup que "
            "genera Hestia (v-backup-user), sin comprimir en .zip ni renombrar.")
    with tar:
        members = tar.getmembers()
        safe_members = []
        for m in members:
            member_path = os.path.join(dest, m.name)
            # Una ruta de fichero que escapa del destino SÍ es un ataque → abortar.
            if not _is_within(dest, member_path):
                raise HestiaImportError(
                    f"El backup contiene una ruta no segura: {m.name!r}")
            # Modo análisis: saltar los datos pesados (no se leen para el manifiesto).
            if config_only and m.isfile() and _is_heavy_data_member(m.name):
                continue
            # Symlinks/hardlinks que apuntan FUERA del destino: NO abortamos. Los
            # backups de Hestia traen symlinks de config (p.ej. nginx.ssl.conf →
            # /etc/letsencrypt/...) que apuntan a rutas del sistema origen. No nos
            # sirven (regeneramos la config en SVQPanel) y extraerlos sería un
            # riesgo, así que simplemente los OMITIMOS y seguimos.
            if m.issym() or m.islnk():
                link_target = os.path.join(dest, os.path.dirname(m.name), m.linkname)
                if not _is_within(dest, link_target):
                    logger.info(f"Omitido enlace que apunta fuera del backup: {m.name!r}")
                    continue
            safe_members.append(m)
        try:
            tar.extractall(dest, members=safe_members, filter="data")  # Python ≥ 3.12
        except TypeError:
            tar.extractall(dest, members=safe_members)                 # validado arriba
        return [m.name for m in members]


# ─────────────────────────────────────────────────────────────────────────────
# Descompresión gz / zst (para domain_data, dumps, accounts)
# ─────────────────────────────────────────────────────────────────────────────
def has_zstd() -> bool:
    """¿Hay soporte zstd? (módulo python `zstandard` o binario `zstd`)."""
    try:
        import zstandard  # noqa: F401
        return True
    except ImportError:
        return shutil.which("zstd") is not None or shutil.which("unzstd") is not None


def is_zst(path: str) -> bool:
    return path.endswith(".zst") or path.endswith(".zstd")


# ─────────────────────────────────────────────────────────────────────────────
# Clase principal: representa un backup extraído y lo analiza
# ─────────────────────────────────────────────────────────────────────────────
class HestiaBackup:
    """Abre y analiza un backup de Hestia/Vesta. Context manager: limpia el tmp."""

    def __init__(self, tar_path: str, config_only: bool = False):
        if not os.path.isfile(tar_path):
            raise HestiaImportError(f"No existe el archivo de backup: {tar_path}")
        self.tar_path = tar_path
        self.tmpdir = tempfile.mkdtemp(prefix="svq_hestia_")
        self.system: Optional[str] = None   # "hestia" | "vesta"
        self._extracted = False
        # En modo análisis no se extraen los datos pesados; guardamos los nombres
        # del tar para poder reportar has_data/has_dump sin haberlos extraído.
        self.config_only = config_only
        self._tar_names: List[str] = []

    def __enter__(self):
        self.extract()
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def __del__(self):
        # Red de seguridad: si el objeto se creó sin 'with' o falló antes de
        # entrar al with, el GC limpia igualmente el tmpdir (no dejar basura).
        try:
            self.cleanup()
        except Exception:
            pass

    def cleanup(self):
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None

    # ── extracción ──────────────────────────────────────────────────────────
    def extract(self):
        if self._extracted:
            return
        self._tar_names = safe_extract_tar(
            self.tar_path, self.tmpdir, config_only=self.config_only)
        self._extracted = True
        # Detectar sistema de origen: hay un fichero/carpeta marcador.
        for marker in ("hestia", "vesta"):
            if os.path.exists(os.path.join(self.tmpdir, marker)):
                self.system = marker
                break
        # Algunos backups anidan todo bajo ./{user}/ — detectar raíz real.
        self.root = self._find_root()
        if self.system is None:
            # Sin marcador: inferir por la presencia de las carpetas típicas.
            if any(os.path.isdir(os.path.join(self.root, d))
                   for d in ("web", "mail", "dns", "db")):
                self.system = "hestia"
            else:
                raise HestiaImportError(
                    "El archivo no parece un backup de HestiaCP/Vesta "
                    "(faltan las carpetas web/db/mail/dns).")

    def _find_root(self) -> str:
        """La raíz donde están web/db/mail/dns. Normalmente el propio tmpdir."""
        for cand in (self.tmpdir,):
            if any(os.path.isdir(os.path.join(cand, d))
                   for d in ("web", "db", "mail", "dns")):
                return cand
        # ¿Anidado un nivel? (./algo/web …)
        for entry in os.listdir(self.tmpdir):
            sub = os.path.join(self.tmpdir, entry)
            if os.path.isdir(sub) and any(
                    os.path.isdir(os.path.join(sub, d))
                    for d in ("web", "db", "mail", "dns")):
                return sub
        return self.tmpdir

    # ── helpers de lectura ────────────────────────────────────────────────────
    def _conf_dir(self, kind: str, name: str) -> Optional[str]:
        """Ruta del subdir de config del objeto: {kind}/{name}/{system}/."""
        for sysname in (self.system, "hestia", "vesta"):
            if not sysname:
                continue
            d = os.path.join(self.root, kind, name, sysname)
            if os.path.isdir(d):
                return d
        return None

    def _read(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def _list_objects(self, kind: str) -> List[str]:
        base = os.path.join(self.root, kind)
        if not os.path.isdir(base):
            return []
        return sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))

    # ── análisis por tipo de recurso ──────────────────────────────────────────
    def analyze_user(self) -> Dict[str, str]:
        """Lee user.conf si está (email, nombre, paquete…)."""
        for cand in (
            os.path.join(self.root, "user.conf"),
            os.path.join(self.root, self.system or "hestia", "user.conf"),
        ):
            if os.path.isfile(cand):
                return parse_conf_single(self._read(cand))
        return {}

    def analyze_web(self) -> List[Dict]:
        out = []
        for domain in self._list_objects("web"):
            cdir = self._conf_dir("web", domain)
            conf = parse_conf_single(self._read(os.path.join(cdir, "web.conf"))) if cdir else {}
            data_tar = self._find_data_archive("web", domain, "domain_data")
            out.append({
                "domain": conf.get("DOMAIN", domain),
                "aliases": [a for a in conf.get("ALIAS", "").split(",") if a],
                "php_version": _php_from_backend(conf.get("BACKEND", "")),
                "ssl": conf.get("SSL", "no") == "yes",
                "letsencrypt": conf.get("LETSENCRYPT", "no") == "yes",
                "custom_docroot": conf.get("CUSTOM_DOCROOT", "") or None,
                "redirect": conf.get("REDIRECT", "") or None,
                "has_data": bool(data_tar),
                "_data_tar": data_tar,
                "_conf_dir": cdir,
            })
        return out

    def analyze_db(self) -> List[Dict]:
        out = []
        for dbname in self._list_objects("db"):
            cdir = self._conf_dir("db", dbname)
            conf = parse_conf_single(self._read(os.path.join(cdir, "db.conf"))) if cdir else {}
            dump = self._find_db_dump(dbname, conf.get("TYPE", "mysql"))
            out.append({
                "db": conf.get("DB", dbname),
                "dbuser": conf.get("DBUSER", ""),
                "md5": conf.get("MD5", ""),     # hash nativo (reutilizable)
                "type": conf.get("TYPE", "mysql"),
                "charset": conf.get("CHARSET", "utf8mb4"),
                "has_dump": bool(dump),
                "_dump": dump,
            })
        return out

    def analyze_mail(self) -> List[Dict]:
        out = []
        for domain in self._list_objects("mail"):
            cdir = self._conf_dir("mail", domain)
            # accounts están en mail/{domain}/hestia/{domain}.conf (una por línea)
            accounts = []
            if cdir:
                acc_conf = os.path.join(cdir, f"{domain}.conf")
                if os.path.isfile(acc_conf):
                    for a in parse_conf_multi(self._read(acc_conf), "ACCOUNT"):
                        accounts.append({
                            "account": a.get("ACCOUNT", ""),
                            "md5": a.get("MD5", ""),      # hash (reutilizable)
                            "quota": a.get("QUOTA", "0"),
                            "fwd": a.get("FWD", "") or None,
                        })
            out.append({
                "domain": domain,
                "accounts": accounts,
                "accounts_tar": self._find_data_archive("mail", domain, "accounts"),
                "_conf_dir": cdir,
            })
        return out

    def analyze_dns(self) -> List[Dict]:
        out = []
        for domain in self._list_objects("dns"):
            cdir = self._conf_dir("dns", domain)
            conf = parse_conf_single(self._read(os.path.join(cdir, "dns.conf"))) if cdir else {}
            records = []
            if cdir:
                rec_conf = os.path.join(cdir, f"{domain}.conf")
                if os.path.isfile(rec_conf):
                    records = parse_conf_multi(self._read(rec_conf), "RECORD")
            out.append({
                "domain": conf.get("DOMAIN", domain),
                "ip": conf.get("IP", "") or None,
                "ttl": conf.get("TTL", "14400"),
                "records_count": len(records),
                "_records": records,
            })
        return out

    # ── localizar archivos de datos comprimidos ───────────────────────────────
    def _find_data_archive(self, kind: str, name: str, base: str) -> Optional[str]:
        """Busca {base}.tar.gz / .tar.zst en {kind}/{name}/.

        En modo config_only los datos no se extrajeron: buscamos en la lista de
        nombres del tar y devolvemos la ruta donde ESTARÁ tras la extracción real.
        """
        d = os.path.join(self.root, kind, name)
        for ext in (".tar.gz", ".tar.zst", ".tar.zstd", ".tar"):
            p = os.path.join(d, base + ext)
            if os.path.isfile(p):
                return p
        if self.config_only:
            suffix = f"{kind}/{name}/{base}"
            for n in self._tar_names:
                nn = n.rstrip("/")
                if (suffix in nn) and nn.split(suffix, 1)[1] in (
                        ".tar.gz", ".tar.zst", ".tar.zstd", ".tar"):
                    return os.path.join(d, os.path.basename(nn))
        return None

    def _find_db_dump(self, dbname: str, dbtype: str) -> Optional[str]:
        d = os.path.join(self.root, "db", dbname)
        if os.path.isdir(d):
            # {db}.{type}.sql.{gz,zst} — por robustez buscamos cualquier .sql.*
            for fn in os.listdir(d):
                if fn.startswith(dbname) and ".sql" in fn:
                    return os.path.join(d, fn)
        if self.config_only:
            frag = f"db/{dbname}/"
            for n in self._tar_names:
                base = os.path.basename(n.rstrip("/"))
                if frag in n and base.startswith(dbname) and ".sql" in base:
                    return os.path.join(d, base)
        return None

    # ── manifiesto completo ────────────────────────────────────────────────────
    def analyze(self) -> Dict:
        """Manifiesto del backup (sin tocar el sistema)."""
        user = self.analyze_user()
        return {
            "system": self.system,
            "user": {
                "contact": user.get("CONTACT", ""),
                "fname": user.get("FNAME", ""),
                "lname": user.get("LNAME", ""),
                "package": user.get("PACKAGE", ""),
            },
            "web": self.analyze_web(),
            "db": self.analyze_db(),
            "mail": self.analyze_mail(),
            "dns": self.analyze_dns(),
        }


def installed_php_versions() -> List[str]:
    """Versiones PHP instaladas (con pool FPM) en el servidor, ordenadas."""
    base = "/etc/php"
    if not os.path.isdir(base):
        return []
    vers = []
    for v in os.listdir(base):
        if os.path.isdir(os.path.join(base, v, "fpm", "pool.d")):
            vers.append(v)
    return sorted(vers, key=lambda s: [int(x) for x in s.split(".") if x.isdigit()])


def resolve_php_version(wanted: Optional[str]) -> str:
    """Devuelve `wanted` si está instalada; si no, la más cercana disponible.

    Hestia puede traer una versión PHP que el servidor destino no tenga (p. ej.
    8.2 cuando el server tiene 8.4). En vez de fallar, caemos a la disponible
    más cercana (preferimos una >= a la pedida; si no, la mayor instalada).
    """
    installed = installed_php_versions()
    if not installed:
        return wanted or "8.2"
    if wanted and wanted in installed:
        return wanted
    if wanted:
        try:
            wf = float(wanted)
            ge = [v for v in installed if _ver_float(v) >= wf]
            if ge:
                return min(ge, key=_ver_float)   # la menor >= pedida
        except ValueError:
            pass
    return installed[-1]   # la mayor instalada


def _ver_float(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


def _php_from_backend(backend: str) -> Optional[str]:
    """Extrae la versión PHP del campo BACKEND de Hestia.

    Formatos típicos: 'user_domain_php82', 'PHP-8_2', 'php-fpm-8.2'. Devolvemos
    '8.2' o None si no se puede inferir.
    """
    if not backend:
        return None
    m = re.search(r"(\d)[._]?(\d)", backend)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Detección de conflictos contra el panel (sin tocar nada)
# ─────────────────────────────────────────────────────────────────────────────
def find_conflicts(manifest: Dict, db, scope: Optional[List[str]] = None) -> List[str]:
    """Devuelve una lista de conflictos legibles (recursos que YA existen).

    `db` es una Session de SQLAlchemy del panel. `scope` limita las comprobaciones
    a lo que realmente se va a importar (web/db/mail/dns); si es None, comprueba
    todo. Así, si solo importas «Webs», no te bloquean las BD/correo/DNS que ya
    existan (porque no se van a tocar).
    """
    from api.models.models_domain import Domain
    from api.models.models_client_db import ClientDatabase
    conflicts: List[str] = []
    scope = scope if scope is not None else ["web", "db", "mail", "dns"]

    if "web" in scope:
        for w in manifest.get("web", []):
            if db.query(Domain).filter(Domain.domain_name == w["domain"]).first():
                conflicts.append(f"El dominio web «{w['domain']}» ya existe en el panel.")

    if "db" in scope:
        for d in manifest.get("db", []):
            if db.query(ClientDatabase).filter(ClientDatabase.db_name == d["db"]).first():
                conflicts.append(f"La base de datos «{d['db']}» ya existe en el panel.")

    # Mail y DNS: comprobar si los modelos existen (import defensivo).
    if "mail" in scope:
        try:
            from api.models.models_mail import MailDomain
            for m in manifest.get("mail", []):
                if db.query(MailDomain).filter(MailDomain.domain_name == m["domain"]).first():
                    conflicts.append(f"El dominio de correo «{m['domain']}» ya existe.")
        except ImportError:
            pass
    if "dns" in scope:
        try:
            from api.models.models_dns import DnsZone
            for z in manifest.get("dns", []):
                if db.query(DnsZone).filter(DnsZone.domain_name == z["domain"]).first():
                    conflicts.append(f"La zona DNS «{z['domain']}» ya existe.")
        except ImportError:
            pass

    return conflicts


# ─────────────────────────────────────────────────────────────────────────────
# Descompresión de un .tar.{gz,zst} a un directorio destino
# ─────────────────────────────────────────────────────────────────────────────
def extract_data_archive(archive: str, dest: str) -> None:
    """Extrae un domain_data/accounts .tar.(gz|zst) en `dest` de forma segura.

    Para .zst usa el módulo `zstandard` si está, o el binario `zstd` como
    fallback. Para .gz lo gestiona tarfile directamente.
    """
    os.makedirs(dest, exist_ok=True)
    if is_zst(archive):
        # Descomprimir zst a un .tar temporal y luego extraer con safe_extract.
        tmp_tar = archive[:-4] if archive.endswith(".zst") else archive[:-5]
        tmp_tar = tmp_tar + ".__tmp.tar"
        _zst_decompress(archive, tmp_tar)
        try:
            safe_extract_tar(tmp_tar, dest)
        finally:
            if os.path.exists(tmp_tar):
                os.remove(tmp_tar)
    else:
        safe_extract_tar(archive, dest)


def _zst_decompress(src: str, dst: str) -> None:
    try:
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            dctx.copy_stream(fin, fout)
        return
    except ImportError:
        pass
    # Fallback al binario zstd
    import subprocess
    for tool in ("unzstd", "zstd"):
        if shutil.which(tool):
            args = [tool, "-d", "-f", "-o", dst, src] if tool == "zstd" else [tool, "-f", "-o", dst, src]
            r = subprocess.run(args, capture_output=True, text=True)
            if r.returncode == 0:
                return
    raise HestiaImportError(
        "El backup usa compresión zstd y el servidor no tiene soporte. "
        "Instala el paquete 'zstd' o el módulo python 'zstandard'.")


# ─────────────────────────────────────────────────────────────────────────────
# Informe de la importación
# ─────────────────────────────────────────────────────────────────────────────
class ImportReport:
    """Acumula el resultado de una importación, serializable a JSON."""

    def __init__(self):
        self.created: List[Dict] = []     # {type, name, detail}
        self.errors: List[Dict] = []      # {type, name, error}
        self.passwords: List[Dict] = []   # {type, name, password} (nuevas generadas)

    def ok(self, rtype: str, name: str, detail: str = ""):
        self.created.append({"type": rtype, "name": name, "detail": detail})
        logger.info(f"[import] OK {rtype} {name} {detail}")

    def fail(self, rtype: str, name: str, error: str):
        self.errors.append({"type": rtype, "name": name, "error": str(error)})
        logger.warning(f"[import] FAIL {rtype} {name}: {error}")

    def password(self, rtype: str, name: str, password: str):
        self.passwords.append({"type": rtype, "name": name, "password": password})

    def to_dict(self) -> Dict:
        return {
            "created": self.created,
            "errors": self.errors,
            "passwords": self.passwords,
            "summary": {
                "created": len(self.created),
                "errors": len(self.errors),
                "new_passwords": len(self.passwords),
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Importación de WEB (dominio + archivos + vhost + SSL)
# ─────────────────────────────────────────────────────────────────────────────
def import_web(backup: "HestiaBackup", web: Dict, owner, db, report: ImportReport):
    """Crea el dominio en SVQPanel, restaura public_html y regenera el vhost.

    `web` es un item de manifest['web'] (incluye los campos internos _data_tar).
    `owner` es el User destino. Reutiliza DomainManager y persiste Domain en BD.
    """
    from scripts.domain_manager import DomainManager
    from api.models.models_domain import Domain
    from api.models.models_settings import Settings as _Settings

    domain_name = web["domain"]
    wanted_php = web.get("php_version") or "8.2"
    php_version = resolve_php_version(wanted_php)
    php_note = ""
    if php_version != wanted_php:
        php_note = f" (PHP {wanted_php} no disponible → {php_version})"

    mgr = DomainManager()
    # 1) Crear la estructura del dominio (dirs, pool PHP, vhost base)
    mgr.create_domain(owner.username, domain_name, php_version)

    # 2) Restaurar el contenido. Hestia trae un domain_data.tar.gz (_data_tar);
    #    cPanel trae los archivos ya descomprimidos en una carpeta (_data_dir).
    data_tar = web.get("_data_tar")
    data_dir = web.get("_data_dir")
    public_html = f"/home/{owner.username}/web/{domain_name}/public_html"
    has_data = (data_tar and os.path.isfile(data_tar)) or (data_dir and os.path.isdir(data_dir))
    if has_data:
        web_root = f"/home/{owner.username}/web/{domain_name}"
        # Quitar el index.html placeholder del panel ANTES de copiar, para que
        # no conviva con el index.php del sitio importado (Apache/nginx
        # priorizarían el placeholder). Reutiliza la lógica del autoinstalador.
        try:
            from scripts.app_installer import _clean_placeholders
            _clean_placeholders(public_html)
        except Exception:
            pass
        if data_dir and os.path.isdir(data_dir):
            # cPanel: el documentroot del dominio ya es su public_html → copiamos
            # su CONTENIDO directamente al public_html creado por el panel.
            _copy_into(data_dir, public_html)
        else:
            _restore_web_files(data_tar, web_root, public_html)
        # Neutralizar en el .htaccess la regla "RewriteCond %{HTTPS} off → 301 a
        # https": es redundante (nginx ya fuerza https en el front) y en nuestra
        # arquitectura Apache-tras-Nginx causa un bucle infinito de redirección
        # (Apache siempre ve HTTPS off tras el proxy) → ERR_TOO_MANY_REDIRECTS.
        _neutralize_htaccess_https_redirect(public_html)
        # Permisos: el CONTENIDO al usuario del dominio (ver svqpanel-php-pool-user).
        import subprocess
        subprocess.run(["chown", "-R", f"{owner.username}:{owner.username}", web_root],
                       capture_output=True)
        # PERO el directorio del dominio debe tener grupo www-data + 750 para que
        # nginx (www-data) pueda atravesarlo; si no, da 403 Forbidden. El chown -R
        # de arriba lo había puesto a grupo del usuario → lo restauramos aquí.
        # (Mismo estado que un dominio creado por el panel normalmente.)
        subprocess.run(["chgrp", "www-data", web_root], capture_output=True)
        subprocess.run(["chmod", "750", web_root], capture_output=True)

    # 3) Persistir el Domain en la BD del panel
    ipv4 = None
    try:
        _s = db.query(_Settings).filter(_Settings.id == 1).first()
        ipv4 = (_s.server_ipv4 or None) if _s else None
    except Exception:
        pass

    db_domain = Domain(
        user_id=owner.id,
        domain_name=domain_name,
        php_version=php_version,
        public_html=public_html,
        ipv4=ipv4,
        custom_docroot=web.get("custom_docroot") or None,
        redirect_to=web.get("redirect") or None,
    )
    db.add(db_domain)
    db.commit()
    db.refresh(db_domain)

    # 4) Regenerar el vhost con los ajustes reales (docroot, redirect…). SSL se
    #    deja para emisión posterior (Let's Encrypt) — restaurar certs de Hestia
    #    es frágil; el panel puede emitir uno nuevo cuando el DNS apunte aquí.
    try:
        mgr.regenerate_vhost(
            owner.username, domain_name, php_version,
            custom_docroot=web.get("custom_docroot") or None,
            redirect_to=web.get("redirect") or None,
        )
    except Exception as e:
        report.fail("web-vhost", domain_name, f"vhost no regenerado: {e}")

    report.ok("web", domain_name, f"PHP {php_version}"
              + (" + archivos" if has_data else " (sin datos)") + php_note)
    return db_domain


def _neutralize_htaccess_https_redirect(public_html: str) -> None:
    """Comenta la regla de redirección-a-https del .htaccess (redundante con el
    front Nginx y causa de bucle en Apache-tras-Nginx). Idempotente; deja backup."""
    import re
    ht = os.path.join(public_html, ".htaccess")
    if not os.path.isfile(ht):
        return
    try:
        with open(ht) as f:
            content = f.read()
    except OSError:
        return
    # Par: RewriteCond %{HTTPS} off  +  RewriteRule ... https://... [R=301]
    pat = re.compile(
        r'(^[ \t]*RewriteCond[ \t]+%\{HTTPS\}[ \t]+off[ \t]*\n'
        r'[ \t]*RewriteRule[ \t]+\^.*https://.*\[[^\]]*R=301[^\]]*\][ \t]*\n)',
        re.M | re.I)

    def _comment(m):
        return "".join("    # [SVQPanel] " + l if l.strip() else l
                       for l in m.group(1).splitlines(True))

    new, n = pat.subn(_comment, content)
    if n:
        try:
            with open(ht + ".svqbak", "w") as f:
                f.write(content)
            with open(ht, "w") as f:
                f.write(new)
            logger.info(f"Neutralizada la redirección https redundante en {ht} ({n})")
        except OSError as e:
            logger.warning(f"No se pudo editar {ht}: {e}")


def _restore_web_files(data_tar: str, web_root: str, public_html: str) -> None:
    """Extrae domain_data a un tmp y copia public_html (y dirs hermanos) al sitio.

    Hestia guarda dentro del tar el árbol del dominio (public_html/, etc.). Para
    no pisar el vhost ni el pool, copiamos el CONTENIDO de public_html del backup
    dentro del public_html ya creado por create_domain().
    """
    tmp = tempfile.mkdtemp(prefix="svq_webdata_")
    try:
        extract_data_archive(data_tar, tmp)
        # Buscar el public_html dentro del extraído (puede estar a distinta
        # profundidad según la versión de Hestia).
        src_ph = _find_subdir(tmp, "public_html")
        if src_ph:
            _copy_into(src_ph, public_html)
        else:
            # Sin public_html explícito: copiar todo el contenido extraído.
            _copy_into(tmp, public_html)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_subdir(base: str, name: str) -> Optional[str]:
    """Busca un subdirectorio `name` hasta 3 niveles de profundidad."""
    for root, dirs, _ in os.walk(base):
        if os.path.relpath(root, base).count(os.sep) > 3:
            continue
        if name in dirs:
            return os.path.join(root, name)
    return None


def _copy_into(src_dir: str, dst_dir: str) -> None:
    """Copia el contenido de src_dir dentro de dst_dir (mezcla, no reemplaza dst)."""
    os.makedirs(dst_dir, exist_ok=True)
    for entry in os.listdir(src_dir):
        s = os.path.join(src_dir, entry)
        d = os.path.join(dst_dir, entry)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


# ─────────────────────────────────────────────────────────────────────────────
# Importación de BASE DE DATOS (BD + usuario + dump)
# ─────────────────────────────────────────────────────────────────────────────
def import_db(backup: "HestiaBackup", dbinfo: Dict, owner, db, report: ImportReport):
    """Recrea una BD MariaDB y su usuario, e importa el dump.

    Intenta reutilizar el hash de contraseña original del usuario MySQL
    (`IDENTIFIED BY PASSWORD '<hash>'`). Si no se puede, genera una nueva y la
    añade al informe. Registra la BD en la tabla ClientDatabase del panel.
    Solo MySQL/MariaDB (Hestia con pgsql no es habitual; se omite con aviso).
    """
    from api.routes.databases import (
        _run_mariadb, _hash_password, _encrypt_password, _generate_password)
    from api.models.models_client_db import ClientDatabase

    name = dbinfo["db"]
    dbuser = dbinfo.get("dbuser") or name
    md5 = (dbinfo.get("md5") or "").strip()    # hash nativo de MySQL
    dbtype = dbinfo.get("type", "mysql")
    charset = dbinfo.get("charset") or "utf8mb4"

    if dbtype not in ("mysql", "mariadb"):
        report.fail("db", name, f"tipo {dbtype} no soportado (solo MySQL/MariaDB)")
        return

    # Identificadores: respetamos el nombre original del backup (sin re-prefijar,
    # para que el sitio importado siga encontrando su BD por el nombre de siempre).
    safe_name = _ident(name)
    safe_user = _ident(dbuser)
    new_password = None

    # 1) Crear la BD
    _run_mariadb(f"CREATE DATABASE `{safe_name}` CHARACTER SET {charset};")

    # 2) Crear el usuario reutilizando el hash, con fallback a pass nueva
    created_user = _create_db_user_with_hash(_run_mariadb, safe_user, md5)
    if not created_user:
        new_password = _generate_password()
        _run_mariadb(f"CREATE USER '{safe_user}'@'localhost' "
                     f"IDENTIFIED BY '{new_password}';")
        report.password("db", f"{name} (usuario {dbuser})", new_password)

    # 3) Permisos
    _run_mariadb(
        f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, "
        f"CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, CREATE VIEW, SHOW VIEW, "
        f"CREATE ROUTINE, ALTER ROUTINE, EVENT, TRIGGER ON `{safe_name}`.* "
        f"TO '{safe_user}'@'localhost';")
    _run_mariadb("FLUSH PRIVILEGES;")

    # 4) Importar el dump
    dump = dbinfo.get("_dump")
    if dump and os.path.isfile(dump):
        _import_sql_dump(dump, safe_name)

    # 5) Registrar en el panel (ClientDatabase). Sin la pass en claro del hash
    #    reusado, guardamos un placeholder de hash y dejamos enc=None.
    pw_for_panel = new_password or ""
    suffix = name.split("_", 1)[-1] if "_" in name else name
    usuffix = dbuser.split("_", 1)[-1] if "_" in dbuser else dbuser
    client_db = ClientDatabase(
        user_id=owner.id,
        db_name=name,
        db_name_suffix=suffix[:48],
        db_user=dbuser,
        db_user_suffix=usuffix[:48],
        db_password_hash=_hash_password(pw_for_panel) if pw_for_panel else _hash_password("!imported!"),
        db_password_enc=_encrypt_password(pw_for_panel) if pw_for_panel else None,
        db_charset=charset,
    )
    db.add(client_db)
    db.commit()

    detail = "con dump" if dump else "sin dump"
    detail += "; contraseña conservada" if created_user else "; contraseña NUEVA (ver informe)"
    report.ok("db", name, detail)


def _create_db_user_with_hash(run_sql, safe_user: str, md5: str) -> bool:
    """Crea el usuario MySQL reutilizando el hash original. True si lo logró.

    El hash de Hestia es el hash nativo de MySQL/MariaDB. Probamos dos sintaxis:
    la moderna (`IDENTIFIED WITH mysql_native_password AS '<hash>'`) y la clásica
    (`IDENTIFIED BY PASSWORD '<hash>'`). Si ninguna funciona, devolvemos False.
    """
    if not md5:
        return False
    # El hash nativo de mysql_native_password empieza por '*'. Otros formatos
    # (caching_sha2, argon…) no se pueden reinyectar fiablemente → fallback.
    candidates = []
    if md5.startswith("*"):
        candidates.append(
            f"CREATE USER '{safe_user}'@'localhost' "
            f"IDENTIFIED WITH mysql_native_password AS '{md5}';")
        candidates.append(
            f"CREATE USER '{safe_user}'@'localhost' "
            f"IDENTIFIED BY PASSWORD '{md5}';")
    for sql in candidates:
        try:
            run_sql(sql)
            return True
        except Exception:
            continue
    return False


def _import_sql_dump(dump_path: str, db_name: str) -> None:
    """Importa un dump .sql(.gz|.zst) en la BD indicada vía el cliente CLI."""
    import subprocess
    from api.routes.databases import (
        _mariadb_binary, MARIADB_HOST, MARIADB_PANEL_USER, MARIADB_PANEL_PASSWORD)

    # Descomprimir a un .sql temporal si hace falta.
    tmp_sql = None
    sql_path = dump_path
    if is_zst(dump_path):
        tmp_sql = dump_path + ".__tmp.sql"
        _zst_decompress(dump_path, tmp_sql)
        sql_path = tmp_sql
    elif dump_path.endswith(".gz"):
        import gzip, shutil as _sh
        tmp_sql = dump_path + ".__tmp.sql"
        with gzip.open(dump_path, "rb") as fin, open(tmp_sql, "wb") as fout:
            _sh.copyfileobj(fin, fout)
        sql_path = tmp_sql
    try:
        binary = _mariadb_binary()
        with open(sql_path, "rb") as fin:
            r = subprocess.run(
                [binary, f"--host={MARIADB_HOST}", f"--user={MARIADB_PANEL_USER}",
                 f"--password={MARIADB_PANEL_PASSWORD}", db_name],
                stdin=fin, capture_output=True, timeout=1800)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip()
            raise HestiaImportError(f"error importando el dump: {err[:300]}")
    finally:
        if tmp_sql and os.path.exists(tmp_sql):
            os.remove(tmp_sql)


def _ident(s: str) -> str:
    """Sanea un identificador de BD/usuario (alfanumérico + _)."""
    return re.sub(r"[^A-Za-z0-9_]", "", s)[:64]


# ─────────────────────────────────────────────────────────────────────────────
# Importación de CORREO (dominio + buzones + maildir, reusando el hash)
# ─────────────────────────────────────────────────────────────────────────────
def _dovecot_scheme(md5: str) -> Optional[str]:
    """Prefijo de esquema Dovecot para un hash de Hestia, o None si desconocido."""
    if not md5:
        return None
    if md5.startswith("$6$"):
        return "{SHA512-CRYPT}" + md5
    if md5.startswith("$5$"):
        return "{SHA256-CRYPT}" + md5
    if md5.startswith(("$2y$", "$2a$", "$2b$")):
        return "{BLF-CRYPT}" + md5
    if md5.startswith("$argon2"):
        return "{ARGON2ID}" + md5 if "argon2id" in md5 else "{ARGON2I}" + md5
    if md5.startswith("{"):       # ya viene con esquema
        return md5
    return None


def import_mail(backup: "HestiaBackup", mailinfo: Dict, owner, db, report: ImportReport):
    """Crea el dominio de correo y sus buzones, reutilizando el hash de cada uno.

    Estrategia: usa create_mailbox() (que monta maildir + postfix + dovecot) con
    una contraseña temporal y luego sobrescribe el hash en Dovecot con el ORIGINAL
    del backup vía _dovecot_set(). Así conservamos la contraseña del usuario sin
    duplicar toda la lógica de mailbox. Si el hash no es reconocible, dejamos la
    contraseña nueva y la reportamos.
    """
    import os as _os
    if _os.getenv("MAIL_ENABLED", "false").lower() != "true":
        report.fail("mail", mailinfo["domain"], "el módulo de correo no está activo")
        return

    from scripts.mail_manager import MailManager
    from api.models.models_mail import MailDomain, Mailbox
    from api.routes.databases import _generate_password

    domain = mailinfo["domain"]
    mgr = MailManager()

    # 1) Dominio de correo + registro
    mgr.create_mail_domain(domain, owner.username)
    mail_domain = MailDomain(user_id=owner.id, domain_name=domain, is_active=True)
    db.add(mail_domain)
    db.commit()
    db.refresh(mail_domain)

    # 2) Buzones
    n_ok = 0
    for acc in mailinfo.get("accounts", []):
        user = acc["account"]
        email = f"{user}@{domain}"
        try:
            quota = _quota_to_mb(acc.get("quota", "0"))
            scheme = _dovecot_scheme((acc.get("md5") or "").strip())

            tmp_pw = _generate_password()
            mgr.create_mailbox(owner.username, domain, user, tmp_pw, quota_mb=quota)

            if scheme:
                # Sobrescribir el hash temporal con el ORIGINAL del backup.
                mgr._dovecot_set(email, scheme, owner.username, domain, user, quota)
                mgr._reload_dovecot()
                stored_hash = scheme
            else:
                stored_hash = mgr.hash_password(tmp_pw)
                report.password("mail", email, tmp_pw)

            db.add(Mailbox(
                mail_domain_id=mail_domain.id,
                username=user,
                password_hash=stored_hash,
                quota_mb=quota,
                is_active=True,
            ))
            db.commit()
            n_ok += 1
        except Exception as e:
            report.fail("mail-account", email, e)

    # 3) Restaurar los maildir reales. Hestia los trae en accounts.tar(.gz);
    #    cPanel los trae descomprimidos en una carpeta (_accounts_dir).
    acc_dir = mailinfo.get("_accounts_dir")
    acc_tar = mailinfo.get("accounts_tar")
    if not acc_tar and not acc_dir and hasattr(backup, "_find_data_archive"):
        acc_tar = backup._find_data_archive("mail", domain, "accounts")
    try:
        if acc_dir and os.path.isdir(acc_dir):
            _restore_maildirs_dir(acc_dir, owner.username, domain)
        elif acc_tar and os.path.isfile(acc_tar):
            _restore_maildirs(acc_tar, owner.username, domain)
    except Exception as e:
        report.fail("mail-data", domain, f"maildir no restaurado: {e}")

    # Suscribir INBOX + carpetas estándar en cada buzón. Sin esto, el maildir
    # restaurado puede quedar con la INBOX NO suscrita → muchos clientes (y la
    # vista del panel) no muestran los correos aunque estén ahí. (Bug observado
    # en migraciones de Hestia.)
    for acc in mailinfo.get("accounts", []):
        _subscribe_mailboxes(f"{acc['account']}@{domain}")

    report.ok("mail", domain, f"{n_ok} buzón(es)")


def _subscribe_mailboxes(email: str) -> None:
    """Suscribe INBOX + carpetas estándar en un buzón (idempotente)."""
    import subprocess
    folders = ["INBOX", "Sent", "Drafts", "Trash", "Junk", "Archive"]
    try:
        subprocess.run(["doveadm", "mailbox", "subscribe", "-u", email] + folders,
                       capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"No se pudieron suscribir carpetas de {email}: {e}")


def _restore_maildirs_dir(src_dir: str, panel_username: str, domain: str) -> None:
    """Copia los maildir ya descomprimidos (cPanel) al mail dir del dominio."""
    import subprocess
    dest = f"/home/{panel_username}/mail/{domain}"
    _copy_into(src_dir, dest)
    subprocess.run(["chown", "-R", "vmail:vmail", dest], capture_output=True)


def _restore_maildirs(acc_tar: str, panel_username: str, domain: str) -> None:
    """Extrae accounts.tar y copia los maildirs al mail dir del dominio."""
    import subprocess
    dest = f"/home/{panel_username}/mail/{domain}"
    tmp = tempfile.mkdtemp(prefix="svq_maildata_")
    try:
        extract_data_archive(acc_tar, tmp)
        # El tar suele contener {cuenta}/{cur,new,tmp}. Copiamos su contenido.
        src = tmp
        # Si está anidado un nivel, ajustamos.
        entries = os.listdir(tmp)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            inner = os.path.join(tmp, entries[0])
            if any(os.path.isdir(os.path.join(inner, e)) for e in os.listdir(inner)):
                src = inner
        _copy_into(src, dest)
        subprocess.run(["chown", "-R", "vmail:vmail", dest], capture_output=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _quota_to_mb(q: str) -> int:
    q = (q or "").strip().lower()
    if q in ("", "0", "unlimited"):
        return 0
    try:
        return int(float(q))
    except ValueError:
        return 1024


# ─────────────────────────────────────────────────────────────────────────────
# Propuesta de DNS (clasifica registros del backup; NO toca nada)
# ─────────────────────────────────────────────────────────────────────────────
# Tipos que descartamos: los nameservers y el SOA los genera SVQPanel para este
# servidor; importar los del backup dejaría la zona apuntando al panel viejo.
_DNS_DISCARD_TYPES = {"NS", "SOA"}


def build_dns_proposal(zoneinfo: Dict, server_ipv4: Optional[str],
                       server_ipv6: Optional[str], old_ip: Optional[str]) -> List[Dict]:
    """Convierte los registros crudos del backup en una propuesta clasificada.

    Cada registro propuesto: {name, type, content, ttl, priority,
        action: 'keep'|'rewrite'|'discard', rewrite_suggested: bool,
        original_content, new_content, note, include: bool}.

    Reglas (el núcleo del fix):
      - NS/SOA → action='discard' (los pone SVQPanel).
      - A/AAAA cuyo content == old_ip (la IP del servidor Hestia viejo) →
        rewrite a la IP de SVQPanel. CUALQUIER OTRA IP se MANTIENE intacta
        (correo externo, oficina, otro hosting…).
      - Resto (CNAME/MX/TXT/SRV/CAA…) → keep.
    Esto es solo una SUGERENCIA: el usuario decide cada registro en la UI.
    """
    proposal = []
    default_ttl = int(zoneinfo.get("ttl") or 14400)
    for rec in zoneinfo.get("_records", []):
        rtype = (rec.get("TYPE") or "").upper()
        name = rec.get("RECORD") or "@"
        content = rec.get("VALUE") or ""
        if not rtype:
            continue
        try:
            ttl = int(rec.get("TTL") or default_ttl)
        except (ValueError, TypeError):
            ttl = default_ttl
        try:
            priority = int(rec.get("PRIORITY") or 0)
        except (ValueError, TypeError):
            priority = 0

        item = {
            "name": name, "type": rtype, "content": content,
            "ttl": ttl, "priority": priority,
            "original_content": content, "new_content": content,
            "rewrite_suggested": False, "note": "",
        }

        if rtype in _DNS_DISCARD_TYPES:
            item["action"] = "discard"
            item["include"] = False
            item["note"] = "Lo genera SVQPanel (nameservers/SOA del panel)."
        elif rtype == "A" and old_ip and content.strip() == old_ip.strip() and server_ipv4:
            item["action"] = "rewrite"
            item["rewrite_suggested"] = True
            item["new_content"] = server_ipv4
            item["include"] = True
            item["note"] = "Apuntaba al servidor antiguo → se reescribe a este servidor."
        elif rtype == "AAAA" and old_ip and server_ipv6 and content.strip() == (old_ip.strip()):
            # (poco común: AAAA == old_ip textual)
            item["action"] = "rewrite"
            item["rewrite_suggested"] = True
            item["new_content"] = server_ipv6
            item["include"] = True
            item["note"] = "Apuntaba al servidor antiguo → se reescribe a este servidor."
        else:
            item["action"] = "keep"
            item["include"] = True
            if rtype in ("A", "AAAA"):
                item["note"] = "Apunta a otra IP (no al hosting migrado): se mantiene."

        proposal.append(item)
    return proposal


# ─────────────────────────────────────────────────────────────────────────────
# Importación de DNS (zona + registros aprobados)
# ─────────────────────────────────────────────────────────────────────────────
def import_dns(backup: "HestiaBackup", zoneinfo: Dict, owner, db, report: ImportReport,
               approved_records: Optional[List[Dict]] = None,
               server_ipv4: Optional[str] = None, server_ipv6: Optional[str] = None):
    """Crea la zona DNS con los registros APROBADOS por el usuario.

    Si `approved_records` es None (p. ej. import por CLI sin UI), se usa la
    propuesta automática (rewrite de la IP vieja, mantener el resto). Los NS y el
    SOA SIEMPRE los pone SVQPanel (create_zone), nunca el backup.
    """
    from scripts.dns_manager import DNSManager
    from api.models.models_dns import DnsZone, DnsRecord

    domain = zoneinfo["domain"]
    old_ip = zoneinfo.get("ip")
    mgr = DNSManager()

    # NS/SOA + zona base la crea SVQPanel apuntando a ESTE servidor.
    try:
        serial = mgr.create_zone(domain, ipv4=server_ipv4 or old_ip)
    except PermissionError:
        serial = 2026052501

    zone = DnsZone(domain_name=domain, serial=serial,
                   ip_address=server_ipv4 or old_ip, ttl=int(zoneinfo.get("ttl") or 14400))
    db.add(zone)
    db.commit()
    db.refresh(zone)

    # Registros a crear: los aprobados por el usuario o, en su defecto, la
    # propuesta automática.
    if approved_records is None:
        approved_records = build_dns_proposal(zoneinfo, server_ipv4, server_ipv6, old_ip)

    n = 0
    for rec in approved_records:
        try:
            if not rec.get("include", True):
                continue
            rtype = (rec.get("type") or "").upper()
            if not rtype or rtype in _DNS_DISCARD_TYPES:
                continue
            # El valor final: si la acción es rewrite usamos new_content; si no,
            # el content (que el usuario pudo editar en la UI).
            if rec.get("action") == "rewrite":
                content = rec.get("new_content") or rec.get("content") or ""
            else:
                content = rec.get("content") or ""
            if not content:
                continue
            db.add(DnsRecord(
                zone_id=zone.id,
                record_type=rtype,
                name=rec.get("name") or "@",
                content=content,
                ttl=int(rec.get("ttl") or zoneinfo.get("ttl") or 14400),
                priority=int(rec.get("priority") or 0),
            ))
            n += 1
        except Exception:
            continue
    db.commit()

    # Reescribir la zona en BIND con los registros aprobados, si es posible.
    try:
        all_zones = [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]
        mgr.reload_zone(domain, all_zones)
    except Exception:
        pass

    report.ok("dns", domain, f"{n} registro(s) (NS/SOA de SVQPanel)")


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador de la importación (lo invoca el job en segundo plano)
# ─────────────────────────────────────────────────────────────────────────────
def open_backup(source_panel: str, tar_path: str, config_only: bool = False):
    """Factory: devuelve el backup adecuado según el panel de origen.

    Tanto HestiaBackup como CpanelBackup exponen analyze() y son context managers,
    así que el resto del pipeline los usa indistintamente.

    `config_only`: en el ANÁLISIS, no extrae los datos pesados (web/buzones/dumps)
    — basta con los .conf para el manifiesto y evita extraer varios GB (el 504).
    La importación real abre el backup SIN config_only (extrae todo).
    """
    if (source_panel or "hestia").lower() == "cpanel":
        from scripts.cpanel_import import CpanelBackup
        try:
            return CpanelBackup(tar_path, config_only=config_only)
        except TypeError:
            return CpanelBackup(tar_path)  # cpanel aún no soporta config_only
    return HestiaBackup(tar_path, config_only=config_only)


def run_import(tar_path: str, target_user_id: int, scope: List[str], db,
               dns_records: Optional[Dict[str, List[Dict]]] = None,
               source_panel: str = "hestia") -> Dict:
    """Importa el backup al usuario destino. Devuelve el informe (dict).

    `scope`: subconjunto de {'web','db','mail','dns'}. Asume que el preflight de
    conflictos ya pasó (terreno limpio). Cada recurso se registra en el informe;
    un fallo en uno no aborta los demás.
    `dns_records`: {domain: [registros aprobados]} desde la UI. Si una zona no
    está, se usa la propuesta automática.
    `source_panel`: 'hestia' | 'cpanel'.
    """
    from api.models.models_user import User

    report = ImportReport()
    dns_records = dns_records or {}
    owner = db.query(User).filter(User.id == target_user_id).first()
    if not owner:
        raise HestiaImportError("El usuario destino no existe.")
    if owner.role == "admin" or owner.is_admin:
        raise HestiaImportError(
            "El destino no puede ser un administrador; elige una cuenta de cliente.")

    # IPs de ESTE servidor (destino de las reescrituras). Autodetecta si no está
    # en Settings (mismo helper que usa la creación de zonas DNS del panel).
    server_ipv4 = server_ipv6 = None
    try:
        from api.routes.dns import _get_server_ipv4
        server_ipv4 = _get_server_ipv4(db) or None
    except Exception:
        pass
    try:
        from api.models.models_settings import Settings as _S
        _s = db.query(_S).filter(_S.id == 1).first()
        if _s:
            server_ipv6 = getattr(_s, "server_ipv6", None) or None
    except Exception:
        pass

    with open_backup(source_panel, tar_path) as backup:
        manifest = backup.analyze()

        if "web" in scope:
            for web in manifest["web"]:
                try:
                    import_web(backup, web, owner, db, report)
                except Exception as e:
                    db.rollback()
                    report.fail("web", web["domain"], e)

        if "db" in scope:
            for dbinfo in manifest["db"]:
                try:
                    import_db(backup, dbinfo, owner, db, report)
                except Exception as e:
                    db.rollback()
                    report.fail("db", dbinfo["db"], e)

        if "mail" in scope:
            for mailinfo in manifest["mail"]:
                try:
                    import_mail(backup, mailinfo, owner, db, report)
                except Exception as e:
                    db.rollback()
                    report.fail("mail", mailinfo["domain"], e)

        if "dns" in scope:
            for zoneinfo in manifest["dns"]:
                try:
                    approved = dns_records.get(zoneinfo["domain"])
                    import_dns(backup, zoneinfo, owner, db, report,
                               approved_records=approved,
                               server_ipv4=server_ipv4, server_ipv6=server_ipv6)
                except Exception as e:
                    db.rollback()
                    report.fail("dns", zoneinfo["domain"], e)

        # Aunque NO se importe el DNS del backup, todo dominio web migrado debe
        # tener una zona DNS con el template por defecto (igual que un dominio
        # creado normalmente en el panel) — si no, queda sin DNS propio. Solo
        # para los que aún no tienen zona (no pisa lo importado).
        if "web" in scope:
            for web in manifest["web"]:
                try:
                    _ensure_default_zone(web["domain"], owner, db, report,
                                         server_ipv4, server_ipv6)
                except Exception as e:
                    db.rollback()
                    report.fail("dns", web["domain"], f"zona por defecto: {e}")

    return report.to_dict()


def _ensure_default_zone(domain: str, owner, db, report, server_ipv4, server_ipv6):
    """Crea la zona DNS con el template por defecto si el dominio no tiene ya una
    (mismo comportamiento que crear un dominio en el panel). Idempotente."""
    from api.models.models_dns import DnsZone, DnsRecord
    from scripts.dns_manager import DNSManager, get_panel_nameservers
    from api.routes.dns import _build_template_records

    if db.query(DnsZone).filter(DnsZone.domain_name == domain).first():
        return  # ya tiene zona (importada o previa)

    mgr = DNSManager()
    try:
        ns1, ns2 = get_panel_nameservers(db)
    except Exception:
        ns1 = ns2 = None
    try:
        serial = mgr.create_zone(domain, ipv4=server_ipv4, ipv6=server_ipv6, ns1=ns1)
    except PermissionError:
        serial = 2026052501
    zone = DnsZone(domain_name=domain, serial=serial,
                   ip_address=server_ipv4, soa_ns=ns1 or None, ttl=14400)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    for r in _build_template_records(domain, server_ipv4, server_ipv6, ns1, ns2):
        db.add(DnsRecord(zone_id=zone.id, **r))
    db.commit()
    try:
        all_zones = [z.domain_name for z in
                     db.query(DnsZone).filter(DnsZone.is_active == True).all()]  # noqa: E712
        mgr.reload_zone(domain, all_zones)
    except Exception:
        pass
    report.ok("dns", domain, "zona por defecto creada")
