"""
Importador de backups de cPanel para SVQPanel.

Un backup completo de cPanel es un .tar.gz con una carpeta raíz `cpmove-USUARIO/`
(a veces `backup-*/...`). A diferencia de Hestia, los archivos van DESCOMPRIMIDOS
en carpetas y el DNS son ficheros de zona BIND reales. Estructura relevante:

    cpmove-USER/
      cp/USER                 → PLAN=, CONTACTEMAIL=, DNS= (dominio principal)
      userdata/main           → main_domain, addon_domains{}, sub_domains[]
      userdata/{DOMINIO}       → documentroot, ip, phpversion (ea-php74…)
      homedir/public_html/     → archivos del dominio principal (sin comprimir)
      homedir/{docroot}/       → archivos de cada addon (su documentroot)
      homedir/mail/{DOM}/{cuenta}/  → maildir
      etc/{DOM}/shadow         → cuenta:HASH:...  (hash de cada buzón)
      etc/{DOM}/quota          → cuenta:BYTES
      mysql/{DB}.create        → "CREATE DATABASE ..." (nombre)
      mysql/{DB}.sql           → dump de datos
      mysql.sql                → GRANTs (usuario + hash nativo)
      dnszones/{DOM}.db        → fichero de zona BIND

Este parser produce el MISMO manifiesto que `hestia_import.HestiaBackup.analyze()`,
de modo que TODO el pipeline (preflight, import_web/db/mail/dns, DNS interactivo,
job, frontend) se reutiliza sin cambios.
"""

import os
import re
import shutil
import tempfile
import logging
from typing import Dict, List, Optional

from scripts.hestia_import import safe_extract_tar, parse_bind_zone

logger = logging.getLogger(__name__)


class CpanelImportError(RuntimeError):
    """Error legible del importador cPanel (el endpoint lo da como 4xx)."""


def _php_from_ea(value: str) -> Optional[str]:
    """'ea-php74' / 'ea-php80' / 'php7.4' → '7.4'. None si no se reconoce."""
    if not value:
        return None
    m = re.search(r"(\d)\.?(\d)", value)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


def _parse_cpanel_yaml(text: str) -> Dict:
    """Parser minimalista del 'YAML' de cPanel (userdata/main, userdata/{dom}).

    Soporta `clave: valor`, listas (`- item`) y mapas anidados de 1 nivel
    (`addon_domains:` seguido de `  sub.dom: dom`). Es tolerante: no valida.
    """
    result: Dict = {}
    current_key = None
    current_indent = 0
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()

        if line.startswith("- "):
            # Elemento de lista del último current_key. Si la cabecera se creó
            # como dict vacío ({}), la convertimos a lista al ver el primer item.
            if current_key is not None:
                if not isinstance(result.get(current_key), list):
                    result[current_key] = []
                result[current_key].append(line[2:].strip())
            continue

        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if indent > current_indent and current_key is not None and isinstance(result.get(current_key), dict):
                # Entrada de un mapa anidado
                result[current_key][key] = val
            elif val == "":
                # Cabecera: puede ser lista o mapa; lo decidimos al ver el hijo
                result[key] = {}
                current_key = key
                current_indent = indent
            else:
                result[key] = val
                current_key = key
                current_indent = indent
    # Limpiar mapas vacíos que en realidad eran listas/escala
    return result


