#!/bin/bash
# 0079-ssh-fail2ban-estricto.sh
#
# Endurece SSH y fail2ban (política estricta de fuerza bruta).
#
# Diagnóstico que motiva el cambio: en producción se vieron ~6700 fallos de
# login SSH en 7 días desde ~714 IPs únicas, pero fail2ban solo mantenía 5 IPs
# baneadas porque cada baneo duraba 1h y NO escalaba → "puerta giratoria":
# el bot baneado vuelve cada hora indefinidamente.
#
# Cambios (idempotentes):
#   1) [DEFAULT] de jail.local → activa bantime.increment (baneo exponencial
#      para reincidentes, global a TODAS las jails: ssh, dovecot, postfix, auth).
#      factor=2, maxtime=4w, rndtime=30m. El historial por IP persiste en la BD
#      de fail2ban (sobrevive reinicios).
#   2) [sshd] → maxretry 3, findtime 30m, bantime inicial 12h (escala solo).
#   3) sshd_config: MaxAuthTries 3, LoginGraceTime 20, MaxStartups 10:30:60.
#
# NO toca PasswordAuthentication ni PermitRootLogin (se mantiene el acceso por
# contraseña de root; el endurecimiento de eso es un paso futuro aparte).
#
# Idempotente y no interactivo.

set -u

echo "→ 0079: SSH + fail2ban estricto (baneo escalado para reincidentes)…"

# ── 1 + 2. fail2ban: increment global + jail sshd estricta ──────────────────
JAIL=/etc/fail2ban/jail.local
if [ -f "$JAIL" ] && command -v fail2ban-client >/dev/null 2>&1; then
    python3 - "$JAIL" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

# --- Limpieza defensiva: eliminar bloques '[DEFAULT].' MAL FORMADOS (con punto u
# otra basura tras el corchete) que ediciones previas pudieran haber dejado. Un
# '[DEFAULT].' seguido de opciones DUPLICA maxretry/findtime/bantime en el DEFAULT
# real y hace que fail2ban NO ARRANQUE ("option 'maxretry' ... already exists").
# Quitamos la etiqueta mal formada y sus líneas de opciones inmediatas. Idempotente.
s = re.sub(
    r"\n\[DEFAULT\]\.[^\n]*\n(?:\s*(?:maxretry|findtime|bantime)\s*=.*\n)+",
    "\n", s)

# --- [DEFAULT]: asegurar las directivas bantime.* (añadir o actualizar) ---
def ensure_in_default(text, key, value):
    """Pone 'key = value' dentro del bloque [DEFAULT]. Si la clave ya existe la
    actualiza; si no, la inserta justo después de la línea 'ignoreip ='."""
    m = re.search(r"^\[DEFAULT\][^\[]*", text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return text  # sin [DEFAULT] no tocamos nada
    block = m.group(0)
    line_re = re.compile(rf"^{re.escape(key)}\s*=.*$", flags=re.MULTILINE)
    if line_re.search(block):
        new_block = line_re.sub(f"{key} = {value}", block, count=1)
    else:
        # insertar tras 'ignoreip =' (o al final del bloque si no está)
        ig = re.search(r"^ignoreip\s*=.*$", block, flags=re.MULTILINE)
        if ig:
            new_block = block[:ig.end()] + f"\n{key} = {value}" + block[ig.end():]
        else:
            new_block = block.rstrip("\n") + f"\n{key} = {value}\n"
    return text[:m.start()] + new_block + text[m.end():]

for k, v in (
    ("bantime.increment", "true"),
    ("bantime.factor",    "2"),
    ("bantime.maxtime",   "4w"),
    ("bantime.rndtime",   "30m"),
):
    s = ensure_in_default(s, k, v)

# --- [sshd]: maxretry 3, findtime 30m, bantime 12h ---
m = re.search(r"^\[sshd\][^\[]*", s, flags=re.MULTILINE | re.DOTALL)
if m:
    block = m.group(0)
    def setkv(b, key, value):
        r = re.compile(rf"^{re.escape(key)}\s*=.*$", flags=re.MULTILINE)
        if r.search(b):
            return r.sub(f"{key} = {value}", b, count=1)
        # añadir la clave conservando los saltos finales del bloque (la línea en
        # blanco que separa de la siguiente sección [..]).
        core = b.rstrip("\n")
        tail = b[len(core):]  # los "\n" que había al final
        return core + f"\n{key} = {value}" + (tail or "\n")
    block = setkv(block, "maxretry", "3")
    block = setkv(block, "findtime", "30m")
    block = setkv(block, "bantime",  "12h")
    s = s[:m.start()] + block + s[m.end():]

if s != orig:
    open(p, "w").write(s)
    print("  ✓ jail.local actualizado (increment global + sshd estricto)")
else:
    print("  · jail.local ya estaba al día")
PYEOF

    # Validar antes de recargar para no dejar fail2ban caído.
    if fail2ban-client -d >/dev/null 2>&1; then
        systemctl restart fail2ban >/dev/null 2>&1 || true
        echo "  ✓ fail2ban recargado"
    else
        echo "  ✗ fail2ban-client -d falló; revisa $JAIL (no se recargó)"
    fi
else
    echo "  · fail2ban no gestionado por el panel; salto jail.local"
fi

# ── 3. sshd: endurecer límites de auth ──────────────────────────────────────
SSHD_HARDEN=/etc/ssh/sshd_config.d/99-svqpanel.conf
if [ -d /etc/ssh/sshd_config.d ]; then
    cat > "$SSHD_HARDEN" << 'SSHDEOF'
# SVQPanel — hardening SSH (mínimo, no rompe el acceso por contraseña de root)
X11Forwarding no
# No permitir contraseñas vacías (por si acaso)
PermitEmptyPasswords no
# Límite de intentos de auth por conexión (estricto: 3, complementa a fail2ban)
MaxAuthTries 3
# Tiempo máximo para autenticarse antes de cerrar (corta bots que se cuelgan)
LoginGraceTime 20
# Sin sesiones múltiples sin autenticar en paralelo desde una misma conexión
MaxStartups 10:30:60
SSHDEOF
    # Asegurar que sshd_config incluye el directorio (Debian 12+ ya lo trae).
    if ! grep -qE '^\s*Include\s+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config 2>/dev/null; then
        echo "Include /etc/ssh/sshd_config.d/*.conf" >> /etc/ssh/sshd_config
    fi
    # Validar antes de recargar: si falla, revertir para no dejar SSH roto.
    if sshd -t 2>/dev/null; then
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
        echo "  ✓ sshd endurecido (MaxAuthTries 3, LoginGraceTime 20)"
    else
        rm -f "$SSHD_HARDEN"
        echo "  ✗ sshd -t falló; revertido (SSH intacto)"
    fi
else
    echo "  · /etc/ssh/sshd_config.d no existe; salto hardening sshd"
fi

echo "✓ 0079: SSH + fail2ban estricto aplicado"
exit 0
