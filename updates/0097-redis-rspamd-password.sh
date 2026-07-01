#!/bin/bash
# 0097-redis-rspamd-password.sh
#
# SEGURIDAD: protege el Redis global (backend de Rspamd: Bayes, greylisting,
# rate-limit de correo) con contraseña (requirepass).
#
# Hasta ahora escuchaba en 127.0.0.1:6379 SIN contraseña. disable_functions
# bloquea exec/system pero NO sockets TCP, así que el PHP de cualquier cliente
# (p. ej. con Predis, sin extensión) podía conectarse y hacer FLUSHALL: borrar
# el Bayes entrenado, el greylisting o vaciar su propio contador de rate-limit
# de envío (saltarse el límite antispam de salida).
#
# Invoca el código del panel (api.cli secure_rspamd_redis, idempotente):
#   - genera/reutiliza la clave en /etc/svqpanel/redis_rspamd.pass (root 600)
#   - añade requirepass a /etc/redis/redis.conf (bloque gestionado)
#   - la propaga a /etc/rspamd/local.d/redis.conf
#   - reinicia redis-server y rspamd, y verifica (sin clave rechaza / con clave PONG)
# En servidores sin stack de correo no hace nada.

set -euo pipefail

echo "→ 0097: proteger el Redis de Rspamd con contraseña…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli secure_rspamd_redis || {
    echo "  ⚠ secure_rspamd_redis devolvió error (no crítico)."
    exit 0
}

echo "✓ 0097: Redis de Rspamd protegido"
exit 0
