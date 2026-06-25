#!/bin/bash
# 0048-goaccess-spanish-locale.sh
#
# Genera el locale es_ES.UTF-8 para que los informes de GoAccess (estadísticas
# de dominio) salgan EN ESPAÑOL. La traducción (goaccess.mo) ya viene con el
# paquete; solo faltaba el locale del sistema. Separado del 0047 porque ese ya
# está aplicado en servidores existentes. Idempotente.

set -euo pipefail

echo "→ 0048: informes de GoAccess en español (locale es_ES.UTF-8)…"

if locale -a 2>/dev/null | grep -qiE "^es_ES\.(utf8|UTF-8)$"; then
    echo "  locale es_ES.UTF-8 ya disponible."
    exit 0
fi

grep -q "^es_ES.UTF-8" /etc/locale.gen 2>/dev/null || echo "es_ES.UTF-8 UTF-8" >> /etc/locale.gen
if locale-gen es_ES.UTF-8 >/dev/null 2>&1; then
    echo "  ✓ locale es_ES.UTF-8 generado"
else
    echo "  ⚠ no se pudo generar el locale (el informe quedará en inglés)."
fi

echo "✓ 0048: locale español listo"
exit 0
