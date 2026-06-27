#!/bin/bash
# 0061-unbound-resolver-rspamd.sh
#
# Arregla el antispam: Rspamd no podía resolver DNS (SPF, DKIM, DMARC, listas
# negras RBL) porque usaba 127.0.0.1:53 = el 'named' del cluster DNS, que es
# AUTORITATIVO con 'recursion no' y rechaza dominios externos (REFUSED). Eso
# tumbaba SPF/DKIM/DMARC/RBL en TODO el correo desde que se montó el cluster.
#
# Solución: unbound como resolver recursivo cacheante SOLO en localhost:5353
# (NO es open resolver: no escucha en la IP pública) y apuntar Rspamd ahí.
#
# Idempotente y no interactivo. Solo actúa si Rspamd está instalado.

set -u

echo "→ 0061: resolver DNS propio (unbound) para el antispam…"

if ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0061: Rspamd no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

# 1) Instalar unbound (idempotente).
if ! command -v unbound-checkconf >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unbound 2>/dev/null || {
        echo "  ⚠ no se pudo instalar unbound"; exit 0; }
fi
# Que unbound NO toque el resolver del SO.
systemctl disable unbound-resolvconf 2>/dev/null || true
systemctl stop unbound-resolvconf 2>/dev/null || true

# 2) Config solo-local en 5353 (no choca con named :53; no open resolver).
cat > /etc/unbound/unbound.conf.d/svqpanel.conf << 'UNBOUNDEOF'
# SVQPanel — resolver recursivo cacheante SOLO localhost para Rspamd (antispam).
# Puerto 5353 para no chocar con named (DNS autoritativo del cluster en :53).
server:
    port: 5353
    interface: 127.0.0.1@5353
    interface: ::1@5353
    access-control: 127.0.0.0/8 allow
    access-control: ::1 allow
    do-ip6: yes
    prefetch: yes
    cache-min-ttl: 60
    cache-max-ttl: 86400
    hide-identity: yes
    hide-version: yes
UNBOUNDEOF

if ! unbound-checkconf >/dev/null 2>&1; then
    echo "  ⚠ config unbound inválida; abortando sin tocar Rspamd"
    exit 0
fi
systemctl enable unbound 2>/dev/null || true
systemctl restart unbound 2>/dev/null || true
sleep 2

# 3) Comprobar que unbound resuelve externo ANTES de reapuntar Rspamd (seguridad:
#    si unbound no funciona, NO dejar a Rspamd sin DNS).
if ! dig @127.0.0.1 -p 5353 google.com A +short +time=3 +tries=1 >/dev/null 2>&1; then
    echo "  ⚠ unbound no resuelve; NO reapunto Rspamd (sigue como estaba)"
    exit 0
fi

# 4) Apuntar Rspamd a unbound.
cat > /etc/rspamd/local.d/options.inc << 'RSPAMDDNSEOF'
dns {
  nameserver = ["127.0.0.1:5353"];
  timeout = 1s;
  sockets = 16;
  retransmits = 5;
}
RSPAMDDNSEOF
systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true

echo "✓ 0061: Rspamd resuelve DNS vía unbound (SPF/DKIM/DMARC/RBL reactivados)"
exit 0
