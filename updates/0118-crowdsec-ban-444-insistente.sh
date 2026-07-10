#!/bin/bash
# 0118-crowdsec-ban-444-insistente.sh
#
# Cierra una brecha entre nuestras dos defensas HTTP:
#   - El catalogo de bad-bots de nginx (conf.d/bad-bots.conf) corta a los bots
#     conocidos (Go-http-client, scrapers, etc.) devolviendo 444 (nginx cierra la
#     conexion sin responder: coste infimo, NO llega a PHP).
#   - CrowdSec banea por reputacion... pero sus escenarios http-* miran codigos
#     200/403/404, NO el 444. Resultado: un bot cortado por bad-bots RECIBE 444 y
#     CrowdSec nunca acumula suficientes eventos para escalarlo a ban de firewall,
#     asi que el bot RECONECTA ~1/seg indefinidamente (visto: una IP de AWS con
#     ~2000 hits 444 seguidos a /robots.txt).
#
# Fix: un escenario propio (tipo leaky) que cuenta los 444 por IP y, si una IP
# insiste (muchos 444 en poco tiempo), pide su ban al firewall-bouncer (nftables).
# Asi el bot deja de poder ni abrir conexion TCP, en vez de reconectar sin fin.
# Aplica a TODA la flota (CrowdSec ya lee /home/*/web/*/logs/nginx.access.log).
#
# Umbral: capacity 30, leakspeed 2s -> tolera trafico normal (un 444 aislado por
# un bot puntual se drena), pero una IP que mete >~15 en pocos segundos se banea.
# Idempotente.

set -u

echo "-> 0118: escenario CrowdSec para banear IPs que insisten tras un 444..."

if ! command -v cscli >/dev/null 2>&1; then
    echo "  . cscli no disponible (CrowdSec no instalado); se omite"
    echo "OK 0118: sin cambios"
    exit 0
fi

mkdir -p /etc/crowdsec/scenarios
cat > /etc/crowdsec/scenarios/svqpanel-http-444-flood.yaml << 'CS444EOF'
# SVQPanel — banear IPs que insisten tras ser cortadas con 444 por nginx.
# nginx devuelve 444 (cierra sin responder) a los bad-bots del catalogo; los
# escenarios http-* de CrowdSec NO miran el 444, asi que un bot cortado reconecta
# sin fin. Este escenario cuenta los 444 por IP y banea al que insiste.
type: leaky
name: svqpanel/http-444-flood
description: "IP que recibe muchos 444 (cortada por bad-bots de nginx) y sigue reconectando"
filter: "evt.Meta.log_type in ['http_access-log'] && evt.Meta.http_status == '444'"
groupby: "evt.Meta.source_ip"
capacity: 30
leakspeed: "2s"
blackhole: 5m
labels:
  confidence: 2
  spoofable: 0
  service: http
  behavior: "http:bruteforce"
  label: "Bot insistente cortado con 444"
  remediation: true
CS444EOF

echo "  . escenario svqpanel/http-444-flood escrito"

# Validar config antes de recargar (un YAML malo tumbaria CrowdSec).
if cscli config show >/dev/null 2>&1 && systemctl reload crowdsec >/dev/null 2>&1; then
    echo "  . crowdsec recargado"
else
    systemctl restart crowdsec >/dev/null 2>&1 \
        && echo "  . crowdsec reiniciado" \
        || echo "  ! aviso: no se pudo recargar crowdsec (revisar journalctl -u crowdsec)"
fi

echo "OK 0118: escenario 444-flood instalado"
exit 0
