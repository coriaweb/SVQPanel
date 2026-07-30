#!/bin/bash
# 0131-unbound-buffers-y-subnetcache.sh
#
# Remata el 0130. Al revisar los logs de unbound DESPUÉS de aplicarlo, dos de
# las opciones que puso no estaban surtiendo efecto:
#
# 1) "so-rcvbuf 4194304 was not granted. Got 425984"
#    Los buffers de socket los limita el kernel (net.core.rmem_max/wmem_max,
#    por defecto 212992 = 208k). unbound pedía 4m y se quedaba en ~416k. Justo
#    los buffers son lo que amortigua las RÁFAGAS de consultas, que es el caso
#    que provocó el bug original (spam masivo → cola desbordada → correo
#    evaluado sin SPF/DMARC).
#
# 2) "subnetcache: serve-expired is set but not working"
#    "subnetcache: prefetch is set but not working"
#    Debian activa el módulo subnetcache (EDNS Client Subnet) por defecto y
#    ANULA serve-expired y prefetch para los datos que él cachea — las dos
#    opciones que evitan esperas en los picos. Ese módulo sirve para DNS con
#    respuestas por geolocalización; aquí es un resolver LOCAL para el
#    antispam, así que sobra.
#
# Idempotente y no interactivo. Reutiliza el 0130 (que ya es idempotente) para
# no duplicar la config: este update solo añade el sysctl y relanza el 0130.

set -u

echo "→ 0131: buffers de socket y module-config de unbound…"

if ! command -v unbound >/dev/null 2>&1; then
    echo "✓ 0131: unbound no instalado; nada que hacer"
    exit 0
fi

# 1) Buffers del kernel (persistente).
cat > /etc/sysctl.d/99-svqpanel-unbound.conf << 'SYSCTLEOF'
# SVQPanel — buffers de socket para unbound (resolver del antispam).
# Sin esto el kernel recorta el so-rcvbuf/so-sndbuf que pide unbound y las
# ráfagas de consultas DNS se pierden (ver updates 0130 y 0131).
net.core.rmem_max = 4194304
net.core.wmem_max = 4194304
SYSCTLEOF
sysctl -p /etc/sysctl.d/99-svqpanel-unbound.conf >/dev/null 2>&1 || true
echo "  · net.core.rmem_max/wmem_max = 4m"

# 2) Reaplicar el 0130, que ya escribe la config con module-config correcto.
#    Es idempotente: reescribe el fichero, valida y reinicia.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SELF_DIR/0130-unbound-capacidad-spf-dmarc.sh" ]; then
    bash "$SELF_DIR/0130-unbound-capacidad-spf-dmarc.sh" || exit 1
else
    echo "⚠ 0131: no se encontró el 0130; nada que reaplicar"
    exit 0
fi

# Verificación: que los avisos hayan desaparecido de verdad.
sleep 2
if journalctl -u unbound --since '1 min ago' --no-pager 2>/dev/null | grep -q 'was not granted'; then
    echo "⚠ 0131: unbound sigue sin obtener los buffers (revisar sysctl)"
else
    echo "✓ 0131: buffers concedidos"
fi

if unbound-control -c /etc/unbound/unbound.conf get_option module-config 2>/dev/null | grep -q subnetcache; then
    echo "⚠ 0131: subnetcache sigue activo (serve-expired/prefetch limitados)"
else
    echo "✓ 0131: subnetcache desactivado (serve-expired y prefetch operativos)"
fi

exit 0
