"""
Migrador SVQPanel → SVQPanel · FASE 3: copiar los DATOS del origen al destino
(después de que la fase 2 haya recreado la cuenta). Se ejecuta en el destino.

  - /home/USUARIO entero (webs, correo, ~/.ssh, ~/imports…) con rsync por SSH:
      · sin --numeric-ids: los UID cambian entre servidores y rsync, como root
        en los dos lados, traduce por NOMBRE (usuario, vmail, www-data).
      · -aHAX: enlaces duros, ACL (las de las subcuentas SFTP) y xattr.
      · --delete: el destino queda IGUAL que el origen, así que repetirlo es la
        «resincronización» antes del corte (solo copia lo que cambió).
      · fuera: logs/ y tmp/ de cada web (son del servidor que los genera).
  - Cada BD: mariadb-dump en el origen → mariadb en el destino, en streaming
    por SSH (sin ficheros intermedios: ni el disco ni /tmp se llenan).
  - Después: permisos que el panel exige (raíz de la web y logs con grupo
    www-data, tmp de PHP de www-data 0700) y la project quota del correo.
  - Verificación: ficheros y bytes por web y por correo, y tablas/filas por BD,
    comparando origen y destino.

Todo lo que ejecuta comandos pasa por un `runner` inyectable (los tests lo
sustituyen); el JSON del export no se escribe nunca a disco.
"""

import logging
import os
import re
import shlex
import subprocess
import tempfile
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

RSYNC_EXCLUDES = ["/web/*/logs/", "/web/*/tmp/"]
DUMP_OPTS = ("--single-transaction --quick --routines --triggers --events "
             "--hex-blob --default-character-set=utf8mb4")


class CopyError(RuntimeError):
    pass


class Remote:
    """Comandos contra el origen por SSH (contraseña vía sshpass -e o clave)."""

    def __init__(self, cfg: Dict):
        self.host = (cfg.get("host") or "").strip()
        self.user = (cfg.get("user") or "root").strip()
        self.port = str(cfg.get("port") or 22)
        self.password = cfg.get("password") or None
        self.keyfile = None
        if not self.host:
            raise CopyError("Falta el servidor de origen.")
        if cfg.get("key"):
            fd, self.keyfile = tempfile.mkstemp(prefix="svq_sshkey_")
            with os.fdopen(fd, "w") as f:
                f.write(cfg["key"])
            os.chmod(self.keyfile, 0o600)

    def close(self):
        if self.keyfile and os.path.exists(self.keyfile):
            os.remove(self.keyfile)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"

    def ssh_opts(self, compress: bool = False) -> List[str]:
        o = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-p", self.port]
        if compress:
            o.insert(0, "-C")
        if self.keyfile:
            o += ["-i", self.keyfile]
        return o

    def env(self) -> Dict:
        e = dict(os.environ)
        if self.password:
            e["SSHPASS"] = self.password
        return e

    def _wrap(self, argv: List[str]) -> List[str]:
        return (["sshpass", "-e"] + argv) if self.password and not self.keyfile else argv

    def ssh(self, remote_cmd: str, compress: bool = False) -> List[str]:
        return self._wrap(["ssh"] + self.ssh_opts(compress) + [self.target, remote_cmd])

    def rsync_home(self, username: str, dry_run: bool = False) -> List[str]:
        ssh_cmd = " ".join(shlex.quote(x) for x in ["ssh"] + self.ssh_opts())
        argv = ["rsync", "-aHAX", "--delete", "--stats", "--partial", "-e", ssh_cmd]
        for ex in RSYNC_EXCLUDES:
            argv += ["--exclude", ex]
        if dry_run:
            argv.append("--dry-run")
        argv += [f"{self.target}:/home/{username}/", f"/home/{username}/"]
        return self._wrap(argv)


