"""
Importador de cuentas de CWP (CentOS Web Panel) para SVQPanel.

CWP no tiene un backup por cuenta con formato estable, así que el origen lo
genera NUESTRO exportador (scripts/cwp_export.sh, que el panel ejecuta por SSH
en el CWP). El .tar trae los datos de CWP tal cual (salida de `mysql -B` de
root_cwp y postfix) más los volcados de BD, zonas y maildirs. Ver la estructura
en la cabecera de cwp_export.sh.

Como el de cPanel, produce el MISMO manifiesto que HestiaBackup.analyze(): todo
el pipeline (preflight, import_web/db/mail/dns, job, interfaz) se reutiliza.
Hereda de CpanelBackup lo que coincide (BD en mysql/, zonas en dnszones/).

Lo propio de CWP:
  - Webs en /home/U/public_html (y addons/subdominios con su path) → SVQPanel
    las pone en /home/U/web/DOMINIO/public_html: las rutas absolutas viejas en
    la configuración de las webs se reescriben (post_import).
  - PHP por web de los vhosts de Apache (/opt/alt/php-fpmNN).
  - Hashes de buzón con esquema ({SHA512-CRYPT}…, {MD5-CRYPT}…, $1$…): se
    conservan. Un "{MD5-CRYPT}" sin hash es un buzón SIN contraseña: se le
    genera una nueva y sale en el informe.
  - Reenvíos de postfix.alias: si el destino incluye al propio buzón, es con
    copia; si no, es reenvío puro (en postfix el alias manda sobre el buzón).
  - Carpetas .spam y .Spam (las dos existen en CWP) → se funden en .Junk.
  - DKIM de opendkim con su selector: se instala la MISMA clave, así el TXT que
    ya está publicado sigue valiendo sin tocar el DNS.
  - Sieve y autorespuestas (postfix.vacation) → los sitios de SVQPanel.
"""

import logging
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from scripts.cpanel_import import (CpanelBackup, CpanelImportError, parse_cpanel_crontab,
                                   _cpanel_cron_cmd)
from scripts.hestia_import import safe_extract_tar

logger = logging.getLogger(__name__)


class CwpImportError(CpanelImportError):
    """Error legible del importador CWP (el endpoint lo da como 4xx)."""


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de los .tsv (salida de `mysql -B`: tabuladores y escapes \t \n \\ \0)
# ─────────────────────────────────────────────────────────────────────────────
_TSV_ESC = {"t": "\t", "n": "\n", "\\": "\\", "0": "\0", "r": "\r"}


def _unescape(value: str) -> str:
    if "\\" not in value:
        return value
    return re.sub(r"\\(.)", lambda m: _TSV_ESC.get(m.group(1), m.group(1)), value)


def parse_tsv(text: str) -> List[Dict[str, str]]:
    """Filas de una salida `mysql -B` con cabecera → [{columna: valor}]. NULL → ''."""
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]
    if not lines:
        return []
    cols = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        vals = ln.split("\t")
        row = {}
        for i, c in enumerate(cols):
            v = _unescape(vals[i]) if i < len(vals) else ""
            row[c] = "" if v == "NULL" else v
        rows.append(row)
    return rows


def _php_from_cwp(value: str) -> Optional[str]:
    """'56' / '74' / '82' (de /opt/alt/php-fpmNN) → '5.6' / '7.4' / '8.2'."""
    m = re.fullmatch(r"(\d)(\d)", (value or "").strip())
    return f"{m.group(1)}.{m.group(2)}" if m else None


def cwp_hash(value: str) -> str:
    """Hash de postfix.mailbox utilizable por Dovecot, o '' si no hay contraseña.

    CWP guarda '{ESQUEMA}hash' o un '$1$…' sin esquema (MD5-CRYPT, el
    default_pass_scheme de su Dovecot). '{MD5-CRYPT}' a secas = sin contraseña."""
    v = (value or "").strip()
    m = re.fullmatch(r"\{[A-Z0-9.-]+\}(.*)", v)
    if m and not m.group(1).strip():
        return ""
    return v


