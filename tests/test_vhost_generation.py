"""
Tests de generación de vhosts (nginx y Apache).

Estos tests verifican el TEXTO que generan los generadores de configuración, sin
necesidad de un servidor real. Cazan la clase de bug que más nos ha dado guerra:
actualizaciones que rompen la generación de vhosts (proxy a Apache perdido,
IPv6 mal, listen atado a IP, gzip/cache faltante…).

Son funciones puras: dadas las entradas, devuelven texto → fáciles y rápidas de
probar. Si uno de estos falla en CI, significa que un cambio rompió la generación
de configs ANTES de que llegue a producción.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils import generate_nginx_config
from scripts.apache_vhost_generator import generate_apache_vhost


# ─────────────────────────────────────────────────────────────────────────────
# Modo Apache+Nginx: nginx es FRONT y hace proxy_pass a Apache (127.0.0.1:8181)
# (regresión del bug de IPv6 que rompía el proxy en modo Apache)
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_modo_apache_usa_proxy_pass():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                proxy_to_apache=True)
    assert "proxy_pass http://127.0.0.1:8181" in cfg, "modo Apache debe hacer proxy"
    assert "fastcgi_pass" not in cfg, "modo Apache NO debe usar fastcgi_pass"


def test_nginx_modo_apache_con_ipv6_conserva_proxy():
    # Este es EXACTAMENTE el caso del bug: asignar IPv6 en modo Apache.
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                proxy_to_apache=True,
                                ipv6="2001:db8::1")
    assert "proxy_pass http://127.0.0.1:8181" in cfg
    assert "fastcgi_pass" not in cfg
    assert "2001:db8::1" in cfg, "la IPv6 debe ir en server_name"


def test_nginx_modo_puro_usa_fastcgi():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                proxy_to_apache=False)
    assert "fastcgi_pass" in cfg, "modo nginx puro sirve PHP por fastcgi"
    assert "proxy_pass http://127.0.0.1:8181" not in cfg


# ─────────────────────────────────────────────────────────────────────────────
# IPv6 / listen genérico (regresión del bug de listen atado a IP)
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_listen_generico_no_atado_a_ip():
    # El listen debe ser genérico (listen 80 / [::]:80), NO atado a una IP, para
    # no romper el enrutado en servidores de una sola IP.
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ipv4="185.10.10.10")
    assert "listen 80;" in cfg
    assert "listen [::]:80;" in cfg
    assert "listen 185.10.10.10:80" not in cfg, "no atar el listen a la IP"


def test_nginx_ipv6_en_server_name_no_default_server():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ipv6="2001:db8::abcd")
    assert "2001:db8::abcd" in cfg
    # No debe declararse default_server (ese rol es del vhost de bienvenida)
    assert "default_server" not in cfg


# ─────────────────────────────────────────────────────────────────────────────
# server_name siempre incluye el dominio y www
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_server_name_incluye_dominio_y_www():
    cfg = generate_nginx_config("midominio.com", "user1", "8.3")
    assert "server_name" in cfg
    assert "midominio.com" in cfg
    assert "www.midominio.com" in cfg


# ─────────────────────────────────────────────────────────────────────────────
# Cache de estáticos (regresión del bug de gzip/cache faltante en nginx puro)
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_puro_tiene_cache_estaticos():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                proxy_to_apache=False)
    assert "expires 30d" in cfg, "los estáticos deben llevar cache de navegador"


# ─────────────────────────────────────────────────────────────────────────────
# Redirección (vhost que redirige a otra URL)
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_redirect_genera_301():
    cfg = generate_nginx_config("viejo.com", "user1", "8.3",
                                redirect_to="https://nuevo.com")
    assert "return 301" in cfg
    assert "nuevo.com" in cfg


# ─────────────────────────────────────────────────────────────────────────────
# Dominio canónico (www / non-www / none) — redirección 301 a la variante elegida
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_canonical_www_por_defecto_redirige_no_www_a_www():
    # El default del panel es forzar www: dominio.com → www.dominio.com
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3")
    assert "if ($host = ejemplo.com)" in cfg
    assert "return 301 $scheme://www.ejemplo.com$request_uri;" in cfg


def test_nginx_canonical_non_www_redirige_www_a_raiz():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                canonical_domain="non-www")
    assert "if ($host = www.ejemplo.com)" in cfg
    assert "return 301 $scheme://ejemplo.com$request_uri;" in cfg


def test_nginx_canonical_none_no_redirige():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                canonical_domain="none")
    # Sin redirección canónica: no debe haber un if($host=...) de canónico
    assert "Dominio canónico" not in cfg


def test_nginx_canonical_www_tambien_en_bloque_ssl():
    # La redirección canónica debe aplicarse también en el bloque 443.
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ssl_enabled=True, canonical_domain="www")
    # Debe aparecer en el bloque https (busca tras 'listen 443')
    pos_443 = cfg.find("listen 443")
    assert pos_443 != -1
    assert "return 301 $scheme://www.ejemplo.com$request_uri;" in cfg[pos_443:]


# ─────────────────────────────────────────────────────────────────────────────
# SSL: cuando está activo, debe haber bloque 443
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_ssl_genera_bloque_443():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ssl_enabled=True)
    assert "listen 443 ssl" in cfg
    assert "ssl_certificate" in cfg


# ─────────────────────────────────────────────────────────────────────────────
# Apache vhost (modo dual)
# ─────────────────────────────────────────────────────────────────────────────
def test_apache_vhost_documentroot_y_php():
    vhost = generate_apache_vhost("ejemplo.com", "user1", "8.3")
    assert "DocumentRoot" in vhost
    assert "ejemplo.com" in vhost
    # PHP vía PHP-FPM (socket)
    assert "proxy:unix:" in vhost or "SetHandler" in vhost


def test_apache_vhost_cache_estaticos():
    # Regresión del bug: en modo Apache la cache de estáticos la pone Apache.
    vhost = generate_apache_vhost("ejemplo.com", "user1", "8.3")
    assert "mod_expires" in vhost, "Apache debe tener bloque de cache de estáticos"
    assert "ExpiresDefault" in vhost


def test_apache_vhost_protege_ficheros_sensibles():
    vhost = generate_apache_vhost("ejemplo.com", "user1", "8.3")
    # Debe denegar acceso a .env, .git, etc. aunque el .htaccess del cliente no lo haga
    assert "env" in vhost and "git" in vhost
