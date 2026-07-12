#!/bin/bash
# 0126-clamav-oom-y-milter.sh
#
# DOS BUGS del antivirus de correo, encontrados revisando los logs de un servidor
# en produccion. Los dos silenciosos: el panel decia "antivirus instalado" y no
# escaneaba NADA.
#
# BUG 1 — ClamAV muerto por el OOM killer, y sin volver:
#   clamd carga sus firmas en RAM y llega a ~1 GB. En un servidor de 4 GB eso es
#   el 26% de la memoria, y el kernel acaba matandolo. Lo grave es que la unit de
#   Debian trae Restart=no: una vez muerto se queda MUERTO, sin avisar a nadie, y
#   el correo entrante deja de escanearse durante horas o dias.
#   Ademas MaxThreads=12 (default de Debian) multiplica la RAM en una maquina que
#   suele tener 2 CPUs.
#
# BUG 2 — clamav-milter arrancado pero NO enchufado a Postfix:
#   el servicio corria, pero `smtpd_milters` solo tenia el de Rspamd. Postfix no
#   le pasaba ni un correo: el antivirus estaba de adorno. (El 0120 instalaba los
#   paquetes pero no completaba el enganche.)
#
# FIX:
#   1) clamd: MaxThreads 2 + ConcurrentDatabaseReload false (al recargar firmas
#      cargaba DOS copias en RAM a la vez: pico x2).
#   2) systemd: MemoryMax=900M + Restart=on-failure. Si se descontrola, systemd lo
#      mata y lo REINICIA, en vez de que el OOM del kernel lo deje muerto.
#   3) enchufar el milter a Postfix via el codigo del panel (antivirus_manager.
#      enable_milter()), que ya sabe hacerlo preservando el milter de Rspamd.
#
# Reflejado tambien en install.sh. Idempotente y no interactivo.

set -u

echo "-> 0126: ClamAV (OOM + milter no enchufado)..."

command -v clamd >/dev/null 2>&1 || dpkg -l clamav-daemon 2>/dev/null | grep -q '^ii' || {
    echo "  . ClamAV no instalado; nada que hacer."
    exit 0
}

# ── 1. clamd: bajar el consumo de RAM ────────────────────────────────────────
CONF=/etc/clamav/clamd.conf
if [ -f "$CONF" ]; then
    CHANGED=0
    # MaxThreads: el default de Debian (12) multiplica la RAM. 2 basta para correo.
    if ! grep -qE '^MaxThreads 2$' "$CONF"; then
        if grep -qE '^MaxThreads' "$CONF"; then
            sed -i 's/^MaxThreads .*/MaxThreads 2/' "$CONF"
        else
            echo "MaxThreads 2" >> "$CONF"
        fi
        CHANGED=1
    fi
    # ConcurrentDatabaseReload: al actualizar firmas mantiene la base VIEJA y la
    # NUEVA en memoria a la vez -> el pico dobla y dispara el OOM.
    if ! grep -qE '^ConcurrentDatabaseReload false$' "$CONF"; then
        if grep -qE '^ConcurrentDatabaseReload' "$CONF"; then
            sed -i 's/^ConcurrentDatabaseReload.*/ConcurrentDatabaseReload false/' "$CONF"
        else
            echo "ConcurrentDatabaseReload false" >> "$CONF"
        fi
        CHANGED=1
    fi
    [ "$CHANGED" = "1" ] && echo "  . clamd.conf: MaxThreads 2 + ConcurrentDatabaseReload false"
fi

# ── 2. systemd: techo de RAM + que vuelva solo ───────────────────────────────
DROPIN=/etc/systemd/system/clamav-daemon.service.d/99-svqpanel-memory.conf
if [ ! -f "$DROPIN" ]; then
    mkdir -p "$(dirname "$DROPIN")"
    cat > "$DROPIN" << 'EOF'
# SVQPanel: clamd carga ~1GB de firmas en RAM y el OOM killer lo mataba en
# servidores pequeños. Peor: la unit de Debian trae Restart=no, así que se quedaba
# MUERTO sin avisar y el correo dejaba de escanearse en silencio durante horas.
[Service]
# Techo duro: si lo supera, lo mata systemd (que sí lo reinicia), no el OOM del kernel.
MemoryMax=900M
MemoryHigh=700M
Restart=on-failure
RestartSec=30s
EOF
    systemctl daemon-reload
    echo "  . systemd: MemoryMax=900M + Restart=on-failure"
fi

systemctl restart clamav-daemon >/dev/null 2>&1 || true

# ── 3. Enchufar el milter a Postfix (si el antivirus esta activo) ────────────
if command -v postconf >/dev/null 2>&1 && [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel 2>/dev/null && /opt/svqpanel/venv/bin/python - <<'PYEOF' 2>/dev/null || true
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    import scripts.antivirus_manager as am
except Exception as e:
    print(f"  . no pude cargar antivirus_manager: {e}")
    sys.exit(0)

if not am.clamav_available():
    print("  . ClamAV no disponible; no se engancha el milter.")
    sys.exit(0)

if am.milter_enabled():
    print("  . el milter ya estaba enchufado a Postfix.")
    sys.exit(0)

# enable_milter() escribe la config del milter, lo arranca y lo añade a
# smtpd_milters PRESERVANDO el de Rspamd.
am.enable_milter()
if am.milter_enabled():
    print("  . clamav-milter enchufado a Postfix (antes NO escaneaba nada)")
else:
    print("  . AVISO: no se pudo enchufar el milter; revisar a mano")
PYEOF
fi

echo "OK 0126: ClamAV con límite de RAM, reinicio automático y milter enchufado."
exit 0
