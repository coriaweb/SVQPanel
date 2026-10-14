#!/bin/bash
# 0166-permissions-policy-self.sh
#
# Permissions-Policy de los "Headers de seguridad" por dominio: cámara,
# micrófono y ubicación pasan de () a (self).
#
# Con () el navegador se los deniega a la PROPIA web sin preguntar al
# visitante: un lector QR (ampaconecta.com, oct 2026), una videollamada o un
# mapa "cerca de mí" fallaban sin remedio desde la aplicación. Con (self) el
# navegador sigue pidiendo permiso y los iframes de terceros siguen bloqueados.
# El generador ya escribe el valor nuevo; esto actualiza los vhosts existentes.
#
# Cambio quirúrgico (solo esa cabecera, no regenera los vhosts). Copia previa y
# si nginx -t falla, se restaura todo. Idempotente. Solo código del panel → no
# requiere cambio en install.sh (un servidor nuevo nace con el valor nuevo).

set -u

echo "-> 0166: Permissions-Policy con camera/microphone/geolocation=(self)..."

DIR=/etc/nginx/sites-available
if [ ! -d "$DIR" ] || ! command -v nginx >/dev/null 2>&1; then
    echo "  . sin nginx; se omite"
    echo "OK 0166: sin cambios"
    exit 0
fi

OLD='accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()'
NEW='accelerometer=(), camera=(self), geolocation=(self), gyroscope=(), magnetometer=(), microphone=(self), payment=(), usb=()'

BK=/var/backups/svqpanel-0166-$(date +%Y%m%d%H%M%S)
changed=()
for f in "$DIR"/*; do
    [ -f "$f" ] || continue
    if grep -qF "$OLD" "$f"; then
        mkdir -p "$BK"
        cp -a "$f" "$BK/"
        # Sin metacaracteres de regex salvo los paréntesis, que en sed básico son literales.
        sed -i "s/$OLD/$NEW/g" "$f"
        changed+=("$f")
    fi
done

if [ ${#changed[@]} -eq 0 ]; then
    echo "OK 0166: ningún vhost con la política antigua"
    exit 0
fi

if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  OK ${#changed[@]} vhost(s) actualizados (copia en $BK)"
else
    echo "  !! nginx -t falla tras el cambio: restaurando los ${#changed[@]} vhost(s)"
    cp -a "$BK"/* "$DIR/"
    nginx -t >/dev/null 2>&1 && systemctl reload nginx
    echo "OK 0166: revertido (revisar a mano; copia en $BK)"
    exit 0
fi

echo "OK 0166: Permissions-Policy actualizada"
exit 0
