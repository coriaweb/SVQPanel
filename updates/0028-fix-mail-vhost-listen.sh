#!/bin/bash
# 0028-fix-mail-vhost-listen.sh
#
# Corrige los vhosts de webmail.* y mail.* que ataban el listen a la IPv4
# (listen <IP>:443). Eso hacía a esos vhosts el "default" de la IP y capturaban
# tráfico de otros server_name (p.ej. www.dominio acababa redirigido a webmail),
# además de crear una asimetría IPv4/IPv6 (el [::]:443 no se ataba) que detecta
# internet.nl ("Same website on IPv6 and IPv4").
#
# El código nuevo ya genera estos vhosts con listen GENÉRICO; este update los
# regenera en los servidores ya instalados. Invoca el código del panel
# (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0028: corregir listen atado a IP en vhosts webmail/mail…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli fix_mail_vhosts || {
    echo "  ⚠ fix_mail_vhosts devolvió error (no crítico)."
    exit 0
}

nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

echo "✓ 0028: vhosts webmail/mail corregidos"
exit 0
