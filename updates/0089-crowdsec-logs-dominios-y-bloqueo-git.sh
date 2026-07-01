#!/bin/bash
# 0089-crowdsec-logs-dominios-y-bloqueo-git.sh
#
# Dos defensas contra los ataques a las webs de clientes:
#
# 1) CrowdSec CIEGO ante los dominios — sus acquisitions (setup.nginx/apache2.yaml)
#    solo leen /var/log/nginx|apache2/*.log (el panel), NO los logs de los dominios
#    (/home/*/web/*/logs/). Resultado: la fuerza bruta DISTRIBUIDA a wp-login
#    (decenas de IPs, 2-3 intentos c/u → cada una bajo el umbral del rate-limit por
#    IP) no la para nadie. CrowdSec sí puede (banea por reputación), pero no veía
#    esos logs. Se añade una acquisition propia con los access.log de los dominios.
#
# 2) Bloqueo de /.git/ /.env /.svn… — los bots sondean /.git/config, /.env para
#    robar credenciales o el repo entero. El generador de vhosts ya lo bloquea
#    (return 444); este update REGENERA todos los vhosts para propagarlo.
#
# Idempotente y no interactivo.

set -u

echo "→ 0089: CrowdSec logs de dominios + bloqueo /.git/…"

# ── 1) Acquisition de CrowdSec para los logs de los dominios ────────────────
if [ -d /etc/crowdsec ]; then
    ACQ=/etc/crowdsec/acquis.d/svqpanel-domains.yaml
    mkdir -p /etc/crowdsec/acquis.d
    cat > "$ACQ" <<'CSDOMEOF'
# SVQPanel — logs de acceso de los dominios de clientes (para escenarios http-*)
filenames:
  - /home/*/web/*/logs/nginx.access.log
labels:
  type: nginx
---
filenames:
  - /home/*/web/*/logs/apache.access.log
labels:
  type: apache2
CSDOMEOF
    echo "  ✓ acquisition escrita ($ACQ)"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart crowdsec >/dev/null 2>&1 \
            && echo "  ✓ crowdsec reiniciado (ahora ve los logs de dominios)" \
            || echo "  ⚠ no se pudo reiniciar crowdsec (revisar: journalctl -u crowdsec)"
    fi
else
    echo "  · /etc/crowdsec no existe (CrowdSec no instalado); se omite"
fi

# ── 2) Regenerar vhosts para propagar el bloqueo /.git/ ─────────────────────
if [ -x /opt/svqpanel/venv/bin/python ]; then
    echo "  · regenerando vhosts (bloqueo /.git/ /.env /.svn)…"
    (cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts) \
        && echo "  ✓ vhosts regenerados" \
        || echo "  ⚠ fallo regenerando algún vhost; se continúa"
else
    echo "  · venv no encontrado; se omite la regeneración de vhosts"
fi

echo "✓ 0089: CrowdSec ve los dominios + /.git/ bloqueado"
exit 0
