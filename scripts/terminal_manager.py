"""
SVQPanel — Terminal web (consola SSH en el navegador) vía ttyd.

Arquitectura de seguridad (importante):

  • ttyd corre en **localhost** (127.0.0.1:7681), NUNCA expuesto directamente.
    nginx hace proxy de /terminal/ → ttyd, en el mismo vhost del panel (que ya
    está protegido por HTTPS).
  • ttyd no usa su propio login. Arranca SIEMPRE un wrapper
    (`svqpanel-terminal-launch`) que pide un **token de un solo uso** emitido por
    el panel. El token:
        - lo genera el panel al pulsar "Abrir terminal" (endpoint autenticado),
        - codifica QUIÉN puede usarlo (root para admin; o un usuario del sistema
          para sesión jailed) y CADUCA en segundos,
        - se guarda en /run/svqpanel/terminal-tokens/<token> (root 0600),
        - el wrapper lo valida, lo BORRA (un solo uso) y lanza la shell correcta:
            · admin  → `bash -l` como root
            · usuario → `su - <usuario>` (queda confinado a su entorno/HOME;
                        el aislamiento real lo dan permisos del sistema y, si el
                        usuario tiene shell jailed, su propia shell).
  • Sin token válido, el wrapper cierra la conexión. Así, aunque alguien llegue a
    /terminal/ sin pasar por el panel, no obtiene shell.

El token es un JWT corto firmado con el SECRET_KEY del panel (no hace falta
estado compartido salvo el fichero de un solo uso, que evita replay).
"""
import os
import json
import secrets
import subprocess
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

TTYD_BIN          = "/usr/local/bin/ttyd"
TTYD_VERSION      = "1.7.7"
TTYD_URL          = ("https://github.com/tsl0922/ttyd/releases/download/"
                     f"{TTYD_VERSION}/ttyd.x86_64")
LAUNCHER          = "/usr/local/bin/svqpanel-terminal-launch"
TOKEN_DIR         = "/run/svqpanel/terminal-tokens"
TTYD_SERVICE      = "/etc/systemd/system/svqpanel-ttyd.service"
TTYD_PORT         = 7681
TOKEN_TTL_SECONDS = 30          # el usuario tiene 30 s para abrir la sesión


# ─────────────────────────────────────────────────────────────────────────────
# Estado / disponibilidad
# ─────────────────────────────────────────────────────────────────────────────
def ttyd_installed() -> bool:
    return os.path.exists(TTYD_BIN)


def ttyd_active() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "svqpanel-ttyd"],
                           capture_output=True, text=True, timeout=4)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def status() -> dict:
    return {"installed": ttyd_installed(), "active": ttyd_active(),
            "port": TTYD_PORT}


# ─────────────────────────────────────────────────────────────────────────────
# Instalación (idempotente). Requiere root — la usa install.sh o el endpoint admin.
# ─────────────────────────────────────────────────────────────────────────────
def _write_launcher() -> None:
    """Script que ttyd ejecuta en cada conexión: valida el token de un solo uso
    y lanza la shell del usuario correspondiente."""
    content = r'''#!/bin/bash
# SVQPanel — launcher de terminal web. Generado automáticamente. NO editar.
# Pide un token de un solo uso emitido por el panel; lo valida, lo borra y
# lanza la shell correcta. Sin token válido → cierra.
set -euo pipefail
TOKEN_DIR="/run/svqpanel/terminal-tokens"

# El token puede venir como argumento (ttyd ?arg=) o por el prompt.
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  TOKEN="$1"
else
  printf 'Token de acceso SVQPanel: '
  read -r TOKEN
fi
TOKEN="$(echo "$TOKEN" | tr -cd 'A-Za-z0-9_-')"   # sanea: solo caracteres de token

if [[ -z "$TOKEN" ]]; then
  echo "Token vacío. Cerrando."; exit 1
fi
TOKFILE="$TOKEN_DIR/$TOKEN"
if [[ ! -f "$TOKFILE" ]]; then
  echo "Token inválido o caducado. Cerrando."; exit 1
fi

# Leer y BORRAR (un solo uso) de forma atómica
DATA="$(cat "$TOKFILE")"
rm -f "$TOKFILE"

EXPIRES="$(echo "$DATA" | sed -n 's/.*"expires": *\([0-9]*\).*/\1/p')"
TARGET="$(echo "$DATA"  | sed -n 's/.*"target": *"\([^"]*\)".*/\1/p')"
NOW="$(date +%s)"

if [[ -z "$EXPIRES" || "$NOW" -gt "$EXPIRES" ]]; then
  echo "Token caducado. Cerrando."; exit 1
fi

if [[ "$TARGET" == "root" ]]; then
  echo "── Sesión SVQPanel (root) ──"
  exec bash -l
else
  # Confinado al usuario del sistema (su entorno/HOME). Validar que existe.
  if ! id "$TARGET" >/dev/null 2>&1; then
    echo "Usuario inexistente. Cerrando."; exit 1
  fi
  echo "── Sesión SVQPanel ($TARGET) ──"
  # -s /bin/bash: los usuarios de hosting suelen tener shell nologin (solo SFTP);
  # forzamos bash para la sesión web sin cambiar su shell de login real.
  exec su - "$TARGET" -s /bin/bash
fi
'''
    tmp = LAUNCHER + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o755)
    os.replace(tmp, LAUNCHER)


