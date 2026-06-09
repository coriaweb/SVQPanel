#!/bin/bash
# 0016-rspamd-dns-local.sh
#
# Rspamd usaba el resolver del sistema (8.8.8.8 / 1.1.1.1). Las DNSBL
# (Spamhaus/URIBL/dnswl…) BLOQUEAN las consultas desde resolvers públicos
# (devuelven 127.0.0.1 o respuestas falsas → Rspamd marca las listas como
# "dead"), lo que degrada el antispam. Solución: usar el BIND local (127.0.0.1)
# que el panel ya instala para el DNS de los dominios. Idempotente.
#
# Solo actúa si Rspamd está instalado.

set -euo pipefail

echo "→ 0016: Resolver DNS local para Rspamd (DNSBL)..."

if [ ! -d /etc/rspamd ]; then
    echo "  Rspamd no instalado (sin correo) — nada que hacer."
    exit 0
fi

# Comprobar que hay un resolver local en 127.0.0.1:53 (BIND del panel)
if ! ss -lnu 2>/dev/null | grep -q '127.0.0.1:53'; then
    echo "  ⚠ No hay resolver local en 127.0.0.1:53; omito (Rspamd seguirá con el del sistema)."
    exit 0
fi

cat > /etc/rspamd/local.d/options.inc << 'EOF'
dns {
  nameserver = ["127.0.0.1"];
  timeout = 1s;
  sockets = 16;
  retransmits = 5;
}
EOF

if rspamadm configtest >/dev/null 2>&1; then
    systemctl restart rspamd
    sleep 2
    if systemctl is-active --quiet rspamd; then
        echo "  ✓ Rspamd usa el resolver local (127.0.0.1); las DNSBL vuelven a funcionar"
    else
        echo "  ✗ Rspamd no arrancó tras el cambio — revisa: journalctl -u rspamd -n 30"
        exit 1
    fi
else
    echo "  ✗ rspamadm configtest falló; no reinicio Rspamd"
    exit 1
fi

echo "✓ 0016: Resolver DNS local para Rspamd aplicado"
exit 0