def rsync_mail_catchup_argv(remote: "Remote", username: str) -> List[str]:
    """Correo que siga llegando al ORIGEN tras el corte (DNS en caché). SIN
    --delete y con --ignore-existing: el destino ya es el bueno y tiene correo
    que el origen no; solo se AÑADE lo que falte, nunca se borra ni pisa nada."""
    ssh_cmd = " ".join(shlex.quote(x) for x in ["ssh"] + remote.ssh_opts())
    return remote._wrap(["rsync", "-aHAX", "--ignore-existing", "--stats", "-e", ssh_cmd,
                         f"{remote.target}:/home/{username}/mail/", f"/home/{username}/mail/"])


def copy_mail_catchup(remote: "Remote", username: str, runner: Callable = subprocess.run) -> Dict:
    _check_user(username)
    r = runner(rsync_mail_catchup_argv(remote, username), capture_output=True, text=True,
               env=remote.env(), timeout=6 * 3600)
    if r.returncode not in (0, 24):
        raise CopyError(f"rsync del correo falló ({r.returncode}): {(r.stderr or '').strip()[-400:]}")
    m = re.search(r"Number of regular files transferred: ([\d,.]+)", r.stdout or "")
    return {"files": int(re.sub(r"[,.]", "", m.group(1))) if m else None}


def _check_user(username: str):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username or ""):
        raise CopyError(f"Usuario no válido: {username!r}")


def _check_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_$.-]{1,64}", name or ""):
        raise CopyError(f"Nombre de BD no válido: {name!r}")
    return name


# ─────────────────────────────────────────────────────────────────────────────
# Web + correo (rsync)
# ─────────────────────────────────────────────────────────────────────────────
def copy_home(remote: Remote, username: str, runner: Callable = subprocess.run,
              timeout: int = 24 * 3600) -> Dict:
    """rsync de /home/USUARIO. Devuelve las estadísticas de rsync."""
    _check_user(username)
    r = runner(remote.rsync_home(username), capture_output=True, text=True,
               env=remote.env(), timeout=timeout)
    # 24 = «algunos ficheros desaparecieron mientras se copiaban» (correo que
    # entra/sale durante la copia): normal en un servidor vivo, no es un fallo.
    if r.returncode not in (0, 24):
        raise CopyError(f"rsync falló ({r.returncode}): {(r.stderr or '').strip()[-400:]}")
    stats = {}
    for key, pat in (("files", r"Number of regular files transferred: ([\d,.]+)"),
                     ("bytes", r"Total transferred file size: ([\d,.]+)")):
        m = re.search(pat, r.stdout or "")
        if m:
            stats[key] = int(re.sub(r"[,.]", "", m.group(1)))
    stats["vanished"] = r.returncode == 24
    return stats


def fix_after_copy(username: str, domains: List[str], has_mail: bool,
                   runner: Callable = subprocess.run) -> List[str]:
    """Lo que el panel exige y rsync puede haber dejado con lo del origen.
    Mismo estado que un dominio recién creado (ver domain_manager/import_web)."""
    _check_user(username)
    done = []
    home = f"/home/{username}"
    for d in domains:
        root = f"{home}/web/{d}"
        # Sin check: si una carpeta no existe, el comando falla sin más.
        for cmd in (["chgrp", "www-data", root], ["chmod", "750", root],
                    ["chgrp", "www-data", f"{root}/logs"], ["chmod", "750", f"{root}/logs"],
                    ["chown", "www-data:www-data", f"{root}/tmp"], ["chmod", "700", f"{root}/tmp"]):
            runner(cmd, capture_output=True)
        done.append(d)
    if has_mail:
        try:
            import pwd
            uid = str(pwd.getpwnam(username).pw_uid)
        except (KeyError, ImportError):
            uid = None
        if uid:
            # Project quota del correo: lo copiado cuenta en el disco del cliente
            runner(["chattr", "-R", "-p", uid, "+P", f"{home}/mail"], capture_output=True)
            done.append("mail-quota")
    return done


# ─────────────────────────────────────────────────────────────────────────────
# Bases de datos (streaming)
# ─────────────────────────────────────────────────────────────────────────────
def _local_mariadb() -> str:
    from api.routes.databases import _mariadb_binary
    return _mariadb_binary()


