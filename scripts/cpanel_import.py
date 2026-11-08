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

from scripts.hestia_import import safe_extract_tar, parse_bind_zone, _tmp_dir

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
        # En disco real, NO en /tmp (tmpfs en Debian 13: un backup de varios GB
        # lo llena y se come la RAM). Prefijo svq_hestia_ para que lo barra
        # purge_migration_tmp si un OOM se salta el cleanup.
        self.tmpdir = tempfile.mkdtemp(prefix="svq_hestia_cpanel_", dir=_tmp_dir())
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
    def _cp_user_file(self) -> str:
        """Nombre del fichero cp/{usuario} (= usuario de cPanel), '' si no hay."""
        cpdir = os.path.join(self.root, "cp")
        if os.path.isdir(cpdir):
            files = sorted(f for f in os.listdir(cpdir)
                           if os.path.isfile(os.path.join(cpdir, f)))
            if files:
                return files[0]
        return ""

    def guess_username(self) -> str:
        """Usuario de cPanel: el fichero cp/{usuario} (vale para cpmove- y para
        las copias backup-FECHA_usuario); si no, el nombre de la carpeta raíz."""
        name = self._cp_user_file()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", name or ""):
            return name.lower()
        base = os.path.basename(os.path.normpath(self.root or ""))
        if base.startswith("cpmove-"):
            return base[len("cpmove-"):].lower()
        m = re.match(r"backup-[\d.]+_[\d-]+_([A-Za-z0-9_-]+)$", base)
        if m:
            return m.group(1).lower()
        m = re.match(r"(?:cpmove-|backup-[\d.]+_[\d-]+_)([A-Za-z0-9_-]+?)(?:\.tar.*)?$",
                     os.path.basename(self.tar_path))
        return m.group(1).lower() if m else ""

    def analyze_user(self) -> Dict:
        cp = {}
        # cp/{user}: hay un único fichero; lo localizamos.
        name = self._cp_user_file()
        for line in (self._read("cp", name) if name else "").splitlines():
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

    def analyze_forwarders(self, domain: str) -> Dict[str, List[str]]:
        """Reenvíos de cPanel (va/{dominio}): {local: [destinos]}; '@' = catch-all."""
        return _parse_valiases(self._read("va", domain), domain)

    def analyze_mail(self) -> List[Dict]:
        out = []
        maildir_base = os.path.join(self.root, "homedir", "mail")
        domains = set()
        if os.path.isdir(maildir_base):
            domains |= {d for d in os.listdir(maildir_base)
                        if os.path.isdir(os.path.join(maildir_base, d)) and "." in d}
        # Dominios con reenvíos pero sin ningún buzón (solo redirecciones).
        vadir = os.path.join(self.root, "va")
        if os.path.isdir(vadir):
            domains |= {d for d in os.listdir(vadir)
                        if "." in d and self.analyze_forwarders(d)}
        for domain in sorted(domains):
            dpath = os.path.join(maildir_base, domain)
            # Hashes y cuotas de etc/{dom}/shadow y etc/{dom}/quota.
            shadow = _parse_colon_file(self._read("etc", domain, "shadow"))
            quotas = _parse_colon_file(self._read("etc", domain, "quota"))
            fwds = self.analyze_forwarders(domain)
            accounts = []
            for acc in (sorted(os.listdir(dpath)) if os.path.isdir(dpath) else []):
                accpath = os.path.join(dpath, acc)
                if not os.path.isdir(accpath):
                    continue
                hashval = shadow.get(acc, "")
                qbytes = quotas.get(acc, "")
                # En cPanel, un reenviador sobre una dirección que además es
                # buzón entrega en los dos sitios → reenvío CON copia local.
                dest = fwds.pop(acc.lower(), None)
                accounts.append({
                    "account": acc,
                    "md5": hashval,
                    "quota": _bytes_to_mb(qbytes),
                    "fwd": ",".join(dest) if dest else None,
                    "fwd_only": False,
                })
            out.append({
                "domain": domain,
                "accounts": accounts,
                # Reenviadores sin buzón → alias puros (no se crea un buzón vacío).
                "aliases": [{"source": src, "destinations": dst}
                            for src, dst in sorted(fwds.items())],
                "_accounts_dir": dpath if os.path.isdir(dpath) else None,
                "accounts_tar": None,
            })
        return out

    def analyze_cron(self, web: Optional[List[Dict]] = None) -> List[Dict]:
        """Crontab del usuario (cron/{usuario}), con las rutas de cada docroot de
        cPanel traducidas a las de SVQPanel (/home/U/web/DOMINIO/public_html)."""
        user = self.guess_username()
        crondir = os.path.join(self.root, "cron")
        text = ""
        if os.path.isdir(crondir):
            name = user if os.path.isfile(os.path.join(crondir, user or "-")) else None
            if not name:
                files = sorted(f for f in os.listdir(crondir)
                               if os.path.isfile(os.path.join(crondir, f)))
                name = files[0] if files else None
            text = self._read("cron", name) if name else ""
        # docroot relativo a /home/U → dominio (el más largo primero, para que
        # public_html/tienda gane a public_html).
        docroots = []
        for w in (web if web is not None else self.analyze_web()):
            ud = self._domain_userdata(w["domain"])
            rel = re.sub(r"^/home\d*/[^/]+/", "", ud.get("documentroot") or "").strip("/")
            if rel:
                docroots.append((rel, w["domain"]))
        docroots.sort(key=lambda x: -len(x[0]))
        return parse_cpanel_crontab(text, docroots)

    def analyze(self) -> Dict:
        user = self.analyze_user()
        web = self.analyze_web()
        return {
            "system": "cpanel",
            "username": self.guess_username(),
            "user": {
                "contact": user.get("CONTACTEMAIL", ""),
                "fname": "",
                "lname": "",
                "package": user.get("PLAN", ""),
            },
            "web": web,
            "db": self.analyze_db(),
            "mail": self.analyze_mail(),
            "dns": self.analyze_dns(),
            "cron": self.analyze_cron(web),
        }

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

