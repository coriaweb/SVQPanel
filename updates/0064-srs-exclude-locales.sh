#!/bin/bash
# 0064-srs-exclude-locales.sh
#
# SRS estaba reescribiendo TODO el correo, incluido el PROPIO de nuestros
# dominios (formularios PHP, notificaciones, buzón→buzón), no solo los reenvíos.
# Eso convertía remitentes legítimos en direcciones SRS0=...@mydomain (un buzón
# que responde queda con un remitente sin sentido y Rspamd marca "el remitente
# visible no coincide con el real").
#
# SRS solo debe reescribir el envelope-sender de los REENVÍOS (origen externo).
# Este update sincroniza SRS_EXCLUDE_DOMAINS de postsrsd con los dominios LOCALES
# (mydomain + myhostname + virtual_mailbox_domains) invocando el código del panel.
#
# Idempotente y no interactivo. No-op si postsrsd no está instalado.

set -u

echo "→ 0064: SRS — excluir dominios locales (solo reescribir reenvíos)…"

if [ ! -f /etc/default/postsrsd ]; then
    echo "✓ 0064: postsrsd no instalado; nada que hacer"
    exit 0
fi

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  ⚠ venv del panel no encontrado; nada que hacer"
    exit 0
fi

cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli sync_srs_excludes || {
    echo "  ⚠ sync_srs_excludes devolvió error (no crítico)"
    exit 0
}

echo "✓ 0064: SRS solo reescribe reenvíos (dominios locales excluidos)"
exit 0