def copy_database(remote: Remote, name: str, charset: str = "utf8mb4",
                  collation: str = "utf8mb4_unicode_ci", popen: Callable = subprocess.Popen,
                  local_sql: Optional[Callable] = None, mariadb_bin: Optional[str] = None,
                  timeout: int = 12 * 3600) -> None:
    """Vacía la BD del destino y la rellena con el volcado del origen, sin
    ficheros intermedios. Recrearla hace que repetir (resincronizar) deje la BD
    idéntica al origen, también si allí se borró alguna tabla."""
    _check_ident(name)
    _check_ident(charset)
    _check_ident(collation)
    if local_sql is None:
        from api.routes.databases import _run_mariadb as local_sql
    local_sql(f"DROP DATABASE IF EXISTS `{name}`;")
    local_sql(f"CREATE DATABASE `{name}` CHARACTER SET {charset} COLLATE {collation};")
    dump = ('d=$(command -v mariadb-dump || command -v mysqldump) && '
            f'"$d" {DUMP_OPTS} {shlex.quote(name)}')
    with tempfile.TemporaryFile() as e1, tempfile.TemporaryFile() as e2:
        p1 = popen(remote.ssh(dump, compress=True), stdout=subprocess.PIPE, stderr=e1,
                   env=remote.env())
        p2 = popen([mariadb_bin or _local_mariadb(), "--default-character-set=utf8mb4", name],
                   stdin=p1.stdout, stderr=e2)
        if p1.stdout:
            p1.stdout.close()           # que el dump reciba SIGPIPE si el import muere
        rc2 = p2.wait(timeout=timeout)
        rc1 = p1.wait(timeout=60)
        if rc1 != 0 or rc2 != 0:
            e1.seek(0)
            e2.seek(0)
            err = (e2.read() or e1.read() or b"").decode("utf-8", "replace").strip()
            side = "importar en el destino" if rc2 != 0 else "volcar en el origen"
            raise CopyError(f"No se pudo {side} la BD {name}: {err[-400:]}")


# ─────────────────────────────────────────────────────────────────────────────
# Verificación
# ─────────────────────────────────────────────────────────────────────────────
def _count_script(paths: List[str]) -> str:
    """Por cada ruta: 'ruta<TAB>ficheros<TAB>bytes' (0 0 si no existe)."""
    parts = []
    for p in paths:
        q = shlex.quote(p)
        parts.append(f'if [ -d {q} ]; then printf "%s\\t%s\\t%s\\n" {q} '
                     f'"$(find {q} -type f | wc -l)" "$(du -sb {q} | cut -f1)"; '
                     f'else printf "%s\\t0\\t0\\n" {q}; fi')
    return "; ".join(parts)


def _parse_counts(text: str) -> Dict[str, tuple]:
    out = {}
    for line in (text or "").splitlines():
        p = line.split("\t")
        if len(p) == 3 and p[1].isdigit() and p[2].isdigit():
            out[p[0]] = (int(p[1]), int(p[2]))
    return out


def _rows_sql(db: str, tables: List[str]) -> str:
    return " UNION ALL ".join(
        f"SELECT '{t}', COUNT(*) FROM `{db}`.`{t}`" for t in tables) + ";"