# ─────────────────────────────────────────────────────────────────────────────
# Helpers de parsing (reenvíos, crontab, db grants, shadow/quota, bytes)
# ─────────────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[^@\s\"'<>,|:]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _parse_valiases(text: str, domain: str) -> Dict[str, List[str]]:
    """va/{dominio} de cPanel (formato /etc/valiases):
        info@dom.com: alguien@gmail.com, otro@dom.com
        *: usuario_cpanel            ← dirección por defecto (catch-all)
    Solo se importan destinos que son direcciones de correo: :fail:, :blackhole:,
    tuberías (|/ruta) o el usuario de sistema de cPanel no tienen equivalente y se
    descartan. El catch-all solo si apunta a una dirección real."""
    out: Dict[str, List[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        src, _, dst = line.partition(":")
        src = src.strip().strip('"').lower()
        if src == "*":
            local = "@"
        elif src.endswith("@" + domain.lower()):
            local = src[: -len(domain) - 1]
        else:
            continue
        if not local:
            continue
        dests = []
        for d in dst.split(","):
            d = d.strip().strip('"')
            if _EMAIL_RE.match(d) and d.lower() != f"{local}@{domain}".lower():
                dests.append(d)
        if dests:
            cur = out.setdefault(local, [])
            cur.extend(x for x in dests if x not in cur)
    return out


_CRON_MACROS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
                "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
                "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
                "@hourly": "0 * * * *"}


def _cpanel_cron_cmd(cmd: str, docroots: List[tuple]) -> str:
    """Rutas y PHP de cPanel → los de SVQPanel (el usuario lo cambia luego
    _adapt_cron_command, igual que en Hestia):
      /home/U/public_html/x.php → /home/U/web/DOMINIO/public_html/x.php
      /opt/cpanel/ea-php74/root/usr/bin/php → /usr/bin/php7.4
      /usr/local/bin/php → /usr/bin/php"""
    cmd = re.sub(r"/opt/cpanel/ea-php(\d)(\d)/root/usr/bin/php(?:-cgi|-cli)?",
                 r"/usr/bin/php\1.\2", cmd)
    cmd = re.sub(r"/usr/local/bin/(?:ea-php(\d)(\d)|php)\b",
                 lambda m: f"/usr/bin/php{m.group(1)}.{m.group(2)}" if m.group(1) else "/usr/bin/php",
                 cmd)

    def _path(m):
        home = re.sub(r"^/home\d*/", "/home/", m.group(1))   # /home2/U/ → /home/U/
        rest = m.group(2)
        for rel, dom in docroots:
            if rest == rel or rest.startswith(rel + "/"):
                return f"{home}web/{dom}/public_html{rest[len(rel):]}"
        return m.group(0)

    return re.sub(r"(/home\d*/[A-Za-z0-9._-]+/)([^\s;&|>'\"]*)", _path, cmd)


def parse_cpanel_crontab(text: str, docroots: List[tuple]) -> List[Dict]:
    """crontab de cPanel → manifiesto de cron común (mismo formato que Hestia).
    Ignora variables (MAILTO=, SHELL=…), comentarios y @reboot."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            continue
        if line.startswith("@"):
            macro, _, cmd = line.partition(" ")
            sched = _CRON_MACROS.get(macro.lower())
            if not sched or not cmd.strip():
                continue          # @reboot y desconocidos: no hay equivalente
            parts = sched.split() + [cmd.strip()]
        else:
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
        out.append({
            "min": parts[0], "hour": parts[1], "day": parts[2],
            "month": parts[3], "wday": parts[4],
            "cmd": _cpanel_cron_cmd(parts[5], docroots),
            "suspended": False,
            "origin": "cPanel",
        })
    return out


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
