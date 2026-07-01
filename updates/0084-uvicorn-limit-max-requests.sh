#!/bin/bash
# 0084-uvicorn-limit-max-requests.sh
#
# Sube --limit-max-requests de uvicorn de 500 a 50000 y baja RestartSec de 10 a 2
# en el service de svqpanel.
#
# Problema que arregla: con --limit-max-requests 500 el worker de uvicorn se
# recicla cada 500 peticiones. El dashboard hace polling constante
# (/api/system/stats cada ~15s), así que se llega a 500 en pocos minutos SIN que
# el usuario haga nada. Durante los ~14s del reinicio (RestartSec 10 + arranque)
# el backend no responde en 127.0.0.1:8001 y nginx devuelve HTML: el frontend
# muestra "La API no respondió correctamente (no es JSON)". Aparece
# intermitentemente y "sin hacer nada". El pico real de RAM es ~300M y MemoryMax
# ya cubre cualquier fuga, así que 500 era innecesariamente agresivo. 50000
# recicla cada muchas horas; RestartSec=2 acorta la ventana de caída si ocurre.
#
# Idempotente y no interactivo. Edita el service con sed y recarga systemd.

set -u

echo "→ 0084: uvicorn --limit-max-requests 50000 + RestartSec=2…"

SERVICE=/etc/systemd/system/svqpanel.service

if [ ! -f "$SERVICE" ]; then
    echo "  · $SERVICE no existe; nada que hacer"
    echo "✓ 0084: sin cambios"
    exit 0
fi

CHANGED=0

# 1) --limit-max-requests <N> → 50000 (cualquier valor previo)
if grep -qE -- '--limit-max-requests[[:space:]]+[0-9]+' "$SERVICE"; then
    if ! grep -qE -- '--limit-max-requests[[:space:]]+50000\b' "$SERVICE"; then
        sed -i -E 's/--limit-max-requests[[:space:]]+[0-9]+/--limit-max-requests 50000/' "$SERVICE"
        echo "  ✓ --limit-max-requests → 50000"
        CHANGED=1
    else
        echo "  · --limit-max-requests ya es 50000"
    fi
else
    echo "  · No se encontró --limit-max-requests en ExecStart (¿ExecStart personalizado?); no se toca"
fi

# 2) RestartSec=<N> → 2
if grep -qE '^[[:space:]]*RestartSec=[0-9]+' "$SERVICE"; then
    if ! grep -qE '^[[:space:]]*RestartSec=2[[:space:]]*$' "$SERVICE"; then
        sed -i -E 's/^([[:space:]]*)RestartSec=[0-9]+.*/\1RestartSec=2/' "$SERVICE"
        echo "  ✓ RestartSec → 2"
        CHANGED=1
    else
        echo "  · RestartSec ya es 2"
    fi
else
    echo "  · No hay RestartSec explícito; no se añade"
fi

if [ "$CHANGED" -eq 1 ]; then
    systemctl daemon-reload
    # Reiniciar para aplicar el nuevo ExecStart. Corte de ~2s, aceptable.
    systemctl restart svqpanel >/dev/null 2>&1 || true
    echo "  ✓ systemd recargado y svqpanel reiniciado"
else
    echo "  · Sin cambios; no se reinicia nada"
fi

echo "✓ 0084: límite de reciclado de uvicorn ajustado"
exit 0
