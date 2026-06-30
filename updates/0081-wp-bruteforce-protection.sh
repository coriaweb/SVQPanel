#!/bin/bash
# 0081-wp-bruteforce-protection.sh
#
# Protección anti fuerza bruta de WordPress por dominio (xmlrpc + rate-limit
# wp-login). Desbloqueado por defecto; el cliente lo activa desde el pane
# "Seguridad" de WordPress en la ficha del dominio (con aviso cuando hay ataque).
#
# Este update:
#   1) Crea las columnas domains.xmlrpc_blocked / wp_login_ratelimit si no
#      existen. El ALTER de api/main.py también las crea al arrancar, PERO este
#      update corre ANTES del reinicio del backend y necesita escribir en ellas,
#      así que las garantizamos aquí (idempotente, mismo patrón que 0077).
#   2) Activa la protección (xmlrpc 444 + wp-login 3/min) en los dominios que
#      estaban recibiendo el ataque masivo detectado en la auditoría, EXCEPTO
#      cronicasliterarias.es (se deja desprotegido a propósito para validar el
#      aviso del panel). Solo si el dominio existe en la BD.
#   3) Regenera el vhost de cada dominio protegido vía el código del panel.
#
# Idempotente y no interactivo.

set -u

echo "→ 0081: protección anti fuerza bruta WordPress…"

PSQL="psql -X -q -v ON_ERROR_STOP=1"
DBQ() { sudo -u postgres $PSQL -d panel_db -c "$1"; }

# ── 1. Garantizar columnas ──────────────────────────────────────────────────
DBQ "ALTER TABLE domains ADD COLUMN IF NOT EXISTS xmlrpc_blocked BOOLEAN NOT NULL DEFAULT FALSE;" \
    && echo "  ✓ columna xmlrpc_blocked OK" || { echo "  ✗ no pude crear xmlrpc_blocked"; exit 1; }
DBQ "ALTER TABLE domains ADD COLUMN IF NOT EXISTS wp_login_ratelimit INTEGER NOT NULL DEFAULT 0;" \
    && echo "  ✓ columna wp_login_ratelimit OK" || { echo "  ✗ no pude crear wp_login_ratelimit"; exit 1; }

# ── 2 + 3. Proteger los dominios bajo ataque (menos cronicasliterarias.es) ───
# Lista detectada en la auditoría con ataque masivo. cronicasliterarias.es se
# OMITE adrede para poder ver el aviso del panel.
ATTACKED="ventalachoza.com lionzamar.es belamarestetica.com"

PANEL=/opt/svqpanel
cd "$PANEL" 2>/dev/null || { echo "  · $PANEL no existe; salto activación"; exit 0; }

for D in $ATTACKED; do
    # ¿existe el dominio en la BD?
    EXISTS=$(sudo -u postgres psql -X -tAq -d panel_db \
        -c "SELECT 1 FROM domains WHERE domain_name='$D' LIMIT 1;" 2>/dev/null)
    if [ "$EXISTS" != "1" ]; then
        echo "  · $D no está en la BD; salto"
        continue
    fi
    # Marcar protegido en BD (xmlrpc bloqueado + 3 req/min en wp-login)
    DBQ "UPDATE domains SET xmlrpc_blocked=TRUE, wp_login_ratelimit=3 WHERE domain_name='$D';" >/dev/null
    # Regenerar el vhost vía el código del panel (lee los flags de la BD).
    if [ -x "$PANEL/venv/bin/python" ]; then
        "$PANEL/venv/bin/python" - "$D" <<'PYEOF' && echo "  ✓ $D protegido (xmlrpc 444 + wp-login 3/min)" || echo "  ✗ $D: fallo regenerando vhost"
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()  # registra TODOS los modelos (si no, falla 'ClientDatabase' en relaciones string)
from api.models.models_domain import Domain
from api.models.models_user import User
from scripts.domain_manager import DomainManager
name = sys.argv[1]
db = SessionLocal()
try:
    d = db.query(Domain).filter(Domain.domain_name == name).first()
    if not d:
        sys.exit(1)
    owner = db.query(User).filter(User.id == d.user_id).first()
    if not owner:
        sys.exit(1)
    from scripts import php_ini_manager as phpini
    sock = phpini.pool_socket_path(name) if phpini.has_pool(name) else None
    DomainManager().regenerate_vhost(
        username=owner.username, domain_name=name, php_version=d.php_version,
        ssl_enabled=d.ssl_enabled, ipv6=d.ipv6,
        fastcgi_cache_enabled=d.fastcgi_cache_enabled,
        fastcgi_cache_ttl_minutes=d.fastcgi_cache_ttl_minutes,
        php_socket_override=sock, template_nginx_extra=d.template_nginx_extra,
        custom_nginx_config=d.custom_nginx_config, custom_apache_config=d.custom_apache_config,
        redirect_to=d.redirect_to, custom_docroot=d.custom_docroot, ipv4=d.ipv4,
        force_https=d.force_https or False, hsts=d.hsts_enabled or False,
        rate_limit_enabled=d.rate_limit_enabled or False,
        rate_limit_rps=d.rate_limit_rps or 10, rate_limit_burst=d.rate_limit_burst or 20,
        readonly_mode_enabled=d.readonly_mode_enabled or False,
        allowed_mutation_ips=d.allowed_mutation_ips,
        security_headers_enabled=d.security_headers_enabled or False,
        http3_enabled=d.http3_enabled or False,
        canonical_domain=d.canonical_domain or "www",
        # xmlrpc_blocked / wp_login_ratelimit los lee de la BD
    )
finally:
    db.close()
PYEOF
    fi
done

echo "✓ 0081: protección WordPress aplicada (cronicasliterarias.es queda sin proteger a propósito)"
exit 0