class CpanelBackup:
    """Abre y analiza un backup de cPanel. Context manager: limpia el tmp."""

    def __init__(self, tar_path: str):
        if not os.path.isfile(tar_path):
            raise CpanelImportError(f"No existe el archivo de backup: {tar_path}")
        self.tar_path = tar_path
        self.tmpdir = tempfile.mkdtemp(prefix="svq_cpanel_")
        self.root: Optional[str] = None
        self._extracted = False

    def __enter__(self):
        self.extract()
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── extracción / detección ────────────────────────────────────────────────
    def extract(self):
        if self._extracted:
            return
        safe_extract_tar(self.tar_path, self.tmpdir)
        self._extracted = True
        self.root = self._find_root()
        if not self.root:
            raise CpanelImportError(
                "El archivo no parece un backup de cPanel "
                "(falta cp/, userdata/ o homedir/).")

    def _is_cpanel_root(self, d: str) -> bool:
        return (os.path.isdir(os.path.join(d, "userdata")) or
                os.path.isdir(os.path.join(d, "homedir")) or
                os.path.isdir(os.path.join(d, "cp")))

    def _find_root(self) -> Optional[str]:
        if self._is_cpanel_root(self.tmpdir):
            return self.tmpdir
        for entry in os.listdir(self.tmpdir):
            sub = os.path.join(self.tmpdir, entry)
            if os.path.isdir(sub) and self._is_cpanel_root(sub):
                return sub
        return None

    # ── helpers de lectura ─────────────────────────────────────────────────────
    def _read(self, *parts) -> str:
        p = os.path.join(self.root, *parts)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def _exists(self, *parts) -> bool:
        return os.path.exists(os.path.join(self.root, *parts))

    # ── usuario / dominios ─────────────────────────────────────────────────────
    def parse_userdata_main(self) -> Dict:
        """Lee userdata/main → {main_domain, addon_domains{}, sub_domains[]…}."""
        return _parse_cpanel_yaml(self._read("userdata", "main"))

    def _domain_userdata(self, domain: str) -> Dict:
        """Lee userdata/{dom} (documentroot, ip, phpversion…)."""
        return _parse_cpanel_yaml(self._read("userdata", domain))

    def all_domains(self) -> List[str]:
        """Dominio principal + addons + subdominios (todos los del backup)."""
        main = self.parse_userdata_main()
        domains = []
        md = main.get("main_domain")
        if isinstance(md, str) and md:
            domains.append(md)
        # addon_domains: mapa {addon: subdominio_interno}
        addons = main.get("addon_domains")
        if isinstance(addons, dict):
            domains.extend([k for k in addons.keys() if k])
        # sub_domains: lista
        subs = main.get("sub_domains")
        if isinstance(subs, list):
            domains.extend([s for s in subs if s])
        elif isinstance(subs, dict):
            domains.extend([k for k in subs.keys() if k])
        # Dedup conservando orden
        seen = set()
        out = []
        for d in domains:
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        return out

    # ── análisis por recurso (manifiesto común) ────────────────────────────────
    def analyze_user(self) -> Dict:
        cp = {}
        # cp/{user}: hay un único fichero; lo localizamos.
        cpdir = os.path.join(self.root, "cp")
        if os.path.isdir(cpdir):
            files = [f for f in os.listdir(cpdir) if os.path.isfile(os.path.join(cpdir, f))]
            if files:
                for line in self._read("cp", files[0]).splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        cp[k.strip()] = v.strip().strip("'\"")
        return cp

    def analyze_web(self) -> List[Dict]:
        out = []
        homedir = os.path.join(self.root, "homedir")
        for domain in self.all_domains():
            ud = self._domain_userdata(domain)
            docroot = ud.get("documentroot") or ""
            php = _php_from_ea(ud.get("phpversion") or "")
            # Localizar la carpeta de datos: el documentroot relativo a homedir.
            data_dir = None
            if docroot:
                # documentroot suele ser /home/USER/public_html o .../addon
                rel = docroot.split("/homedir/", 1)[-1] if "/homedir/" in docroot else None
                if not rel:
                    # quitar el prefijo /home/USER/
                    m = re.sub(r"^/home/[^/]+/", "", docroot)
                    rel = m
                cand = os.path.join(homedir, rel)
                if os.path.isdir(cand):
                    data_dir = cand
            if not data_dir:
                # fallback: public_html para el dominio principal
                cand = os.path.join(homedir, "public_html")
                if os.path.isdir(cand):
                    data_dir = cand
            out.append({
                "domain": domain,
                "aliases": [],
                "php_version": php,
                "ssl": self._exists("apache_tls", domain),
                "letsencrypt": False,
                "custom_docroot": None,
                "redirect": None,
                "has_data": bool(data_dir),
                "_data_dir": data_dir,
                "ip": ud.get("ip") or None,
            })
        return out

    def analyze_db(self) -> List[Dict]:
        out = []
        mysqldir = os.path.join(self.root, "mysql")
        if not os.path.isdir(mysqldir):
            return out
        # Mapa usuario→hash y db→usuarios desde mysql.sql (GRANTs).
        grants_text = self._read("mysql.sql")
        user_hash = _parse_mysql_grants(grants_text)
        for fn in sorted(os.listdir(mysqldir)):
            if not fn.endswith(".create"):
                continue
            dbname = fn[:-len(".create")]
            create_sql = self._read("mysql", fn)
            m = re.search(r"CREATE DATABASE[^`']*[`']([^`']+)[`']", create_sql, re.I)
            real_name = m.group(1) if m else dbname
            dump = os.path.join(mysqldir, dbname + ".sql")
            # Usuario y hash: el primero que tenga privilegios sobre esta BD.
            dbuser, md5 = _db_user_for(real_name, grants_text, user_hash)
            out.append({
                "db": real_name,
                "dbuser": dbuser or "",
                "md5": md5 or "",
                "type": "mysql",
                "charset": "utf8mb4",
                "has_dump": os.path.isfile(dump),
                "_dump": dump if os.path.isfile(dump) else None,
            })
        return out

    def analyze_mail(self) -> List[Dict]:
        out = []
        maildir_base = os.path.join(self.root, "homedir", "mail")
        if not os.path.isdir(maildir_base):
            return out
        for domain in sorted(os.listdir(maildir_base)):
            dpath = os.path.join(maildir_base, domain)
            if not os.path.isdir(dpath):
                continue
            # Hashes y cuotas de etc/{dom}/shadow y etc/{dom}/quota.
            shadow = _parse_colon_file(self._read("etc", domain, "shadow"))
            quotas = _parse_colon_file(self._read("etc", domain, "quota"))
            accounts = []
            for acc in sorted(os.listdir(dpath)):
                accpath = os.path.join(dpath, acc)
                if not os.path.isdir(accpath):
                    continue
                hashval = shadow.get(acc, "")
                qbytes = quotas.get(acc, "")
                accounts.append({
                    "account": acc,
                    "md5": hashval,
                    "quota": _bytes_to_mb(qbytes),
                    "fwd": None,
                })
            out.append({
                "domain": domain,
                "accounts": accounts,
                "_accounts_dir": dpath,   # maildirs ya descomprimidos
                "accounts_tar": None,
            })
        return out

    def analyze_dns(self) -> List[Dict]:
        out = []
        dnsdir = os.path.join(self.root, "dnszones")
        if not os.path.isdir(dnsdir):
            return out
        for fn in sorted(os.listdir(dnsdir)):
            if not fn.endswith(".db"):
                continue
            domain = fn[:-len(".db")]
            zone_text = self._read("dnszones", fn)
            records, old_ip = parse_bind_zone(zone_text, domain)
            out.append({
                "domain": domain,
                "ip": old_ip,
                "ttl": "14400",
                "records_count": len(records),
                "_records": records,
            })
        return out

    def analyze(self) -> Dict:
        user = self.analyze_user()
        return {
            "system": "cpanel",
            "user": {
                "contact": user.get("CONTACTEMAIL", ""),
                "fname": "",
                "lname": "",
                "package": user.get("PLAN", ""),
            },
            "web": self.analyze_web(),
            "db": self.analyze_db(),
            "mail": self.analyze_mail(),
            "dns": self.analyze_dns(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de parsing (db grants, shadow/quota, bytes)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_mysql_grants(text: str) -> Dict[str, str]:
    """Devuelve {usuario: hash} de las sentencias GRANT/CREATE USER de mysql.sql."""
    user_hash: Dict[str, str] = {}
    # GRANT ... TO 'user'@'host' IDENTIFIED BY PASSWORD '<hash>'
    for m in re.finditer(
            r"TO\s+'([^']+)'@'[^']+'\s+IDENTIFIED BY PASSWORD\s+'([^']+)'", text, re.I):
        user_hash[m.group(1)] = m.group(2)
    # CREATE USER 'user'@'host' IDENTIFIED ... AS '<hash>'  / BY PASSWORD '<hash>'
    for m in re.finditer(
            r"CREATE USER\s+'([^']+)'@'[^']+'[^;]*?(?:AS|PASSWORD)\s+'([^']+)'", text, re.I):
        user_hash.setdefault(m.group(1), m.group(2))
    return user_hash


def _db_user_for(dbname: str, grants_text: str, user_hash: Dict[str, str]):
    """Encuentra el usuario (y su hash) con privilegios sobre `dbname`."""
    # GRANT ... ON `db`.* TO 'user'@...
    pat = re.compile(
        r"ON\s+[`']?" + re.escape(dbname) + r"[`']?\.\*\s+TO\s+'([^']+)'", re.I)
    m = pat.search(grants_text)
    if m:
        u = m.group(1)
        return u, user_hash.get(u, "")
    # Si no, el primer usuario conocido
    if user_hash:
        u = next(iter(user_hash))
        return u, user_hash[u]
    return "", ""


def _parse_colon_file(text: str) -> Dict[str, str]:
    """Parsea ficheros tipo passwd/shadow/quota: 'clave:valor[:...]' → {clave: valor}."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        parts = line.split(":")
        out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _bytes_to_mb(value: str) -> str:
    """Convierte un valor en bytes (string) a MB (string). '' o 0 → '0' (sin límite)."""
    v = (value or "").strip()
    if not v or v in ("0", "unlimited"):
        return "0"
    try:
        return str(int(int(v) / (1024 * 1024)))
    except ValueError:
        return "0"
