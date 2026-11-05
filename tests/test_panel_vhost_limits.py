"""El vhost del panel debe llevar client_max_body_size (si no, 413 a partir de
1 MB en phpMyAdmin) aunque se haya generado sin él."""
from scripts.panel_ssl_manager import patch_panel_vhost, PANEL_UPLOAD_LIMIT

VHOST = """# SVQPanel — vhost SSL generado automáticamente

server {
    listen 443 ssl default_server;
    server_name _;
    location / {
        try_files $uri $uri/ =200;
    }
}

server {
    listen 8083 ssl;
    server_name panel.ejemplo.com _;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /pma/ {
        root /var/www;
        location ~ \\.php$ {
            include snippets/fastcgi-php.conf;
            fastcgi_pass unix:/run/php/php8.5-fpm.sock;
            include fastcgi_params;
        }
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
    }
}
"""


def test_anade_limite_timeout_y_cabeceras_solo_al_server_del_panel():
    out = patch_panel_vhost(VHOST)
    welcome, panel = out.split("listen 8083", 1)
    assert "client_max_body_size" not in welcome
    assert f"client_max_body_size {PANEL_UPLOAD_LIMIT};" in panel
    assert 'add_header X-Content-Type-Options "nosniff" always;' in panel
    assert "fastcgi_read_timeout 600s;" in panel.split("location /api/")[0]
    assert out.count("{") == out.count("}")


def test_pma_sin_cache_y_conserva_cabeceras():
    out = patch_panel_vhost(VHOST)
    pma = out[out.index("location /pma/"):out.index("location /api/")]
    assert "fastcgi_hide_header Cache-Control;" in pma
    assert 'add_header Cache-Control "no-store, no-cache, must-revalidate" always;' in pma
    # add_header en el location anula los del server: tienen que repetirse.
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in pma
    # Y el server sigue teniendo los suyos (no se confunden con los de /pma).
    server = out.replace(pma, "")
    assert server.count('add_header X-Frame-Options') == 1


def test_vhost_ya_parcheado_por_0171_recibe_el_no_cache():
    # Estado tras el 0171: timeout en /pma pero sin el no-cache.
    viejo = VHOST.replace(
        "            include fastcgi_params;\n",
        "            include fastcgi_params;\n            fastcgi_read_timeout 600s;\n")
    nuevo = patch_panel_vhost(viejo)
    assert "fastcgi_hide_header Cache-Control;" in nuevo
    assert nuevo.count("fastcgi_read_timeout") == 1


def test_pma_apunta_a_su_pool_y_vuelve_al_compartido():
    propio = patch_panel_vhost(VHOST, pma_pass="/run/php/svqpanel-pma.sock")
    pma = propio[propio.index("location /pma/"):propio.index("location /api/")]
    assert "fastcgi_pass unix:/run/php/svqpanel-pma.sock;" in pma
    assert "php8.5-fpm.sock" not in pma
    # Pool caído: se devuelve al compartido.
    vuelta = patch_panel_vhost(propio, pma_pass="/run/php/php8.5-fpm.sock")
    assert "svqpanel-pma.sock" not in vuelta
    assert patch_panel_vhost(propio, pma_pass="/run/php/svqpanel-pma.sock") == propio


def test_idempotente():
    once = patch_panel_vhost(VHOST)
    assert patch_panel_vhost(once) == once


def test_respeta_valor_puesto_a_mano():
    manual = VHOST.replace("server_name panel.ejemplo.com _;",
                           "server_name panel.ejemplo.com _;\n    client_max_body_size 2g;")
    out = patch_panel_vhost(manual)
    assert "client_max_body_size 2g;" in out
    assert out.count("client_max_body_size") == 1


# ── Bienvenida (default_server 80/443): el `=200` colgaba las rutas inexistentes ──
WELCOME_443 = """server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name _;
    ssl_certificate     /etc/letsencrypt/live/panel.ejemplo.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/panel.ejemplo.com/privkey.pem;
    root /var/www/html;
    index index.html;
    location / {
        try_files $uri $uri/ =200;
    }
}
"""

WELCOME_80 = """server {
    listen 80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    root /var/www/html;
    location / {
        try_files $uri $uri/ =200;
    }
}
"""


def test_bienvenida_443_redirige_el_hostname_al_panel():
    from scripts.panel_ssl_manager import patch_welcome_fallback, PANEL_WEB_PORT
    out = patch_welcome_fallback(WELCOME_443)
    assert "=200" not in out and "try_files $uri $uri/ =404;" in out
    assert (f"if ($host = panel.ejemplo.com) {{ return 301 https://$host:{PANEL_WEB_PORT}$request_uri; }}"
            in out)
    assert patch_welcome_fallback(out) == out


def test_bienvenida_80_solo_404_y_acme_intacto():
    from scripts.panel_ssl_manager import patch_welcome_fallback
    out = patch_welcome_fallback(WELCOME_80)
    assert "=200" not in out and "=404" in out and "return 301" not in out
    assert "location /.well-known/acme-challenge/ {\n        root /var/www/html;" in out


def test_vhost_del_panel_arregla_tambien_la_bienvenida():
    out = patch_panel_vhost(VHOST + WELCOME_443)
    assert "=200" not in out and "if ($host = panel.ejemplo.com)" in out


def test_plantilla_ssl_sin_200(monkeypatch, tmp_path):
    from scripts import panel_ssl_manager as P
    written = {}
    mgr = P.PanelSSLManager.__new__(P.PanelSSLManager)
    monkeypatch.setattr(mgr, "_write_conf", lambda c: written.setdefault("c", c), raising=False)
    mgr._write_nginx_ssl("panel.ejemplo.com", force_https=True)
    conf = written["c"]
    assert "=200" not in conf and "if ($host = panel.ejemplo.com)" in conf


def test_bienvenida_con_sangria_de_8_espacios():
    """Así está en servidores reales (vhost generado por una plantilla antigua)."""
    from scripts.panel_ssl_manager import patch_welcome_fallback
    viejo = WELCOME_443.replace("    location / {\n", "        location / {\n")
    out = patch_welcome_fallback(viejo)
    assert "=200" not in out and "if ($host = panel.ejemplo.com)" in out
    assert out.count("location / {") == 1
