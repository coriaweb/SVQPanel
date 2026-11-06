#!/bin/bash
# 0177-php-ini-global-versiones-panel.sh
#
# Las versiones de PHP instaladas DESDE EL PANEL nacían con el php.ini de
# Debian (subida 2M, POST 8M, 30 s, OPcache sin dimensionar): la política del
# panel (php_manager._apply_global_ini_policy) se había quedado en
# `memory_limit = 256M` mientras install.sh aplicaba 512M / 64M / 64M / 120 s.
# Visto en .223: su PHP 8.3 (10 webs) no dejaba subir más de 2 MB ni pedir más
# por dominio ("no puedes superar el límite del servidor").
#
# Fix (código del panel, `api.cli php_global_policy`): aplica a TODAS las
# versiones instaladas la misma política que install.sh. Solo SUBE valores
# (respeta lo que se haya subido a mano), crea el OPcache/APCu-CLI si faltan,
# valida con php-fpm -t y recarga solo las versiones que cambian. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && ls /etc/php/*/fpm/php.ini >/dev/null 2>&1; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli php_global_policy \
      && echo "✓ 0177: php.ini global de todas las versiones con los techos del panel" \
      || echo "⚠ 0177: no se pudo aplicar la política del php.ini global"
fi
exit 0
