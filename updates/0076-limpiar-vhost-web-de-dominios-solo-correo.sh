#!/bin/bash
# 0076-limpiar-vhost-web-de-dominios-solo-correo.sh
#
# BUG: cmd_regenerate_all_vhosts regeneraba vhost web para TODOS los dominios,
# incluidos los marcados como solo-correo/DNS (mail_dns_only). Esos dominios no
# tienen public_html, así que su vhost apunta a un directorio inexistente. Como
# Apache valida TODA la config de golpe, un único vhost así hace fallar
# `apache2ctl configtest` y BLOQUEA la regeneración/recarga de TODOS los demás
# dominios (efecto dominó: 1 roto → 41 "con error").
#
# El código ya está corregido (cmd_regenerate_all_vhosts ahora salta
# mail_dns_only). Este update limpia los vhosts web YA creados en disco para
# dominios mail_dns_only y recarga los webservers.
#
# Idempotente: si no hay ninguno, no hace nada. No interactivo.

set -u

echo "→ 0076: limpiar vhosts web de dominios solo-correo/DNS (mail_dns_only)…"

cd /opt/svqpanel || { echo "✓ 0076: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

# Sacar de la BD los dominios solo-correo/DNS (a través del código del panel,
# sin hardcodear credenciales).
DOMINIOS=$("$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.models.models_domain import Domain
except Exception as e:
    print(f"__ERR__ {e}", file=sys.stderr)
    sys.exit(0)
db = SessionLocal()
try:
    for d in db.query(Domain).filter(Domain.mail_dns_only.is_(True)).all():
        print(d.domain_name)
finally:
    db.close()
PY
)

if [ -z "${DOMINIOS// }" ]; then
    echo "  · no hay dominios solo-correo/DNS; nada que limpiar"
    echo "✓ 0076: completado"
    exit 0
fi

TOCADO=0
for d in $DOMINIOS; do
    # Apache: deshabilitar y borrar vhost si existe.
    if [ -e "/etc/apache2/sites-available/$d.conf" ] || [ -L "/etc/apache2/sites-enabled/$d.conf" ]; then
        echo "  · $d: quitando vhost Apache (solo-correo, no debe tener web)"
        a2dissite "$d.conf" >/dev/null 2>&1 || true
        a2dissite "$d"      >/dev/null 2>&1 || true
        rm -f "/etc/apache2/sites-enabled/$d.conf" "/etc/apache2/sites-available/$d.conf"
        TOCADO=1
    fi
    # Nginx: idem (por si en algún servidor se creó ahí).
    if [ -e "/etc/nginx/sites-available/$d" ] || [ -L "/etc/nginx/sites-enabled/$d" ]; then
        echo "  · $d: quitando vhost nginx (solo-correo, no debe tener web)"
        rm -f "/etc/nginx/sites-enabled/$d" "/etc/nginx/sites-available/$d"
        TOCADO=1
    fi
done

if [ "$TOCADO" -eq 0 ]; then
    echo "  · ningún vhost web de dominio solo-correo en disco; nada que hacer"
    echo "✓ 0076: completado"
    exit 0
fi

# Recargar webservers solo si validan (no romper si quedara otra cosa mal).
if command -v apache2ctl >/dev/null 2>&1 && [ -d /etc/apache2/sites-enabled ]; then
    if apache2ctl configtest >/dev/null 2>&1; then
        systemctl reload apache2 >/dev/null 2>&1 || true
        echo "  ✓ apache2 configtest OK; recargado"
    else
        echo "  ⚠ apache2 configtest aún falla (revisar otros vhosts):"
        apache2ctl configtest 2>&1 | tail -3 | sed 's/^/    /'
    fi
fi
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
    echo "  ✓ nginx -t OK; recargado"
fi

echo "✓ 0076: completado"
exit 0
