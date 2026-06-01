"""
TemplateManager — Aplica plantillas web a dominios.

Cuando se aplica una plantilla a un dominio:
  1. Se guarda el nginx_extra y php_ini_overrides de la plantilla en el dominio
  2. Se regenera el vhost nginx del dominio (incluyendo el nginx_extra)
  3. Si la plantilla tiene php_ini_overrides, se crea/actualiza el pool PHP-FPM
     dedicado del dominio (igual que el sistema de php.ini overrides existente)
  4. Si fastcgi_cache_default es True (y no se anuló), se activa la caché
  5. Se hace reload de nginx

El nginx_extra se inyecta DENTRO del bloque server {}, antes del location PHP.
"""

import json
import logging
import os
from typing import Dict, Any, Optional

from scripts.base import SystemManager
from scripts.utils import (
    get_nginx_config_path,
    get_public_html,
    get_domain_logs,
    reload_nginx,
    generate_nginx_config,
    write_fastcgi_cache_zone,
    remove_fastcgi_cache_zone,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Plantillas builtin (se insertan en BD en la migración)
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    {
        "name": "WordPress",
        "slug": "wordpress",
        "description": "WordPress y WooCommerce. Caché FastCGI activada, bypass automático para admin/usuarios logueados.",
        "category": "cms",
        "fastcgi_cache_default": True,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
        }),
        "nginx_extra": """
    # ── WordPress — seguridad y rutas sensibles ─────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location = /wp-login.php {
        # Limitar intentos de login (requiere ngx_http_limit_req_module)
        # limit_req zone=login burst=5 nodelay;
        fastcgi_pass $phpfpm_backend;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }

    location ~* /wp-config\.php        { deny all; }
    location ~* /xmlrpc\.php           { deny all; }
    location = /wp-cron.php            { allow 127.0.0.1; deny all; }
    location ~* ^/wp-content/uploads/.*\\.php$ { deny all; }
    location ~* ^/wp-includes/.*\\.php { deny all; return 403; }

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff2|woff|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        log_not_found off;
    }
""",
    },
    {
        "name": "WordPress Multisite",
        "slug": "wordpress-multisite",
        "description": "WordPress Multisite (subdirectorio). Incluye reglas de rewrite para subsitios.",
        "category": "cms",
        "fastcgi_cache_default": True,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
        }),
        "nginx_extra": """
    # ── WordPress Multisite ──────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location ~* /wp-config\.php        { deny all; }
    location ~* /xmlrpc\.php           { deny all; }
    location ~* ^/wp-content/uploads/sites/[0-9]+/.*\\.php$ { deny all; }

    location ~* ^(/[^/]+)?/files/(.*) {
        try_files /wp-content/blogs.dir/$blogid/$uri /wp-includes/ms-files.php?file=$2 =404;
        access_log off; log_not_found off; expires max;
    }
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|woff2)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        log_not_found off;
    }
""",
    },
    {
        "name": "Laravel",
        "slug": "laravel",
        "description": "Laravel (y otros frameworks Symfony-style). Sirve desde /public. Sin caché FastCGI (Laravel gestiona la suya propia).",
        "category": "framework",
        "fastcgi_cache_default": False,
        "docroot_subdir": "public",
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
            "max_execution_time":  "60",
        }),
        "nginx_extra": """
    # ── Laravel ─────────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Bloquear acceso a directorios internos de Laravel
    location ~* ^/storage/.*\\.php$ { deny all; }
    location ~* ^/vendor/.*\\.php$ { deny all; }
    location ~* ^/bootstrap/.*\\.php$ { deny all; }
    location = /artisan { deny all; }
    location ~* /\\.env { deny all; }

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
""",
    },
    {
        "name": "Drupal",
        "slug": "drupal",
        "description": "Drupal 9/10. Incluye reglas de rewrite clean URLs y protección de rutas sensibles.",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
            "max_execution_time":  "180",
        }),
        "nginx_extra": """
    # ── Drupal ─────────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location ~* \\.(txt|log)$           { deny all; }
    location ~* ^/sites/.*/private/     { return 403; }
    location ~* ^/core/authorize\\.php  { return 403; }
    location = /update.php              { allow 127.0.0.1; deny all; }
    location ~* ^/sites/.*/files/styles/ {
        try_files $uri @rewrite;
    }
    location @rewrite {
        rewrite ^/(.*)$ /index.php?q=$1;
    }
    location ~* ^/.+\\.php(/|$) {
        fastcgi_split_path_info ^(.+?\\.php)(/.*)$;
        fastcgi_pass $phpfpm_backend;
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        include fastcgi_params;
    }
""",
    },
    {
        "name": "PrestaShop",
        "slug": "prestashop",
        "description": "PrestaShop. Reglas de rewrite para el módulo de URLs amigables y protección de config.",
        "category": "ecommerce",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "180",
        }),
        "nginx_extra": """
    # ── PrestaShop ──────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;

    location ~* /config/.*\\.inc\\.php$  { deny all; }
    location ~* /app/config/.*\\.yml$    { deny all; }
    location ~* /app/config/.*\\.yaml$   { deny all; }
    location = /install                  { return 403; }
    location ~* ^/install/               { return 403; }
    location ~* ^/admin\\d+/             { }  # admin dir personalizada: permitir

    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|woff2|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
""",
    },
    {
        "name": "Joomla",
        "slug": "joomla",
        "description": "Joomla! 4/5. Protección de archivos de configuración y directorio de caché.",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
        }),
        "nginx_extra": """
    # ── Joomla ─────────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location ~* /configuration\\.php   { deny all; }
    location ~* ^/logs/                { deny all; }
    location ~* ^/tmp/                 { deny all; }
    location ~* ^/cache/               { deny all; }
    location ~* /htaccess\\.txt        { deny all; }

    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|woff2|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
""",
    },
    {
        "name": "Magento 2",
        "slug": "magento2",
        "description": "Magento 2. Alta memoria, protección de rutas internas y rewrite de URLs.",
        "category": "ecommerce",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "756M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "180",
        }),
        "nginx_extra": """
    # ── Magento 2 ───────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;

    location ~* /app/etc/env\\.php       { deny all; }
    location ~* ^/var/.*\\.php$         { deny all; }
    location ~* ^/vendor/.*\\.php$      { deny all; }
    location ~* /downloader/             { return 403; }
    location ~* /setup/                  { allow 127.0.0.1; deny all; }

    location ~* ^/pub/static/version    {
        rewrite ^/pub/static/(version[0-9]+/)?(.*)$ /pub/static/$2 last;
    }
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|woff2|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
""",
    },
    {
        "name": "PHP Estándar",
        "slug": "default-php",
        "description": "Configuración PHP estándar sin modificaciones extra. Útil para apps personalizadas.",
        "category": "other",
        "fastcgi_cache_default": False,
        "php_ini_overrides": None,
        "nginx_extra": """
    # ── PHP Estándar ─────────────────────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
""",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# TemplateManager
# ─────────────────────────────────────────────────────────────────────────────

class TemplateManager(SystemManager):
    """Aplica plantillas web a dominios existentes."""

    def __init__(self):
        super().__init__(require_root=True)

    def apply_template(
        self,
        domain_row,            # ORM Domain
        template_row,          # ORM WebTemplate
        username: str,
        enable_cache: Optional[bool] = None,
        ttl_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        Aplica la plantilla al dominio:
          1. Actualiza los campos de plantilla en el objeto domain_row (el caller hace commit)
          2. Regenera el vhost nginx con el nginx_extra de la plantilla
          3. Si hay php_ini_overrides, los aplica via PHPIniManager
          4. Activa/desactiva FastCGI cache según la plantilla (a menos que enable_cache lo anule)
          5. Reload nginx

        Returns: dict con resultado
        """
        result = {
            "status":       "success",
            "nginx_updated": False,
            "php_pool":      False,
            "cache_updated": False,
            "error":         None,
        }

        domain_name = domain_row.domain_name
        php_version = domain_row.php_version or "8.2"
        ssl_enabled = domain_row.ssl_enabled or False

        # ── Determinar estado de cache ────────────────────────────────────
        use_cache = template_row.fastcgi_cache_default
        if enable_cache is not None:
            use_cache = enable_cache

        # ── PHP ini overrides ─────────────────────────────────────────────
        # Todos los dominios tienen pool dedicado (con bloque de seguridad).
        # Si el template trae overrides, reescribimos el pool con ellos; si no,
        # el pool existente se mantiene. El socket SIEMPRE es el dedicado.
        from scripts.php_ini_manager import write_pool, pool_socket_path, has_pool
        php_socket_override = pool_socket_path(domain_name) if has_pool(domain_name) else None
        relax = getattr(domain_row, "php_hardening_relaxed", False) or False
        if template_row.php_ini_overrides:
            try:
                overrides = json.loads(template_row.php_ini_overrides)
                ok, msg = write_pool(
                    domain=domain_name,
                    version=php_version,
                    owner=username,
                    overrides=overrides,
                    relax_hardening=relax,
                )
                if ok:
                    php_socket_override = pool_socket_path(domain_name)
                    result["php_pool"] = True
                else:
                    logger.warning(f"PHP pool fallido para {domain_name}: {msg}")
            except Exception as exc:
                logger.warning(f"PHP ini overrides fallaron para {domain_name}: {exc}")

        # ── FastCGI cache zone (si procede) ────────────────────────────────
        if use_cache:
            try:
                write_fastcgi_cache_zone(domain_name)
                result["cache_updated"] = True
            except Exception as exc:
                logger.warning(f"Error configurando cache zone para {domain_name}: {exc}")
        else:
            try:
                remove_fastcgi_cache_zone(domain_name)
            except Exception:
                pass

        # ── Regenerar nginx con template_nginx_extra ───────────────────────
        try:
            nginx_config_path = get_nginx_config_path(domain_name)
            config = generate_nginx_config(
                domain=domain_name,
                user=username,
                php_version=php_version,
                ssl_enabled=ssl_enabled,
                ipv6=domain_row.ipv6,
                fastcgi_cache_enabled=use_cache,
                fastcgi_cache_ttl_minutes=ttl_minutes,
                php_socket_override=php_socket_override,
                template_nginx_extra=template_row.nginx_extra,
                ipv4=getattr(domain_row, 'ipv4', None),
                force_https=getattr(domain_row, 'force_https', False) or False,
                hsts=getattr(domain_row, 'hsts_enabled', False) or False,
                rate_limit_enabled=getattr(domain_row, 'rate_limit_enabled', False) or False,
                rate_limit_burst=getattr(domain_row, 'rate_limit_burst', 20) or 20,
                docroot_subdir=getattr(template_row, 'docroot_subdir', None),
            )
            with open(nginx_config_path, "w") as f:
                f.write(config)
            result["nginx_updated"] = True
        except Exception as exc:
            result["status"] = "failed"
            result["error"]  = f"Error escribiendo nginx config: {exc}"
            return result

        # ── Reload nginx ───────────────────────────────────────────────────
        if not reload_nginx():
            result["status"] = "failed"
            result["error"]  = "nginx config test falló tras aplicar plantilla"
            return result

        # ── Actualizar campos en domain_row (caller hace commit) ───────────
        domain_row.applied_template_id   = template_row.id
        domain_row.applied_template_name = template_row.name
        domain_row.template_nginx_extra  = template_row.nginx_extra

        if template_row.php_ini_overrides:
            domain_row.php_ini_overrides = template_row.php_ini_overrides

        domain_row.fastcgi_cache_enabled     = use_cache
        domain_row.fastcgi_cache_ttl_minutes = ttl_minutes

        return result
