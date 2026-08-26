#!/bin/bash
# 0144-sync-php-wp-cron.sh
#
# Sincroniza la versión de PHP de los wp-cron con la del dominio.
#
# El comando del CronJob de wp-cron se construye UNA VEZ, al optimizarlo
# (wp_cron_command usa domain.php_version). Si después se cambiaba el PHP del
# dominio, NADIE actualizaba el cron: se quedaba con la versión vieja. Y si esa
# versión ya no cumple el mínimo de WordPress, el cron falla en cada ejecución
# → el wp-cron del sitio deja de correr EN SILENCIO (con DISABLE_WP_CRON=true
# tampoco hay disparo por visitas que lo salve) y, de paso, cron envía el error
# por correo cada 10 min y la cola de Postfix crece sin parar.
#
# Caso real en el .71: pacobasallote.com tenía el dominio en PHP 8.4 y el cron
# en php7.3 → "WordPress requires at least 7.4", 35 tareas atascadas y 62
# correos encolados. sonibel.es estaba en php8.2 con el dominio en 8.5.
#
# El fix de código (sync_wp_cron_php, llamado al cambiar el PHP) evita que
# vuelva a pasar; este update arregla los que YA están desfasados.
#
# Idempotente y no interactivo: si no hay desfases, no toca nada.

set -u

echo "→ 0144: sincronizar la versión de PHP de los wp-cron…"

PANEL=/opt/svqpanel
PY="$PANEL/venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "  · venv del panel no encontrado; nada que hacer"
    exit 0
fi

cd "$PANEL" || exit 0

"$PY" - <<'PYEOF'
import re
import sys
sys.path.insert(0, "/opt/svqpanel")

from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_cron import CronJob
from api.models.models_domain import Domain
from scripts import wp_manager as wpm

db = SessionLocal()
jobs = db.query(CronJob).filter(CronJob.comment.like("wp-cron:%")).all()
print(f"  {len(jobs)} CronJob de wp-cron")

cambiados = 0
for j in jobs:
    d = db.query(Domain).filter(Domain.id == j.domain_id).first()
    if not d:
        continue
    m = re.match(r"php([\d.]+)\s", j.command or "")
    php_cron = m.group(1) if m else None
    if php_cron == (d.php_version or ""):
        continue
    # sync_wp_cron_php actualiza la BD y regenera la línea del crontab.
    if wpm.sync_wp_cron_php(d, db):
        print(f"  ✓ {d.domain_name}: php{php_cron} → php{d.php_version}")
        cambiados += 1

db.close()
print(f"  {cambiados} wp-cron sincronizado(s)" if cambiados
      else "  · todos los wp-cron ya estaban en la versión correcta")
PYEOF

rc=$?
if [ "$rc" -ne 0 ]; then
    echo "  ✗ falló la sincronización (código $rc)"
    exit 1
fi

echo "✓ 0144: wp-cron sincronizados con el PHP de su dominio"
exit 0
