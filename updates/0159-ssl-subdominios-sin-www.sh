#!/bin/bash
# 0159-ssl-subdominios-sin-www.sh
#
# Los certificados de subdominios llevaban www.<subdominio> y dejaban de renovarse.
#
# El panel añadía www.{dominio} a cualquier cert si resolvía al emitir, también
# en subdominios (comodín DNS o el DNS del hosting anterior en una migración).
# Certbot renueva con la lista de SAN guardada: cuando www.<sub> dejaba de
# existir, la renovación fallaba ENTERA y el cert caducaba (socios.zococoria.es,
# sep 2026). El código ya no lo añade; este update reemite sin él los certs de
# subdominios que lo llevan (api.cli fix_subdomain_www_certs). El vhost de un
# subdominio no sirve www, así que no se pierde nada. Idempotente: un cert sin
# www.<sub> no se toca. Solo código del panel → no requiere cambio en install.sh.

set -u

echo "-> 0159: certificados de subdominios sin www..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0159: sin cambios"
    exit 0
fi

# Si certbot falla con algún cert (DNS que ya no apunta aquí, etc.) NO se aborta
# la cadena: el ssl-check diario seguirá avisando de ese cert.
cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli fix_subdomain_www_certs 2>&1 \
    | grep -v -i deprecat | sed 's/^/  /' || true

echo "OK 0159: certificados de subdominios revisados"
exit 0
