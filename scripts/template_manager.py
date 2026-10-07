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
    get_public_html,
    get_domain_logs,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Plantillas builtin (se insertan en BD en la migración)
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    # ─────────────────────────────────────────────────────────────────────────
    # Criterio (oct 2026): una plantilla SOLO añade lo propio de la aplicación.
    # Nada de lo que el panel ya da por su cuenta: cabeceras de seguridad (tarjeta
    # propia), caché de navegador de estáticos, bloqueo de .env/.git/.svn/backups
    # y de PHP en wp-content/uploads, .well-known de CalDAV/CardDAV,
    # client_max_body_size (sale del PHP del dominio), protección de xmlrpc y
    # wp-login. Y nada que choque con él: ni `location /` (salvo apps que no son
    # PHP y sirven el sitio ellas mismas: sustituye al del panel), ni fastcgi_pass
    # (en Apache+Nginx se saltaría Apache y sus .htaccess), ni `location =` exacto
    # sobre rutas que el panel protege con regex (el exacto gana y anula la
    # protección). Lo que solo hace falta sin Apache va entre
    # `# >>> solo-nginx` / `# <<< solo-nginx` (en Apache+Nginx lo hace el .htaccess).
    # ─────────────────────────────────────────────────────────────────────────
    {
        "name": "WordPress",
        "slug": "wordpress",
        "description": "WordPress y WooCommerce: más memoria, subidas de 64 MB, más campos por formulario (menús grandes, WooCommerce), caché de página activada y bloqueo de los ficheros que revelan la configuración o la versión.",
        "category": "cms",
        "fastcgi_cache_default": True,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
            "max_input_vars":      "3000",
        }),
        "nginx_extra": """
    # ── WordPress ───────────────────────────────────────────────────────
    # La configuración y los ficheros que delatan la versión no se sirven nunca
    # (si PHP fallara, wp-config.php se descargaría en texto plano). ^/+ cubre //.
    location ~* ^/+(wp-config\\.php|wp-config-sample\\.php|readme\\.html|license\\.txt)$ { deny all; }
""",
    },
    {
        "name": "WordPress Multisite",
        "slug": "wordpress-multisite",
        "description": "WordPress Multisite (subdirectorios): lo mismo que WordPress más las reglas de rutas de los subsitios cuando el servidor es solo nginx (con Apache las pone su .htaccess).",
        "category": "cms",
        "fastcgi_cache_default": True,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
            "max_input_vars":      "3000",
        }),
        "nginx_extra": """
    # ── WordPress Multisite (subdirectorios) ────────────────────────────
    location ~* ^/+(wp-config\\.php|wp-config-sample\\.php|readme\\.html|license\\.txt)$ { deny all; }
    # >>> solo-nginx
    # /subsitio/wp-admin, /subsitio/wp-*.php → los del núcleo (lo que hace el .htaccess)
    if (!-e $request_filename) {
        rewrite ^/[_0-9a-zA-Z-]+(/wp-admin)$ $1/ permanent;
        rewrite ^/[_0-9a-zA-Z-]+(/wp-.*) $1 last;
        rewrite ^/[_0-9a-zA-Z-]+(/.*\\.php)$ $1 last;
    }
    # <<< solo-nginx
""",
    },
    {
        "name": "Laravel",
        "slug": "laravel",
        "description": "Laravel: sirve desde /public (el resto del proyecto, .env incluido, queda fuera de la web) y no ejecuta PHP dentro de /storage (ficheros subidos por los usuarios).",
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
    # public/storage enlaza a storage/app/public (subidas de usuarios): un .php
    # subido ahí no debe poder ejecutarse.
    location ~* ^/+storage/.*\\.php$ { deny all; }
""",
    },
    {
        "name": "Drupal",
        "slug": "drupal",
        "description": "Drupal 9/10/11: más memoria y tiempo para actualizaciones, y bloqueo de los ficheros internos (módulos, plantillas, YAML, carpeta privada, vendor).",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
            "max_execution_time":  "180",
        }),
        "nginx_extra": """
    # ── Drupal ──────────────────────────────────────────────────────────
    # Código y configuración interna (lo que bloquea el .htaccess de Drupal)
    location ~* \\.(engine|inc|install|make|module|profile|po|theme|twig|tpl(\\.php)?|xtmpl|ya?ml)$ { deny all; }
    location ~* ^/+(vendor|core/(scripts|tests))/ { deny all; }
    location ~* ^/+sites/[^/]+/private/ { deny all; }
    location ~* ^/+sites/[^/]+/files/.*\\.php$ { deny all; }
""",
    },
    {
        "name": "Nextcloud",
        "slug": "nextcloud",
        "description": "Nextcloud: subidas de hasta 16 GB, más memoria y tiempo, bloqueo de /data, /config y rutas internas, y las cabeceras que exige su comprobación de seguridad.",
        "category": "other",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "512M",
            "upload_max_filesize": "16G",
            "post_max_size":       "16G",
            "max_execution_time":  "3600",
            "max_input_time":      "3600",
            "output_buffering":    "0",
        }),
        "nginx_extra": """
    # ── Nextcloud ───────────────────────────────────────────────────────
    # Cabeceras propias de Nextcloud (las generales están en "Headers de seguridad")
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header X-Permitted-Cross-Domain-Policies "none" always;
    # Rutas que nunca deben servirse ni ejecutarse
    location ~ ^/+(?:build|tests|config|lib|3rdparty|templates|data)(?:$|/) { return 404; }
    location ~ ^/+(?:\\.|autotest|occ|issue|indie|db_|console)              { return 404; }
    location ~ ^/+(?:README|db_structure\\.xml)                               { return 404; }
    # >>> solo-nginx
    # Recursos de apps que no existen como fichero → los genera index.php
    location ~ \\.(?:css|js|mjs|svg|gif|png|jpg|ico|wasm|tflite|map|woff2?)$ {
        try_files $uri /index.php$request_uri;
        expires 7d;
        access_log off;
    }
    fastcgi_buffers 64 4K;
    # <<< solo-nginx
""",
    },
    {
        "name": "PrestaShop",
        "slug": "prestashop",
        "description": "PrestaShop 8: más memoria y tiempo para el back office e importaciones, y bloqueo de la configuración, el instalador, los logs y las plantillas de correo.",
        "category": "ecommerce",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "180",
            "max_input_vars":      "5000",
        }),
        "nginx_extra": """
    # ── PrestaShop 8 ────────────────────────────────────────────────────
    location ~* ^/+config/.*\\.inc\\.php$ { deny all; }
    location ~* ^/+app/config/.*\\.ya?ml$ { deny all; }
    location ~* ^/+(?:install|install-dev)(?:$|/) { deny all; }
    location ~* ^/+(?:app/logs|var/logs|var/cache|translations|mails)(?:$|/) { deny all; }
""",
    },
    {
        "name": "Joomla",
        "slug": "joomla",
        "description": "Joomla! 4/5: más memoria y subidas de 32 MB, y bloqueo de configuration.php y de las carpetas de logs, temporales y caché.",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
        }),
        "nginx_extra": """
    # ── Joomla ──────────────────────────────────────────────────────────
    location ~* ^/+(configuration\\.php|htaccess\\.txt)$ { deny all; }
    location ~* ^/+(?:logs|tmp|cache|administrator/logs)/ { deny all; }
""",
    },
    {
        "name": "Magento 2",
        "slug": "magento2",
        "description": "Magento 2: la memoria alta que necesita, bloqueo de env.php, var, vendor y setup, y las URLs versionadas de /pub/static cuando el servidor es solo nginx.",
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
    location ~* ^/+app/etc/ { deny all; }
    location ~* ^/+(?:var|vendor)/.*\\.php$ { deny all; }
    location ~* ^/+(?:setup|downloader|update)(?:$|/) { deny all; }
    # >>> solo-nginx
    location ~* ^/+pub/static/version {
        rewrite ^/+pub/static/(version[0-9]+/)?(.*)$ /pub/static/$2 last;
    }
    # <<< solo-nginx
""",
    },
    {
        "name": "Moodle",
        "slug": "moodle",
        "description": "Moodle: límites altos para subir cursos y contenidos (256 MB, 5000 campos), bloqueo de config.php y rutas internas, y los enlaces de ficheros (/pluginfile.php/…) cuando el servidor es solo nginx.",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "512M",
            "upload_max_filesize": "256M",
            "post_max_size":       "256M",
            "max_execution_time":  "300",
            "max_input_vars":      "5000",
        }),
        "nginx_extra": """
    # ── Moodle ──────────────────────────────────────────────────────────
    location ~ ^/+(config|lib/setup|install)\\.php$ { deny all; }
    location ~ ^/+(vendor|node_modules|environment|composer\\.(json|lock))(?:$|/) { deny all; }
    # >>> solo-nginx
    # "Argumentos con barra": /pluginfile.php/12/... necesita PATH_INFO
    location ~ [^/]\\.php(/|$) {
        fastcgi_split_path_info ^(.+\\.php)(/.*)$;
        fastcgi_pass $phpfpm_backend;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        fastcgi_param HTTPS $https if_not_empty;
    }
    # <<< solo-nginx
""",
    },
    {
        "name": "MediaWiki",
        "slug": "mediawiki",
        "description": "MediaWiki: subidas de 128 MB, bloqueo de las carpetas internas y URLs cortas /wiki/Página (requiere $wgArticlePath = \"/wiki/$1\").",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "128M",
            "post_max_size":       "128M",
            "max_execution_time":  "120",
        }),
        "nginx_extra": """
    # ── MediaWiki ───────────────────────────────────────────────────────
    location ~ ^/+(cache|includes|languages|maintenance|serialized|vendor)/ { deny all; }
    # URLs cortas /wiki/Pagina
    location ^~ /wiki/ { rewrite ^/wiki/(.*)$ /index.php?title=$1&$args last; }
""",
    },
    {
        "name": "phpBB",
        "slug": "phpbb",
        "description": "Foro phpBB: subidas de 32 MB y bloqueo de config.php y de las carpetas de caché, adjuntos y avatares (se sirven a través de phpBB, que comprueba permisos).",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
            "max_execution_time":  "60",
        }),
        "nginx_extra": """
    # ── phpBB ───────────────────────────────────────────────────────────
    location ~ ^/+(config|common)\\.php$ { deny all; }
    location ~ ^/+(cache|files|store|includes|images/avatars/upload)/ { deny all; }
""",
    },
    {
        "name": "Symfony",
        "slug": "symfony",
        "description": "Symfony: sirve desde /public y solo deja ejecutar el front controller index.php (cualquier otro .php olvidado devuelve 404).",
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
    # ── Symfony ─────────────────────────────────────────────────────────
    # Solo index.php es ejecutable (práctica recomendada por Symfony)
    location ~ ^/+(?!index\\.php).+\\.php(/|$) { return 404; }
""",
    },
    {
        "name": "CodeIgniter",
        "slug": "codeigniter",
        "description": "CodeIgniter 4: sirve desde /public y solo deja ejecutar index.php.",
        "category": "framework",
        "fastcgi_cache_default": False,
        "docroot_subdir": "public",
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
        }),
        "nginx_extra": """
    # ── CodeIgniter 4 ───────────────────────────────────────────────────
    location ~ ^/+(?!index\\.php).+\\.php(/|$) { return 404; }
""",
    },
    {
        "name": "Yii Framework",
        "slug": "yii",
        "description": "Yii 2: sirve desde /web y solo deja ejecutar index.php (bloquea index-test.php, que no debe estar accesible en producción).",
        "category": "framework",
        "fastcgi_cache_default": False,
        "docroot_subdir": "web",
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "32M",
            "post_max_size":       "32M",
        }),
        "nginx_extra": """
    # ── Yii 2 ───────────────────────────────────────────────────────────
    location ~ ^/+(?!index\\.php).+\\.php(/|$) { return 404; }
""",
    },
    {
        "name": "Ghost",
        "slug": "ghost",
        "description": "Blog Ghost (Node.js): nginx sirve el dominio haciendo de proxy al servicio Ghost local (puerto 2368; ajústalo en Directivas si usas otro). Sustituye al PHP del dominio.",
        "category": "cms",
        "fastcgi_cache_default": False,
        "php_ini_overrides": None,
        "nginx_extra": """
    # ── Ghost (proxy a Node.js) ─────────────────────────────────────────
    # Sustituye al location / del panel: el sitio lo sirve Ghost, no PHP.
    location / {
        proxy_pass http://127.0.0.1:2368;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
""",
    },
    {
        "name": "Matomo",
        "slug": "matomo",
        "description": "Analítica Matomo: más memoria, bloqueo de config, tmp y núcleo, y solo los PHP públicos de Matomo son ejecutables (index.php, matomo.php, piwik.php).",
        "category": "other",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "512M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
        }),
        "nginx_extra": """
    # ── Matomo ──────────────────────────────────────────────────────────
    location ~ ^/+(config|tmp|core|lang)(?:$|/) { deny all; }
    location ~ ^/+(libs|vendor|plugins|misc/user)/.*\\.(twig|tpl|php)$ { deny all; }
    location ~ ^/+(?!(index|matomo|piwik|js/index)\\.php).+\\.php$ { deny all; }
""",
    },
    {
        "name": "OpenCart",
        "slug": "opencart",
        "description": "Tienda OpenCart: subidas de 64 MB y bloqueo de /system y /storage.",
        "category": "ecommerce",
        "fastcgi_cache_default": False,
        "php_ini_overrides": json.dumps({
            "memory_limit":        "256M",
            "upload_max_filesize": "64M",
            "post_max_size":       "64M",
            "max_execution_time":  "120",
        }),
        "nginx_extra": """
    # ── OpenCart ────────────────────────────────────────────────────────
    location ~ ^/+(system|storage)/ { deny all; }
""",
    },
    {
        "name": "Sitio estático / SPA",
        "slug": "static-spa",
        "description": "Sitio estático o SPA (React, Vue, Angular): nginx lo sirve directamente y las rutas del navegador vuelven a index.html. Sustituye al PHP del dominio.",
        "category": "other",
        "fastcgi_cache_default": False,
        "php_ini_overrides": None,
        "nginx_extra": """
    # ── Estático / SPA ──────────────────────────────────────────────────
    # Sustituye al location / del panel: rutas de cliente (history API) → index.html
    location / { try_files $uri $uri/ /index.html; }
""",
    },
    {
        "name": "PHP Estándar",
        "slug": "default-php",
        "description": "Sin reglas extra: vuelve a la configuración por defecto del panel (quita las reglas de otra plantilla; los valores de PHP no se tocan).",
        "category": "other",
        "fastcgi_cache_default": False,
        "php_ini_overrides": None,
        "nginx_extra": None,
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
          1. Si hay php_ini_overrides, reescribe el pool PHP-FPM con ellos
          2. Guarda en domain_row los campos de la plantilla (nginx_extra,
             docroot_subdir, php_ini_overrides, caché) y hace commit
          3. Regenera el vhost con el MISMO camino que el resto del panel
             (_regenerate_domain_vhost → DomainManager.regenerate_vhost)
          4. Si la validación falla, revierte TODO (BD, pool y vhost)

        Antes generaba el vhost por su cuenta con generate_nginx_config: en
        servidores Apache+Nginx escribía un vhost de PHP directo con
        fastcgi_cache sobre una zona declarada como proxy_cache → nginx -t
        fallaba ("shared memory zone … already declared for a different use")
        y, como no revertía, dejaba el vhost roto en disco (obradormarilo.com,
        oct 2026). Además perdía ajustes del dominio que solo conoce
        regenerate_vhost (directivas propias, xmlrpc, wp-login, HTTP/3, httpauth…).

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

        # ── Determinar estado de cache ────────────────────────────────────
        use_cache = template_row.fastcgi_cache_default
        if enable_cache is not None:
            use_cache = enable_cache

        # ── PHP ini overrides ─────────────────────────────────────────────
        # Todos los dominios tienen pool dedicado (con bloque de seguridad).
        # Si el template trae overrides, reescribimos el pool con ellos; si no,
        # el pool existente se mantiene. El socket SIEMPRE es el dedicado.
        from scripts.php_ini_manager import write_pool
        relax = getattr(domain_row, "php_hardening_relaxed", False) or False
        # Preservar el tuning FPM del dominio al reescribir el pool por la plantilla.
        _fpm_raw = getattr(domain_row, "fpm_pool_overrides", None)
        try:
            fpm_tuning = json.loads(_fpm_raw) if _fpm_raw else None
        except (ValueError, TypeError):
            fpm_tuning = None
        from sqlalchemy.orm import object_session
        from api.models.models_user import User
        from api.routes.domains import _regenerate_domain_vhost

        db = object_session(domain_row)
        owner = db.query(User).filter(User.id == domain_row.user_id).first() if db else None
        if db is None or owner is None:
            result["status"] = "failed"
            result["error"] = "No se pudo resolver el dominio o su propietario en la BD"
            return result

        # Estado anterior, para revertir si la validación falla
        _fields = ("applied_template_id", "applied_template_name", "template_nginx_extra",
                   "docroot_subdir", "php_ini_overrides", "fastcgi_cache_enabled",
                   "fastcgi_cache_ttl_minutes")
        prev = {f: getattr(domain_row, f, None) for f in _fields}
        pool_rewritten = False

        def _write_pool_with(overrides_json):
            overrides = json.loads(overrides_json) if overrides_json else {}
            return write_pool(domain=domain_name, version=php_version, owner=username,
                              overrides=overrides, relax_hardening=relax,
                              fpm_tuning=fpm_tuning)

        # ── PHP ini overrides → pool dedicado ─────────────────────────────
        if template_row.php_ini_overrides:
            try:
                ok, msg = _write_pool_with(template_row.php_ini_overrides)
                if ok:
                    pool_rewritten = True
                    result["php_pool"] = True
                else:
                    logger.warning(f"PHP pool fallido para {domain_name}: {msg}")
            except Exception as exc:
                logger.warning(f"PHP ini overrides fallaron para {domain_name}: {exc}")

        # ── Campos de la plantilla en BD (regenerate_vhost lee de aquí) ─────
        domain_row.applied_template_id   = template_row.id
        domain_row.applied_template_name = template_row.name
        domain_row.template_nginx_extra  = template_row.nginx_extra
        # Subcarpeta del docroot (Laravel/Symfony 'public'): toda regeneración
        # posterior del vhost la conserva (si no, da 404).
        domain_row.docroot_subdir = getattr(template_row, 'docroot_subdir', None) or None
        if template_row.php_ini_overrides:
            domain_row.php_ini_overrides = template_row.php_ini_overrides
        domain_row.fastcgi_cache_enabled     = use_cache
        domain_row.fastcgi_cache_ttl_minutes = ttl_minutes
        db.commit()

        # ── Vhost: mismo camino que el resto del panel (respeta Apache/nginx) ─
        try:
            _regenerate_domain_vhost(domain_row, owner)
            result["nginx_updated"] = True
            result["cache_updated"] = True
            return result
        except Exception as exc:
            logger.error(f"Plantilla '{template_row.name}' en {domain_name}: {exc}; revirtiendo")
            for f, v in prev.items():
                setattr(domain_row, f, v)
            db.commit()
            if pool_rewritten:
                try:
                    _write_pool_with(prev["php_ini_overrides"])
                except Exception as exc2:
                    logger.error(f"No se pudo restaurar el pool de {domain_name}: {exc2}")
            try:
                _regenerate_domain_vhost(domain_row, owner)
            except Exception as exc3:
                logger.error(f"No se pudo restaurar el vhost de {domain_name}: {exc3}")
            result.update(status="failed", nginx_updated=False, cache_updated=False,
                          error=f"La plantilla no se ha aplicado (configuración no válida, "
                                f"se ha restaurado la anterior): {exc}")
            return result