_CWP_PHP_BIN = re.compile(r"/opt/alt/php(?:-fpm)?(\d)(\d)/usr/bin/php(?:-cgi|-cli)?\b")


def _cwp_cron_cmd(cmd: str, docroots: List[tuple]) -> str:
    """Comando de cron de CWP → rutas y PHP de SVQPanel."""
    cmd = _CWP_PHP_BIN.sub(r"/usr/bin/php\1.\2", cmd)
    return _cpanel_cron_cmd(cmd, docroots)


def adapt_cwp_sieve(text: str) -> str:
    """Sieve de CWP → SVQPanel: sin el prefijo 'INBOX.' (namespace de CWP) y con
    las carpetas de spam fundidas en Junk."""
    def _folder(m):
        name = m.group(2)
        if name.startswith("INBOX."):
            name = name[len("INBOX."):]
        if name.lower() in ("spam", "junk"):
            name = "Junk"
        return f'{m.group(1)}"{name}"'
    return re.sub(r'(fileinto\s+(?::\w+\s+)*)"([^"]+)"', _folder, text)


# ─────────────────────────────────────────────────────────────────────────────
# Maildirs: .spam/.Spam → .Junk y fuera índices (Dovecot los rehace)
# ─────────────────────────────────────────────────────────────────────────────
_SPAM_FOLDERS = (".spam", ".Spam", ".INBOX.spam", ".INBOX.Spam")


def normalize_maildir(acc_dir: str) -> int:
    """Funde las carpetas de spam de un buzón en .Junk. Devuelve los correos movidos."""
    moved = 0
    junk = os.path.join(acc_dir, ".Junk")
    for name in _SPAM_FOLDERS:
        src = os.path.join(acc_dir, name)
        if not os.path.isdir(src) or os.path.islink(src):
            continue
        for sub in ("cur", "new", "tmp"):
            os.makedirs(os.path.join(junk, sub), exist_ok=True)
        for sub in ("cur", "new"):
            sdir = os.path.join(src, sub)
            if not os.path.isdir(sdir):
                continue
            for fn in os.listdir(sdir):
                dst = os.path.join(junk, sub, fn)
                if not os.path.exists(dst):
                    shutil.move(os.path.join(sdir, fn), dst)
                    moved += 1
        shutil.rmtree(src, ignore_errors=True)
    if moved:
        # Los UID del Junk original ya no casan con lo que hay: que Dovecot los rehaga.
        for fn in ("dovecot-uidlist", "dovecot-uidvalidity"):
            p = os.path.join(junk, fn)
            if os.path.isfile(p):
                os.remove(p)
    # La lista de suscripciones de CWP lleva nombres con 'INBOX.': se rehace al importar.
    sub_file = os.path.join(acc_dir, "subscriptions")
    if os.path.isfile(sub_file):
        os.remove(sub_file)
    return moved


# ─────────────────────────────────────────────────────────────────────────────
# Rutas absolutas viejas dentro de las webs
# ─────────────────────────────────────────────────────────────────────────────
_PATH_EXTS = (".php", ".inc", ".ini", ".htaccess", ".json", ".xml", ".yml", ".yaml",
              ".env", ".conf", ".cfg", ".tpl")
_PATH_SKIP_DIRS = {"uploads", "cache", "node_modules", ".git", "vendor", "wflogs", "logs"}
_PATH_MAX_FILE = 1024 * 1024
_PATH_MAX_FILES = 60000


