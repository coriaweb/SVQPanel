#!/bin/bash
# 0115-php-execution-time-cap-120.sh
#
# Sube el techo global de max_execution_time (y max_input_time) de PHP de 30s a
# 120s en todas las versiones de PHP-FPM instaladas. Es el CAP: el maximo que el
# panel permite pedir a un dominio via override (php_ini_manager valida contra el
# php.ini global).
#
# Motivo: el editor de Elementor (con packs de widgets: Elementor Pro, Ultimate
# Elementor...) tarda a veces >30s en cargar. Con max_execution_time=30 el proceso
# PHP se mata a mitad de carga -> el editor se queda "cargando" indefinidamente y
# ofrece el "modo seguro". 120s le da margen para terminar. nginx (proxy_read_timeout
# 300) y Apache (Timeout 300) ya cubren estos 120s, no cortan antes.
#
# NO baja el valor si el admin ya lo tenia mas alto (>=120 o 0=ilimitado).
# Idempotente y no interactivo.

set -u

echo "-> 0115: techo global de max_execution_time de PHP -> 120s..."

CHANGED=0
for f in /etc/php/*/fpm/php.ini; do
    [ -f "$f" ] || continue
    for KEY in max_execution_time max_input_time; do
        CUR="$(grep -E "^\s*${KEY}\s*=" "$f" | head -1 | sed -E 's/.*=\s*//; s/\s//g')"
        # 0 = ilimitado en PHP: se respeta. Valor >=120: se respeta.
        if [ "$CUR" = "0" ]; then
            echo "  . $f [$KEY]=0 (ilimitado), se respeta"
            continue
        fi
        if [ "$CUR" -ge 120 ] 2>/dev/null; then
            echo "  . $f [$KEY]=$CUR (>=120), se respeta"
            continue
        fi
        sed -i -E "s/^\s*${KEY}\s*=.*/${KEY} = 120/" "$f"
        echo "  . $f [$KEY] $CUR -> 120"
        CHANGED=1
    done
done

if [ "$CHANGED" = "1" ]; then
    for v in 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5; do
        systemctl reload "php${v}-fpm" >/dev/null 2>&1 && echo "  . php${v}-fpm recargado"
    done
fi

echo "OK 0115: techo de max_execution_time de PHP en 120s"
exit 0
