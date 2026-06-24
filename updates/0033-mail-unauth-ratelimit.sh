#!/bin/bash
# 0033-mail-unauth-ratelimit.sh
#
# Cierra el agujero por el que un sitio web HACKEADO podía enviar correo sin
# límite: el correo NO autenticado (PHP mail()/sendmail desde localhost, p.ej.
# formularios de contacto) no se contabilizaba en el rate-limit de Rspamd.
#
# Ahora se limita por el USUARIO DEL SISTEMA del envelope sender (cada cliente
# corre su PHP como su propio usuario), con un tope conservador por defecto
# (RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR). Este update:
#   1) Activa mail.add_x_header en los php.ini de FPM (identifica el script que
#      envía: cabecera X-PHP-Originating-Script).
#   2) Regenera la config de rate-limit de Rspamd desde la BD (incl. el no-auth).
#
# Invoca el código del panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0033: límite de correo no autenticado (anti-spam de sitios hackeados)…"

# 1) mail.add_x_header = On en cada php.ini de FPM presente.
for ini in /etc/php/*/fpm/php.ini; do
    [ -f "$ini" ] || continue
    if grep -q "^\s*;\?\s*mail.add_x_header" "$ini"; then
        sed -i "s|^\s*;\?\s*mail.add_x_header\s*=.*|mail.add_x_header = On|" "$ini"
    else
        echo "mail.add_x_header = On" >> "$ini"
    fi
done
# Recargar los FPM para que tome el php.ini (no crítico si falla).
for svc in $(systemctl list-units --type=service --no-legend 'php*-fpm*' 2>/dev/null | awk '{print $1}'); do
    systemctl reload "$svc" 2>/dev/null || systemctl restart "$svc" 2>/dev/null || true
done

# 2) Regenerar el rate-limit de Rspamd (incluye el límite no-auth).
PYBIN=/opt/svqpanel/venv/bin/python
if [ -x "$PYBIN" ]; then
    cd /opt/svqpanel
    "$PYBIN" -m api.cli rebuild_mail_ratelimit || \
        echo "  ⚠ rebuild_mail_ratelimit con incidencias (no crítico)."
fi

echo "✓ 0033: límite de correo no autenticado aplicado"
exit 0