def rewrite_paths(root: str, mapping: List[tuple]) -> List[str]:
    """Reescribe rutas absolutas del origen en la configuración de una web.

    `mapping`: [(ruta_vieja, ruta_nueva)], se aplica la más larga primero (un
    addon dentro de public_html gana al public_html del principal). Solo ficheros
    de texto de configuración/código de hasta 1 MB. Devuelve los modificados
    (relativos a root)."""
    pairs = sorted(((o.rstrip("/").encode(), n.rstrip("/").encode()) for o, n in mapping if o),
                   key=lambda p: -len(p[0]))
    if not pairs:
        return []
    pattern = re.compile(b"(" + b"|".join(re.escape(o) for o, _ in pairs) + b")(?=[/'\"\\s;:)]|$)")
    lookup = dict(pairs)
    changed, seen = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PATH_SKIP_DIRS]
        for fn in filenames:
            if not (fn.endswith(_PATH_EXTS) or fn in (".htaccess", ".user.ini")):
                continue
            seen += 1
            if seen > _PATH_MAX_FILES:
                return changed
            path = os.path.join(dirpath, fn)
            try:
                if os.path.islink(path) or os.path.getsize(path) > _PATH_MAX_FILE:
                    continue
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if not any(o in data for o, _ in pairs):
                continue
            new = pattern.sub(lambda m: lookup[m.group(1)], data)
            if new != data:
                try:
                    with open(path, "wb") as f:
                        f.write(new)
                    changed.append(os.path.relpath(path, root))
                except OSError as e:
                    logger.warning(f"[cwp] no se pudieron reescribir rutas en {path}: {e}")
    return changed


