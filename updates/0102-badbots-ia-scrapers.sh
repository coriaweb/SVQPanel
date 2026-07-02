#!/bin/bash
# 0102-badbots-ia-scrapers.sh
#
# Añade al bloqueo de bad-bots varios scrapers de IA/SEO agresivos que estaban
# pasando sin bloquear y generaban carga (cientos de hits/día por dominio):
#   meta-externalagent (IA de Meta), PerplexityBot, DataForSeoBot, Scrapy,
#   Timpibot, Bytedance.
#
# IMPORTANTE: NO se bloquean Applebot ni facebookexternalhit a propósito:
#   - Applebot: buscador de Apple (Siri/Spotlight) → bloquearlo daña el SEO.
#   - facebookexternalhit: genera las PREVIEWS al compartir en WhatsApp/FB/IG →
#     bloquearlo rompería las campañas en redes (una tienda vive de eso).
#   (meta-externalagent es el scraper de IA de Meta, distinto de facebookexternalhit.)
#
# Usa ensure_catalog_bots_blocked() del panel: activa solo estos IDs preservando
# los que el admin ya tuviera marcados. Idempotente.

set -u

echo "→ 0090: bloquear scrapers de IA/SEO agresivos (meta-externalagent, Perplexity, DataForSeo, Scrapy…)…"

PANEL=/opt/svqpanel
if [ ! -x "$PANEL/venv/bin/python" ]; then
    echo "  · venv del panel no encontrado; nada que hacer"
    exit 0
fi

"$PANEL/venv/bin/python" - <<'PYEOF'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from scripts.bad_bots_manager import ensure_catalog_bots_blocked
except Exception as e:
    print(f"  · no pude importar bad_bots_manager: {e}")
    sys.exit(0)

NUEVOS = ["meta_ai", "perplexitybot", "dataforseo", "scrapy", "timpibot", "bytedance"]
res = ensure_catalog_bots_blocked(NUEVOS)
added = res.get("added", [])
if added:
    print(f"  ✓ activados: {', '.join(added)} (total patrones: {res.get('blocked_count')})")
else:
    print("  · ya estaban todos activados")
PYEOF

echo "✓ 0090: scrapers de IA/SEO bloqueados (Applebot y facebookexternalhit intactos)"
exit 0
