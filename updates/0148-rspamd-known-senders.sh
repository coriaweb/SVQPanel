#!/bin/bash
# 0148-rspamd-known-senders.sh
#
# Activa el módulo known_senders de Rspamd: recuerda a los remitentes con los que
# ya has intercambiado correo y les BAJA la puntuación de spam.
#
# ── QUÉ RESUELVE ──────────────────────────────────────────────────────────────
# Es lo contrario del greylisting que quitamos en el 0146. El greylisting
# PENALIZABA a los desconocidos (y acabó bloqueando correo legítimo con score
# 0.00). known_senders PREMIA a los conocidos: si tu gestoría, tu cliente o tu
# banco ya te han escrito antes, su correo baja de puntuación y es mucho más
# difícil que un falso positivo lo mande a Junk.
#
# Es la forma correcta de reducir falsos positivos: no abre ningún agujero —
# lo peor que puede pasar con un remitente desconocido es que se le juzgue
# exactamente igual que hasta ahora.
#
# ── DECISIÓN DE DISEÑO: NO se activa symbol_unknown ───────────────────────────
# El ejemplo oficial del módulo incluye `symbol_unknown = 'UNKNOWN_SENDER'`, que
# añade puntos a quien escribe por primera vez. NO lo ponemos, a propósito: eso
# es repetir el error del greylisting (castigar a los nuevos) y en un hosting
# compartido el correo de un cliente nuevo, un juzgado o una administración llega
# siempre de un remitente "desconocido". Aquí solo premiamos, nunca penalizamos.
#
# ── PARÁMETROS ────────────────────────────────────────────────────────────────
#   max_senders = 100000  → tope de remitentes recordados (LRU: al llenarse,
#                           descarta los más antiguos). ~100k entradas son unos
#                           pocos MB en Redis.
#   max_ttl     = 30d     → un remitente se "olvida" si no escribe en 30 días.
#   use_bloom   = false   → los filtros bloom necesitan RedisBloom, que no está
#                           instalado. Sin él se usan sets normales, que además
#                           son exactos (sin falsos positivos).
#
# El peso de KNOWN_SENDER se fija en -1.0: suficiente para rescatar correo bueno
# que se quedaba rozando el umbral de Junk (4.0), pero sin llegar a blanquear un
# spam real (que puntúa 6-8) ni tocar el umbral de rechazo (10).
#
# ── REQUISITOS (verificados en producción antes de escribir esto) ─────────────
#   · Rspamd 4.1.1 (el módulo existe desde 2.x)         ✔
#   · Redis con password, ya usado por Bayes/fuzzy      ✔ (6,25 MB en uso)
#
# Idempotente y no interactivo.
set -e

CONF=/etc/rspamd/local.d/known_senders.conf
GROUPS=/etc/rspamd/local.d/groups.conf

echo "→ 0148: activar known_senders (premiar remitentes conocidos)…"

if [ ! -d /etc/rspamd ]; then
    echo "  · Rspamd no instalado; nada que hacer"
    exit 0
fi

# Necesita Redis configurado: sin él el módulo no puede guardar nada.
if [ ! -f /etc/rspamd/local.d/redis.conf ]; then
    echo "  · sin redis.conf en Rspamd; nada que hacer"
    exit 0
fi

# ── 1) Config del módulo ──────────────────────────────────────────────────────
if [ -f "$CONF" ] && grep -q 'SVQPanel' "$CONF"; then
    echo "  · known_senders.conf ya existe (se refresca)"
    cp -a "$CONF" "${CONF}.bak-0148-$(date +%Y%m%d%H%M%S)"
fi

cat > "$CONF" << 'KSEOF'
# SVQPanel — known_senders. NO editar manualmente.
#
# Recuerda a los remitentes con los que ya se ha intercambiado correo y les baja
# la puntuación (símbolo KNOWN_SENDER, peso negativo en groups.conf).
#
# ⚠️ A PROPÓSITO no se define symbol_unknown: penalizar a quien escribe por
# primera vez es el error del greylisting (ver update 0146). Aquí solo se premia
# a los conocidos; a los demás se les juzga igual que siempre.
enabled = true;
max_senders = 100000;
max_ttl = 30d;
use_bloom = false;
KSEOF
chmod 644 "$CONF"
echo "  · known_senders.conf escrito"

# ── 2) Peso del símbolo ───────────────────────────────────────────────────────
# groups.conf puede tener ya otros símbolos del panel: solo añadimos el nuestro
# si no está, sin tocar el resto.
if [ -f "$GROUPS" ] && grep -q 'KNOWN_SENDER' "$GROUPS"; then
    echo "  · el peso de KNOWN_SENDER ya estaba definido"
else
    [ -f "$GROUPS" ] && cp -a "$GROUPS" "${GROUPS}.bak-0148-$(date +%Y%m%d%H%M%S)"
    cat >> "$GROUPS" << 'GRPEOF'

# ── SVQPanel: known_senders (update 0148) ──
# -1.0 rescata correo legítimo que rozaba el umbral de Junk (4.0) sin llegar a
# blanquear spam real (6-8) ni afectar al umbral de rechazo (10).
group "known_senders" {
    symbols {
        "KNOWN_SENDER" {
            weight = -1.0;
            description = "Remitente con el que ya se ha intercambiado correo";
        }
    }
}
GRPEOF
    echo "  · peso KNOWN_SENDER = -1.0 añadido a groups.conf"
fi

# ── 3) Recargar y verificar que el módulo queda activo ────────────────────────
if systemctl is-active --quiet rspamd 2>/dev/null; then
    systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true
    sleep 2
    if ! systemctl is-active --quiet rspamd; then
        echo "  ✗ Rspamd no quedó activo tras recargar; revirtiendo"
        rm -f "$CONF"
        systemctl restart rspamd 2>/dev/null || true
        exit 1
    fi
    # Comprobar de verdad que Rspamd lo ha cargado (no fiarse del reload).
    if rspamadm configdump -m 2>/dev/null | grep -q 'Modules enabled:.*known_senders'; then
        echo "  ✓ módulo known_senders CARGADO"
    else
        echo "  ⚠ Rspamd recargó pero known_senders no aparece como activo"
    fi
fi

echo "✓ 0148: known_senders activo (premia conocidos, no penaliza desconocidos)"
exit 0