# ─────────────────────────────────────────────────────────────────────────────
# El backup
# ─────────────────────────────────────────────────────────────────────────────
class CwpBackup(CpanelBackup):
    """Abre y analiza un .tar de cwp_export.sh. Context manager: limpia el tmp."""

    def __init__(self, tar_path: str, config_only: bool = False, progress_cb=None):
        super().__init__(tar_path)
        self.progress_cb = progress_cb
        self._mail_moved = 0

    def _is_cpanel_root(self, d: str) -> bool:
        return os.path.isfile(os.path.join(d, "cwp", "user.tsv"))

    def extract(self):
        if self._extracted:
            return
        safe_extract_tar(self.tar_path, self.tmpdir, progress_cb=self.progress_cb)
        self._extracted = True
        self.root = self._find_root()
        if not self.root:
            raise CwpImportError(
                "El archivo no es un export de CWP de SVQPanel (falta cwp/user.tsv). "
                "Genéralo con scripts/cwp_export.sh o usa el origen SSH.")
        mail = os.path.join(self.root, "homedir", "mail")
        if os.path.isdir(mail):
            for dom in os.listdir(mail):
                ddir = os.path.join(mail, dom)
                for acc in (os.listdir(ddir) if os.path.isdir(ddir) else []):
                    if os.path.isdir(os.path.join(ddir, acc)):
                        self._mail_moved += normalize_maildir(os.path.join(ddir, acc))

    def _tsv(self, name: str) -> List[Dict[str, str]]:
        return parse_tsv(self._read("cwp", name))

    # ── cuenta ────────────────────────────────────────────────────────────────
    def _user_row(self) -> Dict[str, str]:
        rows = self._tsv("user.tsv")
        return rows[0] if rows else {}

    def guess_username(self) -> str:
        return (self._user_row().get("username") or "").lower()

    def _home(self) -> str:
        return f"/home/{self.guess_username()}"

    def all_domains(self) -> List[str]:
        main = (self._user_row().get("domain") or "").lower()
        out = [main] if main else []
        out += [r["domain"].lower() for r in self._tsv("domains.tsv") if r.get("domain")]
        out += [f"{r['subdomain']}.{r['domain']}".lower() for r in self._tsv("subdomains.tsv")
                if r.get("subdomain") and r.get("domain")]
        return list(dict.fromkeys(out))

    def _docroots(self) -> Dict[str, str]:
        """{dominio: docroot absoluto en el CWP}. El del vhost manda sobre la BD."""
        out = {}
        main = (self._user_row().get("domain") or "").lower()
        if main:
            out[main] = f"{self._home()}/public_html"
        for r in self._tsv("domains.tsv"):
            if r.get("path"):
                out[r["domain"].lower()] = r["path"]
        for r in self._tsv("subdomains.tsv"):
            if r.get("path"):
                out[f"{r['subdomain']}.{r['domain']}".lower()] = r["path"]
        for r in self._tsv("php.tsv"):
            if r.get("docroot"):
                out[r["domain"].lower()] = r["docroot"]
        return {d: p.rstrip("/") for d, p in out.items()}

    # ── web ───────────────────────────────────────────────────────────────────
    def analyze_web(self) -> List[Dict]:
        php = {r["domain"].lower(): _php_from_cwp(r.get("php")) for r in self._tsv("php.tsv")}
        ssl = {r["domain"].lower() for r in self._tsv("ssl.tsv")}
        home = self._home() + "/"
        main = (self._user_row().get("domain") or "").lower()
        docroots = self._docroots()
        # Webs anidadas/compartidas: en CWP es habitual que subdominios sirvan
        # una carpeta DENTRO del public_html del principal (o la misma carpeta
        # varios a la vez). Copiarlas por separado duplica GB y rompe el CMS
        # multi-sitio (cada copia evolucionaría por su lado). Se resuelve: la web
        # "raíz" (docroot más corto; a igualdad, el principal) se importa con sus
        # datos y las demás apuntan a su carpeta (custom_docroot en import_web).
        order = sorted(docroots, key=lambda d: (len(docroots[d]), d != main, d))
        roots: List[str] = []
        nested_in: Dict[str, Dict[str, str]] = {}
        for d in order:
            dr = docroots[d]
            parent = next((r for r in roots
                           if dr == docroots[r] or dr.startswith(docroots[r] + "/")), None)
            if parent:
                nested_in[d] = {"domain": parent, "rel": dr[len(docroots[parent]):].strip("/")}
            else:
                roots.append(d)
        # Orden de importación: primero las raíces (en el orden original:
        # principal, dominios, subdominios) y después las anidadas, para que la
        # carpeta a la que apuntan ya exista cuando se crean.
        out = []
        for domain in sorted(docroots, key=lambda d: d in nested_in):
            docroot = docroots[domain]
            data_dir = None
            if docroot.startswith(home):
                cand = os.path.join(self.root, "homedir", docroot[len(home):])
                if os.path.isdir(cand):
                    data_dir = cand
            nest = nested_in.get(domain)
            out.append({
                "domain": domain,
                "aliases": [],
                "php_version": php.get(domain),
                "ssl": domain in ssl,
                "letsencrypt": False,
                "custom_docroot": None,
                "redirect": None,
                # Anidada: sin copia propia (sus archivos llegan con la raíz).
                "has_data": bool(data_dir) and not nest,
                "_data_dir": None if nest else data_dir,
                "_nested_in": nest,
                "_nested_data_dir": data_dir if nest else None,
                "shared_with": nest["domain"] if nest else None,
                "_old_docroot": docroot,
                "ip": self._user_row().get("ip_address") or None,
            })
        return out

    # ── correo ────────────────────────────────────────────────────────────────
    def analyze_mail(self) -> List[Dict]:
        mailboxes = self._tsv("mailbox.tsv")
        domains = {r["domain"].lower() for r in self._tsv("maildomains.tsv") if r.get("domain")}
        domains |= {r["domain"].lower() for r in mailboxes if r.get("domain")}
        by_addr = {r["username"].lower(): r for r in mailboxes if r.get("username")}
        aliases = [r for r in self._tsv("alias.tsv") if r.get("active", "1") != "0"]
        out = []
        for domain in sorted(domains):
            accounts, pure = [], []
            fwd_of: Dict[str, tuple] = {}
            for a in aliases:
                addr = (a.get("address") or "").lower()
                if (a.get("domain") or "").lower() != domain or "@" not in addr:
                    continue
                local = addr.split("@", 1)[0] or "@"          # '@dom' = catch-all
                dests = [d.strip() for d in (a.get("goto") or "").split(",") if d.strip()]
                others = [d for d in dests if d.lower() != addr]
                if not others:
                    continue                                   # alias a sí mismo
                if addr in by_addr:
                    fwd_of[addr] = (others, addr not in [d.lower() for d in dests])
                else:
                    pure.append({"source": local, "destinations": others})
            for r in mailboxes:
                if (r.get("domain") or "").lower() != domain:
                    continue
                addr = r["username"].lower()
                fwd, only = fwd_of.get(addr, ([], False))
                try:
                    quota_mb = str(int(int(r.get("quota") or 0) / (1024 * 1024)))
                except ValueError:
                    quota_mb = "0"
                accounts.append({
                    "account": r.get("local_part") or addr.split("@", 1)[0],
                    "md5": cwp_hash(r.get("password")),
                    "quota": quota_mb,
                    "fwd": ",".join(fwd) if fwd else None,
                    "fwd_only": bool(fwd) and only,
                    "suspended": r.get("active", "1") == "0",
                })
            acc_dir = os.path.join(self.root, "homedir", "mail", domain)
            out.append({
                "domain": domain,
                "accounts": accounts,
                "aliases": pure,
                "_accounts_dir": acc_dir if os.path.isdir(acc_dir) else None,
                "accounts_tar": None,
            })
        return out

    # ── cron ──────────────────────────────────────────────────────────────────
    def analyze_cron(self, web: Optional[List[Dict]] = None) -> List[Dict]:
        user = self.guess_username()
        text = self._read("cron", user) if user else ""
        home = self._home() + "/"
        # Las webs anidadas no tienen carpeta propia: sus archivos quedan dentro
        # de la raíz (…/web/PRINCIPAL/public_html/sub), así que solo las raíces.
        nested = {w["domain"] for w in (web if web is not None else self.analyze_web())
                  if w.get("_nested_in")}
        docroots = sorted(((p[len(home):], d) for d, p in self._docroots().items()
                           if p.startswith(home) and d not in nested),
                          key=lambda x: -len(x[0]))
        jobs = parse_cpanel_crontab(text, [])   # sin docroots: las rutas, abajo
        for job in jobs:
            job["cmd"] = _cwp_cron_cmd(job["cmd"], docroots)
            job["origin"] = "CWP"
        return jobs

    # ── avisos del análisis ───────────────────────────────────────────────────
    def warnings(self, manifest: Dict) -> List[str]:
        from scripts.hestia_import import resolve_php_version
        out = []
        old_php = {}
        for w in manifest["web"]:
            v = w.get("php_version")
            if v:
                try:
                    nv = resolve_php_version(v)
                except Exception:
                    nv = v
                if nv != v:
                    old_php.setdefault(f"{v} → {nv}", []).append(w["domain"])
        for change, doms in old_php.items():
            out.append(f"PHP {change} (no está en este servidor) en {len(doms)} web(s): "
                       + ", ".join(doms[:8]) + (" …" if len(doms) > 8 else "")
                       + ". Comprueba que funcionan antes de cambiar el DNS.")
        shared: Dict[str, List[str]] = {}
        for w in manifest["web"]:
            if w.get("_nested_in"):
                n = w["_nested_in"]
                shared.setdefault(n["domain"], []).append(
                    w["domain"] + (f" (/{n['rel']})" if n.get("rel") else " (misma carpeta)"))
        for parent, doms in shared.items():
            out.append(f"{len(doms)} web(s) sirven carpetas de {parent} y la seguirán "
                       f"compartiendo (no se copian aparte): " + ", ".join(doms)
                       + ". Si no importas " + parent + ", se copian por separado.")
        no_pw = [f"{a['account']}@{m['domain']}" for m in manifest["mail"]
                 for a in m["accounts"] if not a["md5"]]
        if no_pw:
            out.append(f"{len(no_pw)} buzón(es) sin contraseña en CWP: se les genera una "
                       f"nueva (sale en el informe): {', '.join(no_pw)}")
        # Desde 1 MB: lo más pequeño son restos de configuración, no datos.
        extra = [r for r in self._tsv("extra_dirs.tsv")
                 if r.get("name") and int(r.get("kb") or 0) >= 1024]
        if extra:
            out.append("Hay carpetas en el home de CWP fuera de las webs que NO se migran: "
                       + ", ".join(f"{r['name']} ({int(r.get('kb') or 0) // 1024} MB)" for r in extra))
        alias_domains = [r for r in self._tsv("alias_domain.tsv") if r.get("alias_domain")]
        if alias_domains:
            out.append("Dominios de correo alias que hay que recrear a mano: "
                       + ", ".join(f"{r['alias_domain']} → {r['target_domain']}" for r in alias_domains))
        users_per_db: Dict[str, set] = {}
        for m in re.finditer(r"ON\s+`([^`]+)`\.\*\s+TO\s+'([^']+)'", self._read("mysql.sql")):
            users_per_db.setdefault(m.group(1), set()).add(m.group(2))
        multi = {db: us for db, us in users_per_db.items() if len(us) > 1}
        if multi:
            out.append("BD con varios usuarios MySQL (solo se migra el primero): "
                       + "; ".join(f"{db}: {', '.join(sorted(us))}" for db, us in multi.items()))
        return out

    def _size_mb(self) -> int:
        return sum(int(r.get("kb") or 0) for r in self._tsv("sizes.tsv")) // 1024

    def analyze(self) -> Dict:
        row = self._user_row()
        pkg = (self._tsv("package.tsv") or [{}])[0]
        web = self.analyze_web()
        manifest = {
            "system": "cwp",
            "username": self.guess_username(),
            "user": {
                "contact": row.get("email", ""),
                "fname": "",
                "lname": "",
                "package": pkg.get("package_name") or pkg.get("name") or "",
            },
            "web": web,
            "db": self.analyze_db(),
            "mail": self.analyze_mail(),
            "dns": self.analyze_dns(),
            "cron": self.analyze_cron(web),
            "size_mb": self._size_mb(),
        }
        manifest["warnings"] = self.warnings(manifest)
        return manifest

    # ── Después de importar (lo llama run_import con el backup aún abierto) ──
    def post_import(self, manifest: Dict, owner, db, report, scope: List[str]) -> None:
        if "web" in scope:
            self._rewrite_web_paths(manifest, owner, db, report)
        if "mail" in scope:
            if self._mail_moved:
                report.ok("mail-junk", "carpetas spam",
                          f"{self._mail_moved} correo(s) de .spam/.Spam fundidos en Junk")
            self._install_dkim(manifest, db, report)
            self._install_sieve(manifest, report)
            self._import_vacation(owner, db, report)
            for m in manifest["mail"]:
                for a in m["accounts"]:
                    _subscribe_all(f"{a['account']}@{m['domain']}")

    def _rewrite_web_paths(self, manifest, owner, db, report):
        from api.models.models_domain import Domain
        old_user = self.guess_username()
        new_paths = {}
        for w in manifest["web"]:
            d = db.query(Domain).filter(Domain.domain_name == w["domain"]).first()
            if d and w.get("_old_docroot"):
                new_paths[w["domain"]] = (w["_old_docroot"], d.custom_docroot or d.public_html)
        mapping = list(new_paths.values())
        if old_user and old_user != owner.username:
            mapping.append((f"/home/{old_user}", f"/home/{owner.username}"))
        for domain, (_old, new_root) in new_paths.items():
            try:
                changed = rewrite_paths(new_root, mapping)
                if changed:
                    report.ok("web-paths", domain,
                              f"rutas de CWP → SVQPanel en {len(changed)} fichero(s): "
                              + ", ".join(changed[:5]) + (" …" if len(changed) > 5 else ""))
            except Exception as e:
                report.fail("web-paths", domain, e)

    def _install_dkim(self, manifest, db, report):
        from api.models.models_mail import MailDomain
        from scripts.dkim_manager import DkimManager
        kdir = os.path.join(self.root, "cwp", "dkim")
        if not os.path.isdir(kdir):
            return
        imported = {m["domain"] for m in manifest["mail"]}
        dm = None
        for fn in sorted(os.listdir(kdir)):
            m = re.fullmatch(r"(.+)\.([A-Za-z0-9_-]+)\.key", fn)
            if not m or m.group(1) not in imported:
                continue
            domain, selector = m.group(1), m.group(2)
            try:
                dm = dm or DkimManager()
                path = dm._key_path(domain, selector)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(os.path.join(kdir, fn)) as f:
                    pem = f.read()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(pem)
                dm._chown_rspamd(path)
                dm._update_selector_map(domain, selector)
                info = dm.get_key_info(domain, selector)
                md = db.query(MailDomain).filter(MailDomain.domain_name == domain).first()
                if md and info:
                    md.dkim_enabled = True
                    md.dkim_selector = selector
                    md.dkim_public_key = info["public_key_b64"]
                    db.commit()
                report.ok("dkim", domain, f"clave de CWP conservada (selector «{selector}»): "
                                          "el TXT publicado sigue valiendo")
            except Exception as e:
                db.rollback()
                report.fail("dkim", domain, e)
        if dm:
            try:
                dm._reload_rspamd()
            except Exception:
                pass

    def _install_sieve(self, manifest, report):
        from scripts.mail_manager import MailManager
        sdir = os.path.join(self.root, "cwp", "sieve")
        if not os.path.isdir(sdir):
            return
        imported = {f"{a['account']}@{m['domain']}".lower()
                    for m in manifest["mail"] for a in m["accounts"]}
        mgr = MailManager()
        for email in sorted(os.listdir(sdir)):
            src = os.path.join(sdir, email)
            if email.lower() not in imported or not os.path.isdir(src):
                continue
            local, domain = email.split("@", 1)
            try:
                active = ""
                if os.path.isfile(os.path.join(src, "active")):
                    with open(os.path.join(src, "active")) as f:
                        active = f.read().strip()
                base = mgr._ensure_sieve_user_dir(domain, local)
                scripts_dir = os.path.join(base, "scripts")
                names = []
                for fn in sorted(os.listdir(src)):
                    if fn == "active" or not fn.endswith(".sieve"):
                        continue
                    with open(os.path.join(src, fn), encoding="utf-8", errors="replace") as f:
                        text = adapt_cwp_sieve(f.read())
                    dst = os.path.join(scripts_dir, fn)
                    with open(dst, "w", encoding="utf-8") as f:
                        f.write(text)
                    os.chown(dst, mgr.VMAIL_UID, mgr.VMAIL_GID)
                    names.append(fn)
                if active in names:
                    link = os.path.join(base, "active.sieve")
                    if os.path.lexists(link):
                        os.remove(link)
                    os.symlink(os.path.join("scripts", active), link)
                    os.lchown(link, mgr.VMAIL_UID, mgr.VMAIL_GID)
                if names:
                    report.ok("mail-sieve", email, f"{len(names)} filtro(s)"
                              + (f", activo «{active}»" if active in names else ""))
            except Exception as e:
                report.fail("mail-sieve", email, e)

    def _import_vacation(self, owner, db, report):
        from api.models.models_mail import MailDomain, Mailbox
        from scripts.mail_manager import MailManager
        rows = self._tsv("vacation.tsv")
        if not rows:
            return
        mgr = MailManager()
        for r in rows:
            email = (r.get("email") or "").lower()
            if "@" not in email:
                continue
            local, domain = email.split("@", 1)
            mb = (db.query(Mailbox).join(MailDomain, Mailbox.mail_domain_id == MailDomain.id)
                    .filter(MailDomain.domain_name == domain, Mailbox.username == local).first())
            if not mb:
                continue
            active = (r.get("active") or "0") not in ("0", "")
            subject = r.get("subject") or ""
            body = r.get("body") or ""
            try:
                mb.autoreply_subject = subject[:255]
                mb.autoreply_body = body
                mb.autoreply_enabled = active
                if active:
                    mgr.set_autoreply(owner.username, domain, local, subject, body)
                db.commit()
                report.ok("mail-autoreply", email, "activa" if active else
                          "guardada desactivada (como estaba en CWP)")
            except Exception as e:
                db.rollback()
                report.fail("mail-autoreply", email, e)


def _subscribe_all(email: str) -> None:
    """Suscribe TODAS las carpetas del buzón (las de CWP venían con 'INBOX.' y
    su lista de suscripciones se descarta en normalize_maildir)."""
    try:
        r = subprocess.run(["doveadm", "mailbox", "list", "-u", email],
                           capture_output=True, text=True, timeout=60)
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        if names:
            subprocess.run(["doveadm", "mailbox", "subscribe", "-u", email] + names,
                           capture_output=True, timeout=60)
    except Exception as e:
        logger.warning(f"[cwp] no se pudieron suscribir las carpetas de {email}: {e}")
