#!/bin/bash
# SVQPanel — hook de certbot para la validación DNS-01 (certificados wildcard).
# certbot lo guarda en /etc/letsencrypt/renewal/<dominio>.conf y lo vuelve a
# llamar en cada renovación automática. Recibe CERTBOT_DOMAIN y
# CERTBOT_VALIDATION por el entorno. Uso: certbot-dns-hook.sh auth|cleanup
# La lógica está en scripts/acme_dns.py.
cd /opt/svqpanel || exit 1
exec /opt/svqpanel/venv/bin/python -m api.cli acme_dns_hook "$1"
