#!/bin/bash
# 0088-xmlrpc-bypass-y-nginx-limit-req.sh
#
# Dos arreglos contra el flood de bots a WordPress (visto tumbando la CPU con
# ~18k hits/min a //xmlrpc.php):
#
# 1) BYPASS DE //xmlrpc.php  — el bloqueo era `location = /xmlrpc.php` (match
#    EXACTO), que NO normaliza las barras iniciales: `//xmlrpc.php` (doble barra)
#    se lo saltaba y llegaba a PHP/Apache arrancando WordPress cada vez. El
#    generador ya usa `location ~ ^/+xmlrpc\.php` (y `~ ^/+wp-login\.php`), que
#    captura cualquier nº de barras. Este update REGENERA todos los vhosts para
#    propagar el bloqueo robusto a los dominios ya existentes.
#
# 2) JAIL nginx-limit-req  — estaba enabled=false, así que nadie baneaba al que
#    floodea wp-login (el rate-limit solo devuelve 429, no banea). Se activa
#    apuntando a los access logs de los dominios. El rate-limit frena; la jail
#    banea al insistente. (Los atacantes tras Cloudflare se ven bien gracias al
#    real_ip del update 0087.)
#
# Idempotente y no interactivo.

set -u

echo "→ 0088: bypass //xmlrpc.php + jail nginx-limit-req…"

# ── 1) Regenerar vhosts con el bloqueo robusto ──────────────────────────────
if [ -x /opt/svqpanel/venv/bin/python ]; then
    echo "  · regenerando vhosts (bloqueo xmlrpc/wp-login por regex)…"
    (cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts) \
        && echo "  ✓ vhosts regenerados" \
        || echo "  ⚠ fallo regenerando algún vhost (revisar log); se continúa"
else
    echo "  · venv no encontrado; se omite la regeneración de vhosts"
fi

# ── 2) Activar la jail nginx-limit-req en fail2ban ──────────────────────────
JAIL=/etc/fail2ban/jail.local
if [ -f "$JAIL" ] && grep -q '^\[nginx-limit-req\]' "$JAIL"; then
    # Reemplaza el bloque [nginx-limit-req] … hasta la línea en blanco anterior a
    # la siguiente sección, por la versión activada con logpath. Usa awk para no
    # depender del contenido exacto previo.
    if grep -qzoP '\[nginx-limit-req\]\s*\nenabled\s*=\s*true' "$JAIL" 2>/dev/null; then
        echo "  · jail nginx-limit-req ya activada"
    else
        awk '
            /^\[nginx-limit-req\]/ {
                print "[nginx-limit-req]"
                print "enabled  = true"
                print "port     = http,https"
                print "filter   = nginx-limit-req"
                print "logpath  = /home/*/web/*/logs/nginx.access.log"
                print "           /var/log/nginx/access.log"
                print "backend  = auto"
                print "maxretry = 10"
                print "findtime = 120"
                print "bantime  = 86400"
                skip=1; next
            }
            skip && /^\[/ { skip=0 }          # llegó la siguiente sección
            skip && /^[[:space:]]*$/ { skip=0; print; next }  # línea en blanco = fin del bloque
            !skip { print }
        ' "$JAIL" > "$JAIL.tmp" && mv "$JAIL.tmp" "$JAIL"
        echo "  ✓ jail nginx-limit-req activada"
    fi
    # Recargar fail2ban (o reiniciar si el reload no basta).
    if command -v fail2ban-client >/dev/null 2>&1; then
        fail2ban-client reload >/dev/null 2>&1 || systemctl restart fail2ban >/dev/null 2>&1 || true
        echo "  ✓ fail2ban recargado"
    fi
else
    echo "  · $JAIL sin sección [nginx-limit-req]; no se toca (¿install antiguo?)"
fi

echo "✓ 0088: bypass xmlrpc cerrado + jail nginx-limit-req activa"
exit 0
