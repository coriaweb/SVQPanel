"""
Visor de logs del servidor (Fase 22).

Seguridad ante todo: NO se permite leer una ruta arbitraria. El cliente elige
un log por su CLAVE de un catálogo curado (LOG_CATALOG); el panel resuelve la
ruta real. Para logs por dominio, la ruta se construye desde el dominio validado
(la ruta la pasa la capa de rutas tras comprobar propiedad), nunca desde input
libre del usuario.

Lectura eficiente: `tail -n N` + filtro opcional con `grep` server-side, para no
mandar megas al navegador. Soporta journalctl para servicios sin fichero propio.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}

MAX_LINES = 2000     # tope de líneas que se devuelven
DEFAULT_LINES = 300


# Catálogo curado: clave → {label, group, path|journal}. Solo rutas conocidas.
# 'journal': nombre de unit para journalctl (logs sin fichero propio).
LOG_CATALOG = {
    # ── Web ──
    "nginx_error":   {"label": "Nginx — errores",        "group": "Web",     "path": "/var/log/nginx/error.log"},
    "nginx_access":  {"label": "Nginx — accesos",        "group": "Web",     "path": "/var/log/nginx/access.log"},
    # ── PHP ──
    "php_fpm":       {"label": "PHP-FPM (todas las versiones)", "group": "Web", "glob": "/var/log/php*-fpm.log"},
    # ── Correo ──
    "mail":          {"label": "Correo — mail.log",      "group": "Correo",  "path": "/var/log/mail.log"},
    "dovecot":       {"label": "Dovecot",                "group": "Correo",  "journal": "dovecot"},
    "rspamd":        {"label": "Rspamd (antispam)",      "group": "Correo",  "path": "/var/log/rspamd/rspamd.log"},
    # ── Seguridad ──
    "fail2ban":      {"label": "Fail2ban",               "group": "Seguridad", "path": "/var/log/fail2ban.log"},
    "auth":          {"label": "Autenticación / SSH",    "group": "Seguridad", "path": "/var/log/auth.log"},
    "crowdsec":      {"label": "CrowdSec",               "group": "Seguridad", "journal": "crowdsec"},
    # ── DNS ──
    "bind":          {"label": "BIND9 / DNS",            "group": "DNS",     "journal": "named"},
    # ── Sistema ──
    "syslog":        {"label": "Syslog (sistema)",       "group": "Sistema", "path": "/var/log/syslog"},
    "kernel":        {"label": "Kernel",                 "group": "Sistema", "path": "/var/log/kern.log"},
    "apt":           {"label": "Actualizaciones APT",    "group": "Sistema", "path": "/var/log/apt/history.log"},
    "svqpanel":      {"label": "Panel SVQPanel",         "group": "Sistema", "journal": "svqpanel"},
}


def catalog() -> list:
    """Lista de logs disponibles (los que realmente existen en este servidor)."""
    out = []
    for key, info in LOG_CATALOG.items():
        exists = True
        if "path" in info:
            exists = os.path.isfile(info["path"])
        elif "glob" in info:
            import glob
            exists = bool(glob.glob(info["glob"]))
        elif "journal" in info:
            # Asumimos disponible si journalctl existe (no comprobamos cada unit)
            exists = os.path.exists("/usr/bin/journalctl") or os.path.exists("/bin/journalctl")
        if exists:
            out.append({"key": key, "label": info["label"], "group": info["group"]})
    return out


def _read_file(path: str, lines: int, search: str | None, regex: bool) -> dict:
    if not os.path.isfile(path):
        return {"available": False, "error": "el archivo no existe", "lines": []}
    try:
        if search:
            # tail grande → grep → recortar. -i = case-insensitive; -F = literal.
            tail = subprocess.Popen(["tail", "-n", "20000", path],
                                    stdout=subprocess.PIPE, env=_ENV)
            grep_cmd = ["grep", "-i"]
            if not regex:
                grep_cmd.append("-F")
            grep_cmd.append(search)
            grep = subprocess.run(grep_cmd, stdin=tail.stdout, capture_output=True,
                                  text=True, timeout=20, env=_ENV)
            tail.stdout.close()
            content = grep.stdout
        else:
            r = subprocess.run(["tail", "-n", str(lines), path],
                               capture_output=True, text=True, timeout=15, env=_ENV)
            content = r.stdout
    except subprocess.SubprocessError as e:
        return {"available": False, "error": str(e), "lines": []}

    rows = content.splitlines()
    if len(rows) > lines:
        rows = rows[-lines:]
    return {"available": True, "lines": rows, "path": path, "total": len(rows)}


def _read_journal(unit: str, lines: int, search: str | None) -> dict:
    cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=_ENV)
        if r.returncode != 0:
            return {"available": False, "error": r.stderr.strip()[:200], "lines": []}
        rows = r.stdout.splitlines()
    except subprocess.SubprocessError as e:
        return {"available": False, "error": str(e), "lines": []}

    if search:
        s = search.lower()
        rows = [ln for ln in rows if s in ln.lower()]
    if len(rows) > lines:
        rows = rows[-lines:]
    return {"available": True, "lines": rows, "source": f"journal:{unit}", "total": len(rows)}


def read_log(key: str, lines: int = DEFAULT_LINES, search: str = "", regex: bool = False) -> dict:
    """Lee un log del catálogo por su clave. Valida la clave (no rutas libres)."""
    info = LOG_CATALOG.get(key)
    if not info:
        return {"available": False, "error": f"log '{key}' no está en el catálogo", "lines": []}
    lines = max(10, min(int(lines or DEFAULT_LINES), MAX_LINES))
    search = (search or "").strip()[:200] or None

    if "journal" in info:
        return _read_journal(info["journal"], lines, search)
    if "glob" in info:
        import glob
        files = sorted(glob.glob(info["glob"]))
        if not files:
            return {"available": False, "error": "sin archivos", "lines": []}
        # Combinar todos los ficheros del glob (p.ej. php8.3/8.4/8.5-fpm.log)
        all_lines = []
        for f in files:
            res = _read_file(f, lines, search, regex)
            for ln in res.get("lines", []):
                all_lines.append(f"[{os.path.basename(f)}] {ln}")
        return {"available": True, "lines": all_lines[-lines:], "total": len(all_lines)}
    return _read_file(info["path"], lines, search, regex)


def read_path(path: str, lines: int = DEFAULT_LINES, search: str = "", regex: bool = False) -> dict:
    """
    Lee un fichero por ruta EXPLÍCITA (para logs de dominio). La capa de rutas
    debe haber validado que la ruta pertenece a un dominio del usuario; aquí solo
    comprobamos que sea un .log dentro de /home o /var/log (defensa en profundidad).
    """
    path = os.path.realpath(path)
    if not (path.startswith("/home/") or path.startswith("/var/log/")):
        return {"available": False, "error": "ruta no permitida", "lines": []}
    if not path.endswith((".log", "log")):
        return {"available": False, "error": "solo archivos de log", "lines": []}
    lines = max(10, min(int(lines or DEFAULT_LINES), MAX_LINES))
    return _read_file(path, lines, (search or "").strip()[:200] or None, regex)