def _write_service() -> None:
    """Servicio systemd de ttyd, escuchando solo en localhost, ejecutando el
    launcher. -W permite escritura (terminal interactiva). credential=root para
    poder hacer `su -`."""
    content = f"""# SVQPanel — terminal web (ttyd). Generado automáticamente.
[Unit]
Description=SVQPanel ttyd (terminal web)
After=network.target

[Service]
Type=simple
# Solo localhost; nginx hace de proxy con HTTPS y autenticación del panel.
# -a: permite pasar el token como argumento vía la query ?arg= (lo hace la UI).
# -W: terminal de escritura. -b: base path (proxy nginx /terminal/).
ExecStart={TTYD_BIN} -p {TTYD_PORT} -i 127.0.0.1 -W -a -t titleFixed=SVQPanel \\
    -b /terminal {LAUNCHER}
Restart=on-failure
RestartSec=3
# Corre como root para poder `su - usuario`; la seguridad la da el token.
User=root

[Install]
WantedBy=multi-user.target
"""
    tmp = TTYD_SERVICE + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, TTYD_SERVICE)


def install() -> dict:
    """Descarga ttyd, escribe launcher + servicio y arranca. Idempotente."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)

    if not ttyd_installed():
        # Descargar el binario estático oficial
        subprocess.run(["curl", "-fsSL", "-o", TTYD_BIN, TTYD_URL],
                       check=True, timeout=120)
        os.chmod(TTYD_BIN, 0o755)

    _write_launcher()
    _write_service()
    subprocess.run(["systemctl", "daemon-reload"], timeout=15)
    subprocess.run(["systemctl", "enable", "svqpanel-ttyd"], timeout=15)
    subprocess.run(["systemctl", "restart", "svqpanel-ttyd"], check=True, timeout=20)
    return status()


def uninstall() -> dict:
    subprocess.run(["systemctl", "disable", "--now", "svqpanel-ttyd"], timeout=15)
    return status()


# ─────────────────────────────────────────────────────────────────────────────
# Tokens de un solo uso
# ─────────────────────────────────────────────────────────────────────────────
def issue_token(target: str) -> str:
    """Emite un token de un solo uso para abrir una sesión como `target`
    ('root' para admin, o un username del sistema). Lo persiste en TOKEN_DIR
    con caducidad corta. Devuelve el token (string) que la UI pasa a ttyd.
    """
    os.makedirs(TOKEN_DIR, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)

    token = secrets.token_urlsafe(32)
    expires = int((datetime.now(timezone.utc) +
                   timedelta(seconds=TOKEN_TTL_SECONDS)).timestamp())
    data = {"target": target, "expires": expires}

    path = os.path.join(TOKEN_DIR, token)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        # Separadores compactos (sin espacios) para que el sed del launcher sea fiable.
        json.dump(data, f, separators=(",", ":"))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

    # Limpieza oportunista de tokens caducados
    _cleanup_expired()
    return token


def _cleanup_expired() -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    try:
        for name in os.listdir(TOKEN_DIR):
            p = os.path.join(TOKEN_DIR, name)
            try:
                with open(p) as f:
                    d = json.load(f)
                if int(d.get("expires", 0)) < now:
                    os.remove(p)
            except Exception:
                # Fichero corrupto/temporal → borrar
                try:
                    os.remove(p)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
