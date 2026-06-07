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
# Extracción segura de tar (anti path-traversal)
# ─────────────────────────────────────────────────────────────────────────────
def _is_within(base: str, target: str) -> bool:
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def safe_extract_tar(tar_path: str, dest: str) -> None:
    """Extrae un .tar(.gz) validando que ningún miembro escape de `dest`.

    Soporta el filtro 'data' de Python 3.12+; en versiones previas valida a mano.
    """
    mode = "r:*"  # autodetecta gz/bz2/xz/plano
    with tarfile.open(tar_path, mode) as tar:
        members = tar.getmembers()
        for m in members:
            member_path = os.path.join(dest, m.name)
            if not _is_within(dest, member_path):
                raise HestiaImportError(
                    f"El backup contiene una ruta no segura: {m.name!r}")
            # No seguimos enlaces fuera del destino
            if m.issym() or m.islnk():
                link_target = os.path.join(dest, os.path.dirname(m.name), m.linkname)
                if not _is_within(dest, link_target):
                    raise HestiaImportError(
                        f"El backup contiene un enlace no seguro: {m.name!r}")
        try:
            tar.extractall(dest, filter="data")   # Python ≥ 3.12
        except TypeError:
            tar.extractall(dest)                   # validado arriba


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

    def __init__(self, tar_path: str):
        if not os.path.isfile(tar_path):
            raise HestiaImportError(f"No existe el archivo de backup: {tar_path}")
        self.tar_path = tar_path
        self.tmpdir = tempfile.mkdtemp(prefix="svq_hestia_")
        self.system: Optional[str] = None   # "hestia" | "vesta"
        self._extracted = False

    def __enter__(self):
        self.extract()
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── extracción ──────────────────────────────────────────────────────────
    def extract(self):
        if self._extracted:
            return
        safe_extract_tar(self.tar_path, self.tmpdir)
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
        """Busca {base}.tar.gz / .tar.zst en {kind}/{name}/."""
        d = os.path.join(self.root, kind, name)
        for ext in (".tar.gz", ".tar.zst", ".tar.zstd", ".tar"):
            p = os.path.join(d, base + ext)
            if os.path.isfile(p):
                return p
        return None

    def _find_db_dump(self, dbname: str, dbtype: str) -> Optional[str]:
        d = os.path.join(self.root, "db", dbname)
        if not os.path.isdir(d):
            return None
        # {db}.{type}.sql.{gz,zst} — pero por robustez buscamos cualquier .sql.*
        for fn in os.listdir(d):
            if fn.startswith(dbname) and ".sql" in fn:
                return os.path.join(d, fn)
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
def find_conflicts(manifest: Dict, db) -> List[str]:
    """Devuelve una lista de conflictos legibles (recursos que YA existen).

    `db` es una Session de SQLAlchemy del panel. Comprueba dominios, BDs y
    dominios de correo/zonas DNS contra las tablas existentes.
    """
    from api.models.models_domain import Domain
    from api.models.models_client_db import ClientDatabase
    conflicts: List[str] = []

    for w in manifest.get("web", []):
        if db.query(Domain).filter(Domain.domain_name == w["domain"]).first():
            conflicts.append(f"El dominio web «{w['domain']}» ya existe en el panel.")

    for d in manifest.get("db", []):
        if db.query(ClientDatabase).filter(ClientDatabase.db_name == d["db"]).first():
            conflicts.append(f"La base de datos «{d['db']}» ya existe en el panel.")

    # Mail y DNS: comprobar si los modelos existen (import defensivo).
    try:
        from api.models.models_mail import MailDomain
        for m in manifest.get("mail", []):
            if db.query(MailDomain).filter(MailDomain.domain_name == m["domain"]).first():
                conflicts.append(f"El dominio de correo «{m['domain']}» ya existe.")
    except ImportError:
        pass
    try:
        from api.models.models_dns import DnsZone
        for z in manifest.get("dns", []):
            if db.query(DnsZone).filter(DnsZone.domain_name == z["domain"]).first():
                conflicts.append(f"La zona DNS «{z['domain']}» ya existe.")
    except ImportError:
        pass

    return conflicts