def verify(remote: Remote, username: str, domains: List[str], mail_domains: List[str],
           dbs: List[str], runner: Callable = subprocess.run,
           local_rows: Optional[Callable] = None) -> Dict:
    """Compara origen y destino. Diferencia pequeña en el correo es normal en
    un servidor vivo (entra correo mientras se copia); la resincronización la
    recoge. Devuelve {"web": [...], "mail": [...], "db": [...], "ok": bool}."""
    _check_user(username)
    home = f"/home/{username}"
    web_paths = [f"{home}/web/{d}/public_html" for d in domains]
    mail_paths = [f"{home}/mail/{d}" for d in mail_domains]
    script = _count_script(web_paths + mail_paths)
    out: Dict = {"web": [], "mail": [], "db": [], "ok": True}
    if web_paths or mail_paths:
        rs = runner(remote.ssh(script), capture_output=True, text=True, env=remote.env(), timeout=3600)
        ls = runner(["bash", "-c", script], capture_output=True, text=True, timeout=3600)
        src, dst = _parse_counts(rs.stdout), _parse_counts(ls.stdout)
        for kind, paths in (("web", web_paths), ("mail", mail_paths)):
            for p in paths:
                s, d = src.get(p, (0, 0)), dst.get(p, (0, 0))
                same = s[0] == d[0]
                out[kind].append({"path": p, "src_files": s[0], "dst_files": d[0],
                                  "src_bytes": s[1], "dst_bytes": d[1], "same": same})
                if kind == "web" and not same:
                    out["ok"] = False
    if local_rows is None:
        from scripts.svq_export import _sql as local_rows     # filas de MariaDB local
    for db in dbs:
        _check_ident(db)
        q = f"SELECT table_name FROM information_schema.tables WHERE table_schema='{db}' " \
            "AND table_type='BASE TABLE' ORDER BY 1"
        rs = runner(remote.ssh(f"mariadb -N -B -e {shlex.quote(q)}"), capture_output=True,
                    text=True, env=remote.env(), timeout=600)
        tables = [t for t in (rs.stdout or "").split() if re.fullmatch(r"[A-Za-z0-9_$-]+", t)]
        item = {"db": db, "tables": len(tables), "diff": []}
        if tables:
            sql = _rows_sql(db, tables)
            rs = runner(remote.ssh(f"mariadb -N -B -e {shlex.quote(sql)}"), capture_output=True,
                        text=True, env=remote.env(), timeout=3600)
            src = dict(l.split("\t") for l in (rs.stdout or "").splitlines() if "\t" in l)
            try:
                dst = {r[0]: r[1] for r in local_rows(sql)}
            except Exception as e:
                dst = {}
                item["error"] = str(e)
            for t in tables:
                if src.get(t) != dst.get(t):
                    item["diff"].append({"table": t, "src": src.get(t), "dst": dst.get(t)})
        item["same"] = not item["diff"] and "error" not in item
        out["ok"] = out["ok"] and item["same"]
        out["db"].append(item)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador de la copia (sirve igual para la primera copia y para resincronizar)
# ─────────────────────────────────────────────────────────────────────────────
def run_copy(cfg: Dict, data: Dict, report, progress=None,
             runner: Callable = subprocess.run, popen: Callable = subprocess.Popen,
             local_sql: Optional[Callable] = None, local_rows: Optional[Callable] = None,
             mariadb_bin: Optional[str] = None, do_verify: bool = True) -> Dict:
    from scripts.hestia_import import NullProgress
    progress = progress or NullProgress()
    username = data["username"]
    t = data.get("tables") or {}
    domains = [d["domain_name"] for d in t.get("domains", []) if not d.get("mail_dns_only")]
    mail_domains = [m["domain_name"] for m in t.get("mail_domains", [])]
    dbs = t.get("client_databases", [])
    result: Dict = {}
    with Remote(cfg) as remote:
        progress.set_phase(f"Copiando /home/{username} (webs y correo)…")
        try:
            result["home"] = copy_home(remote, username, runner=runner)
            report.ok("copy-home", f"/home/{username}",
                      f"{result['home'].get('files', '?')} ficheros nuevos/cambiados")
        except CopyError as e:
            report.fail("copy-home", f"/home/{username}", e)
        fix_after_copy(username, domains, bool(mail_domains), runner=runner)
        for c in dbs:
            name = c["db_name"]
            progress.set_phase(f"Copiando la base de datos {name}…")
            try:
                copy_database(remote, name, c.get("db_charset") or "utf8mb4",
                              c.get("db_collation") or "utf8mb4_unicode_ci",
                              popen=popen, local_sql=local_sql, mariadb_bin=mariadb_bin)
                report.ok("copy-db", name, "volcado completo")
            except Exception as e:
                report.fail("copy-db", name, e)
        if do_verify:
            progress.set_phase("Comprobando que origen y destino coinciden…")
            try:
                result["verify"] = verify(remote, username, domains, mail_domains,
                                          [c["db_name"] for c in dbs], runner=runner,
                                          local_rows=local_rows)
            except Exception as e:
                report.fail("verify", username, e)
    return result
