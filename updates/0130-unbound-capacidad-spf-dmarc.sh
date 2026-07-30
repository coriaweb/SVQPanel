#!/bin/bash
# 0130-unbound-capacidad-spf-dmarc.sh
#
# El antispam dejaba pasar correo con el remitente FALSIFICADO del propio
# dominio (sextorsión "from: tu_email → to: tu_email").
#
# Causa: unbound (el resolver de Rspamd, update 0061) quedó con la config por
# defecto: 1 hilo y cola de 64 peticiones. En una ráfaga de spam la cola se
# desborda y descarta consultas — medido en un servidor real:
# `total.requestlist.exceeded=1445`.
#
# Cuando eso pasa, Rspamd NO obtiene las respuestas de SPF/DMARC/RBL y puntúa
# el correo como si esos checks no existieran. Caso real observado:
#   - Ese correo:            2 consultas DNS, 8.013 ms → score 6.15  → ENTREGADO
#   - Otros de la misma      23-32 consultas,   76 ms → score 24-33 → RECHAZADO
#     campaña (mismo bitcoin)
# El dominio tenía SPF "-all" y DMARC "p=quarantine": debía rechazarse.
#
# Además Rspamd tenía `timeout = 1s` con 5 reintentos, demasiado justo: si
# unbound tarda (caché fría), abandona y evalúa sin SPF/DMARC/RBL — que es
# justo lo que deja pasar el spoofing.
#
# Idempotente y no interactivo. Solo actúa si Rspamd y unbound están instalados.

set -u

echo "→ 0130: capacidad de unbound + timeouts DNS de Rspamd…"

if ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0130: Rspamd no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

if ! command -v unbound >/dev/null 2>&1; then
    echo "✓ 0130: unbound no instalado; lo instalará el 0061. Nada que hacer"
    exit 0
fi

UNBOUND_CONF=/etc/unbound/unbound.conf.d/svqpanel.conf

# num-threads acorde a la máquina (mínimo 2: con 1 hilo la cola se satura).
CORES=$(nproc 2>/dev/null || echo 2)
THREADS=2
[ "$CORES" -ge 4 ] && THREADS=4

cat > "$UNBOUND_CONF" << UNBOUNDEOF
# SVQPanel — resolver recursivo cacheante SOLO localhost para Rspamd (antispam).
# Puerto 5353 para no chocar con named (DNS autoritativo del cluster en :53).
# NO es open resolver: solo escucha y atiende a 127.0.0.1/::1.
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
    # ── Capacidad ─────────────────────────────────────────────────────────
    # Con los valores por defecto (1 hilo, cola de 64) una ráfaga de spam
    # satura la cola: unbound descarta consultas, Rspamd se queda SIN las
    # respuestas de SPF/DMARC/RBL y puntúa el correo como si no existieran.
    # Vigilar con: unbound-control stats | grep requestlist.exceeded
    num-threads: ${THREADS}
    msg-cache-size: 64m
    rrset-cache-size: 128m
    key-cache-size: 32m
    num-queries-per-thread: 2048
    outgoing-range: 4096
    so-rcvbuf: 4m
    so-sndbuf: 4m
    # Servir del cache mientras se refresca (evita esperas en picos)
    serve-expired: yes
    serve-expired-ttl: 60
    infra-cache-numhosts: 100000
UNBOUNDEOF

# Validar ANTES de reiniciar: una config inválida dejaría al antispam sin
# resolver, que es peor que el problema que arreglamos.
if ! unbound-checkconf >/dev/null 2>&1; then
    echo "✗ 0130: la config de unbound no valida; revirtiendo"
    unbound-checkconf 2>&1 | head -5
    cat > "$UNBOUND_CONF" << 'UNBOUNDFALLBACK'
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
UNBOUNDFALLBACK
    systemctl restart unbound 2>/dev/null || true
    exit 1
fi

systemctl restart unbound 2>/dev/null || true
echo "  · unbound: ${THREADS} hilos, cola 2048/hilo, cache 64m/128m"

# Rspamd: más margen por consulta y menos reintentos (1s x5 era demasiado
# justo; con 3s x2 el peor caso es parecido pero cada intento sí da tiempo).
cat > /etc/rspamd/local.d/options.inc << 'RSPAMDDNSEOF'
dns {
  nameserver = ["127.0.0.1:5353"];
  timeout = 3s;
  sockets = 64;
  retransmits = 2;
}
RSPAMDDNSEOF

systemctl restart rspamd 2>/dev/null || true
echo "  · rspamd: timeout DNS 3s, 64 sockets"

# Comprobación: que el resolver responde de verdad a través de unbound.
sleep 2
if dig +short +time=3 +tries=1 TXT gmail.com @127.0.0.1 -p 5353 2>/dev/null | grep -q 'spf'; then
    echo "✓ 0130: unbound resuelve SPF correctamente"
else
    echo "⚠ 0130: unbound no devolvió el SPF de prueba (revisar 'systemctl status unbound')"
fi

exit 0
