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
# TLS endurecido (NCSC-NL): cifrados modernos AEAD + prefer_server_ciphers
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_ssl_cifrados_modernos():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3", ssl_enabled=True)
    # Debe imponer su orden de cifrados
    assert "ssl_prefer_server_ciphers on;" in cfg
    # Debe ofrecer cifrados AEAD modernos
    assert "ECDHE-ECDSA-CHACHA20-POLY1305" in cfg
    assert "ECDHE-RSA-AES256-GCM-SHA384" in cfg
    # NO debe usar la lista antigua y permisiva
    assert "HIGH:!aNULL:!MD5" not in cfg
    # La línea de cifrados NO debe contener débiles (CBC/Camellia/ARIA/CCM_8).
    # Comprobamos SOLO la línea ssl_ciphers (no todo el vhost: "ARIA" aparece como
    # substring en comentarios tipo "vARIAble").
    cipher_line = next(l for l in cfg.splitlines() if "ssl_ciphers" in l).upper()
    for weak in ("CBC", "CAMELLIA", "ARIA", "CCM"):
        assert weak not in cipher_line, f"cifrado débil {weak} en la lista"
    # Algoritmos de firma TLS 1.2: solo SHA-256/384/512 (sin SHA-224 ni SHA-1).
    assert "ssl_conf_command SignatureAlgorithms" in cfg
    sign_line = next(l for l in cfg.splitlines() if "SignatureAlgorithms" in l)
    assert "SHA256" in sign_line and "SHA384" in sign_line
    assert "SHA224" not in sign_line and "SHA1" not in sign_line


# ─────────────────────────────────────────────────────────────────────────────
# SSL: cuando está activo, debe haber bloque 443
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_ssl_genera_bloque_443():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ssl_enabled=True)
    assert "listen 443 ssl" in cfg
    assert "ssl_certificate" in cfg


# ─────────────────────────────────────────────────────────────────────────────
# HTTP/3 (QUIC): el listen quic NUNCA debe llevar `reuseport`. reuseport solo
# puede aparecer una vez por puerto en TODA la config; ponerlo en cada vhost hace
# que el SEGUNDO dominio con HTTP/3 reviente nginx con "duplicate listen options
# for 0.0.0.0:443" y bloquee todos los reloads (rompió migraciones en prod).
# ─────────────────────────────────────────────────────────────────────────────
def test_nginx_http3_no_lleva_reuseport():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3",
                                ssl_enabled=True, http3_enabled=True,
                                ipv6="2001:db8::1")
    assert "listen 443 quic;" in cfg, "debe declarar el listen quic de HTTP/3"
    assert "reuseport" not in cfg, \
        "el listen quic NO debe llevar reuseport (rompe el 2º vhost con HTTP/3)"
    # El Alt-Svc anuncia HTTP/3 al navegador.
    assert 'Alt-Svc' in cfg


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


# ─────────────────────────────────────────────────────────────────────────────
# Coherencia de firmas: los wrappers que delegan en regenerate_vhost deben
# aceptar los mismos kwargs que se les pasan desde las rutas. Caza el bug
# "got an unexpected keyword argument 'canonical_domain'" al activar FastCGI
# cache (set_fastcgi_cache no propagaba canonical_domain a regenerate_vhost).
# ─────────────────────────────────────────────────────────────────────────────
import inspect
from scripts.domain_manager import DomainManager


def test_set_fastcgi_cache_acepta_canonical_domain():
    params = inspect.signature(DomainManager.set_fastcgi_cache).parameters
    assert "canonical_domain" in params, \
        "set_fastcgi_cache debe aceptar canonical_domain (lo pasa la ruta)"


def test_set_fastcgi_cache_kwargs_son_subconjunto_de_regenerate_vhost():
    # Todo kwarg con default de set_fastcgi_cache (salvo los propios de cache)
    # debe existir en regenerate_vhost, o el passthrough peta en runtime.
    fc = inspect.signature(DomainManager.set_fastcgi_cache).parameters
    rv = set(inspect.signature(DomainManager.regenerate_vhost).parameters)
    propios = {"self", "username", "domain_name", "php_version",
               "enabled", "ttl_minutes"}
    for name in fc:
        if name in propios:
            continue
        assert name in rv, f"set_fastcgi_cache pasa '{name}' pero regenerate_vhost no lo acepta"


# ─────────────────────────────────────────────────────────────────────────────
# El bloque SSL debe pasar HTTPS a PHP-FPM. Sin "fastcgi_param HTTPS on",
# WordPress (y otras apps) detectan $_SERVER['HTTPS'] vacío tras la terminación
# SSL de nginx y redirigen a HTTPS en bucle → ERR_TOO_MANY_REDIRECTS.
# ─────────────────────────────────────────────────────────────────────────────
def test_vhost_ssl_pasa_https_a_php():
    cfg = generate_nginx_config("ejemplo.com", "user1", "8.3", ssl_enabled=True)
    # En el bloque SSL (location php del 443) debe ir el fastcgi_param HTTPS on.
    assert "fastcgi_param HTTPS on" in cfg, \
        "el vhost SSL debe pasar HTTPS a PHP-FPM (evita bucle de redirección)"


# ─────────────────────────────────────────────────────────────────────────────
# El vhost de Apache debe apuntar al MISMO socket PHP-FPM que crea el pool real
# (/run/php/svqpanel-{domain}.sock). Un patrón distinto deja Apache apuntando a
# un socket inexistente → 503.
# ─────────────────────────────────────────────────────────────────────────────
def test_apache_vhost_socket_php_correcto():
    vhost = generate_apache_vhost("ejemplo.com", "user1", "8.4")
    assert "/run/php/svqpanel-ejemplo.com.sock" in vhost, \
        "el vhost Apache debe usar el socket real del pool (svqpanel-{domain}.sock)"
    # NO debe usar el patrón viejo inventado.
    assert "php8.4-fpm-svqpanel" not in vhost


# ─────────────────────────────────────────────────────────────────────────────
# El vhost Apache debe poner index.php ANTES de index.html en DirectoryIndex.
# El global de Debian pone .html primero → un sitio con ambos serviría el .html
# en vez de la app PHP.
# ─────────────────────────────────────────────────────────────────────────────
def test_apache_vhost_directoryindex_php_primero():
    vhost = generate_apache_vhost("ejemplo.com", "user1", "8.3")
    # Buscar la DIRECTIVA real (línea que empieza por DirectoryIndex), no el
    # comentario que la menciona.
    di = next((l for l in vhost.splitlines()
               if l.strip().startswith("DirectoryIndex")), None)
    assert di is not None, "falta la directiva DirectoryIndex en el vhost Apache"
    assert di.index("index.php") < di.index("index.html"), \
        "index.php debe ir antes que index.html en DirectoryIndex"
