#!/bin/bash
# 0133-umbrales-antispam-estrictos.sh
#
# Nuevos umbrales antispam por defecto del panel: greylist 3 / marcar spam 4 /
# rechazar 10 (antes se heredaban los de fábrica de Rspamd: 4/6/15, demasiado
# laxos — el spam de 4-6 puntos aterrizaba en la bandeja de entrada).
#
# Racional: a 4+ puntos casi no hay correo legítimo, y acabar en No deseado es
# recuperable (y al sacarlo entrena el Bayes). El rechazo se queda en 10 (no
# menos) para no rebotar correo legítimo un mal día del DNS o del Bayes: el
# BCC legítimo ya carga con FORGED_RECIPIENTS (+2) y un Bayes equivocado suma
# +5.1, así que a 8 aún caería correo bueno.
#
# ⚠️ RESPETA a los admins que ya personalizaron sus umbrales: si existe
# /etc/rspamd/local.d/actions.conf, NO se toca nada (ensure_default_actions).
# Los servidores nuevos nacen ya con estos valores (install.sh).
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0133: umbrales antispam por defecto 3/4/10 (si no están personalizados)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

if ! command -v rspamadm >/dev/null 2>&1; then
    echo "  Sin Rspamd en este servidor (sin correo) — nada que hacer."
    exit 0
fi

cd /opt/svqpanel
"$PYBIN" -m api.cli ensure_antispam_defaults || \
    echo "  ⚠ ensure_antispam_defaults con incidencias (no crítico)."

echo "✓ 0133: umbrales antispam aplicados (o respetados los del admin)"
exit 0
