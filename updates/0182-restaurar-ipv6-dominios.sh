#!/bin/bash
# 0182-restaurar-ipv6-dominios.sh
#
# Vuelve a poner en la interfaz las IPv6 de dominios que faltan.
#
# Un subdominio comparte la IPv6 de su dominio padre. Al borrar el subdominio,
# el panel quitaba esa IPv6 de la interfaz (y del drop-in de networkd) sin
# mirar que el padre la seguía usando: la web del padre dejaba de responder por
# IPv6 y el SSL de sus alias fallaba (Let's Encrypt prueba también por IPv6).
# Caso: applicaabogados.com (.71), 23 nov 2026.
#
# El fix de código (scripts/ipv6_manager.release_ipv6_if_unused) evita que se
# repita; este update repara los servidores ya afectados con
# `api.cli restore_domain_ipv6`, que solo añade las IPv6 de la BD que no están
# en la interfaz. Es un backfill de datos: no hace falta nada en install.sh.
# Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli restore_domain_ipv6 \
      && echo "✓ 0182: IPv6 de dominios revisadas" \
      || echo "⚠ 0182: no se pudieron revisar las IPv6 de dominios"
fi
exit 0
