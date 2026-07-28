#!/bin/bash
# 0128-dkim-automatico-backfill.sh
#
# Outlook/Hotmail y Gmail EXIGEN SPF+DKIM+DMARC desde mayo 2025 (el correo sin
# firma va a spam o se rechaza). El panel publicaba SPF y DMARC automáticamente
# al activar el correo de un dominio, pero el DKIM solo se generaba si alguien
# pulsaba el botón de la pestaña DKIM: en el primer servidor había 13 de 47
# dominios de correo sin firma.
#
# Desde v0.214.0 el alta de correo genera el DKIM sola. Este update es el
# backfill para los dominios ya existentes con dkim_enabled=false:
#   - genera la clave (o REUTILIZA la que hubiera en disco, para no invalidar
#     un TXT ya publicado en un DNS externo) y la declara en selectors.map
#   - publica el TXT en la zona DNS del panel si el dominio la tiene; si su DNS
#     está fuera, la clave queda lista y el TXT pendiente (visible en la
#     pestaña DKIM del dominio)
#
# Idempotente (solo actúa sobre dominios sin DKIM) y no interactivo.

set -u

echo "-> 0128: backfill DKIM de dominios de correo sin firma..."

PY=/opt/svqpanel/venv/bin/python
[ -x "$PY" ] || { echo "  . venv del panel no encontrado; nada que hacer."; exit 0; }
[ -d /etc/rspamd ] || { echo "  . Rspamd no instalado (servidor sin correo); nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PY" -m api.cli backfill_dkim || { echo "  ⚠️ backfill_dkim falló"; exit 1; }

echo "OK 0128: backfill DKIM completado."
exit 0
