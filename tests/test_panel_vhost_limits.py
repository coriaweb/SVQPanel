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


def test_idempotente():
    once = patch_panel_vhost(VHOST)
    assert patch_panel_vhost(once) == once


def test_respeta_valor_puesto_a_mano():
    manual = VHOST.replace("server_name panel.ejemplo.com _;",
                           "server_name panel.ejemplo.com _;\n    client_max_body_size 2g;")
    out = patch_panel_vhost(manual)
    assert "client_max_body_size 2g;" in out
    assert out.count("client_max_body_size") == 1
