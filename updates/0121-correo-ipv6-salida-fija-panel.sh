#!/bin/bash
# 0121-correo-ipv6-salida-fija-panel.sh
#
# BUG: en un servidor con IPv6, el correo saliente salia por una IPv6 SLAAC
# ALEATORIA del /64 (Postfix sin smtp_bind_address6 deja elegir al SO). Esa IPv6
# cambia y no tiene PTR ni esta en el SPF -> Gmail marcaba spf=fail y arriesga
# rechazo por PTR faltante. NO se soluciona apagando IPv6: se soluciona fijando UNA
# IPv6 estable de salida.
#
# FIX: fijar smtp_bind_address6 a la IPv6 del PANEL (panel_ipv6, la ::1 del rango) —
# la misma que va al SPF. Asi el correo por IPv6 sale por una IP predecible, con PTR
# (que el admin configura en su proveedor) y en el SPF. IPv6 SIGUE activa. La vista
# de Salud de correo del panel avisa si a esa IP le falta el PTR.
#
# A partir de ahora, activar la IPv6 del panel fija el bind6 automaticamente
# (api/routes/settings.py). Este update lo aplica a los que YA tienen IPv6.
#
# Solo si hay Postfix e IPv6 del panel. Idempotente y no interactivo.

set -u

echo "-> 0121: fijar IPv6 de salida del correo a la del panel..."

if ! command -v postconf >/dev/null 2>&1; then
    echo "  . Postfix no instalado; nada que hacer."
    exit 0
fi

# Leer la IPv6 del panel (panel_ipv6) de la BD.
PANEL_IP6=""
if [ -x /opt/svqpanel/venv/bin/python ]; then
    PANEL_IP6="$(cd /opt/svqpanel 2>/dev/null && /opt/svqpanel/venv/bin/python - <<'PYEOF' 2>/dev/null
try:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.routes.settings import get_or_create_settings
    db = SessionLocal()
    s = get_or_create_settings(db)
    print((s.panel_ipv6 or "").strip())
    db.close()
except Exception:
    print("")
PYEOF
)"
fi

if [ -z "$PANEL_IP6" ]; then
    echo "  . El panel no tiene IPv6 activada (panel_ipv6 vacio); nada que hacer."
    echo "    (Cuando actives la IPv6 del panel, el bind6 se fija solo.)"
    exit 0
fi

CUR="$(postconf -h smtp_bind_address6 2>/dev/null)"
if [ "$CUR" = "$PANEL_IP6" ]; then
    echo "  . smtp_bind_address6 ya es $PANEL_IP6; nada que hacer."
    exit 0
fi

postconf -e "smtp_bind_address6 = $PANEL_IP6"
echo "  . smtp_bind_address6: '$CUR' -> $PANEL_IP6"

if postfix check 2>/dev/null; then
    systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true
    echo "  . Postfix recargado."
fi

echo "OK 0121: correo IPv6 sale por $PANEL_IP6 (configura su PTR en el proveedor)."
exit 0
