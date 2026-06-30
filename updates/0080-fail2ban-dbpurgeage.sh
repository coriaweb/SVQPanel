#!/bin/bash
# 0080-fail2ban-dbpurgeage.sh
#
# Sube dbpurgeage de fail2ban a 5 semanas para que el baneo escalado
# (bantime.increment, update 0079) tenga memoria suficiente.
#
# Problema que arregla: fail2ban guarda el historial de reincidencias por IP en
# su SQLite y lo purga cada 'dbpurgeage' (default 1 día). Con maxtime=4w pero
# purge=1d, cada IP se "olvida" en 24h → nunca escala más allá del baneo inicial
# (la reincidencia de pasado mañana vuelve a contar como la primera). 5w > 4w.
#
# Usa fail2ban.local (sobreescribe fail2ban.conf y sobrevive a upgrades del
# paquete). Idempotente y no interactivo.

set -u

echo "→ 0080: fail2ban dbpurgeage = 5w (memoria para el baneo escalado)…"

if ! command -v fail2ban-client >/dev/null 2>&1; then
    echo "  · fail2ban no instalado; nada que hacer"
    echo "✓ 0080: sin cambios"
    exit 0
fi

LOCAL=/etc/fail2ban/fail2ban.local

# Escribir/asegurar dbpurgeage = 5w en [Definition] de fail2ban.local.
if [ -f "$LOCAL" ] && grep -qE '^\s*dbpurgeage\s*=' "$LOCAL"; then
    sed -i -E 's/^\s*dbpurgeage\s*=.*/dbpurgeage = 5w/' "$LOCAL"
    echo "  ✓ dbpurgeage actualizado a 5w en $LOCAL"
elif [ -f "$LOCAL" ] && grep -qE '^\s*\[Definition\]' "$LOCAL"; then
    # Existe [Definition] pero sin dbpurgeage: lo añadimos bajo esa sección.
    sed -i -E '0,/^\s*\[Definition\]\s*$/s//[Definition]\ndbpurgeage = 5w/' "$LOCAL"
    echo "  ✓ dbpurgeage = 5w añadido a $LOCAL"
else
    cat > "$LOCAL" << 'F2BLOCALEOF'
# /etc/fail2ban/fail2ban.local — gestionado por SVQPanel
[Definition]
dbpurgeage = 5w
F2BLOCALEOF
    echo "  ✓ $LOCAL creado con dbpurgeage = 5w"
fi

# Recargar (validando). dbpurgeage se aplica con reload, sin reiniciar bans.
if fail2ban-client -d >/dev/null 2>&1; then
    fail2ban-client reload >/dev/null 2>&1 || systemctl restart fail2ban >/dev/null 2>&1 || true
    EFF=$(fail2ban-client get dbpurgeage 2>/dev/null | grep -oE '[0-9]+seconds' || true)
    echo "  ✓ fail2ban recargado (dbpurgeage efectivo: ${EFF:-?})"
else
    echo "  ✗ fail2ban-client -d falló; revisa $LOCAL (no se recargó)"
fi

echo "✓ 0080: dbpurgeage = 5w aplicado"
exit 0
