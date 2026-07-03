from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base

class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Dominio
    domain_name = Column(String(255), unique=True, nullable=False, index=True)
    
    # Rutas
    public_html = Column(String(255), nullable=False)  # /home/user/public_html/domain
    
    # PHP
    php_version = Column(String(10), default="8.2")  # 7.4, 8.0, 8.1, 8.2, 8.3
    
    # SSL
    ssl_enabled = Column(Boolean, default=False)
    ssl_certificate = Column(Text, nullable=True)
    ssl_key = Column(Text, nullable=True)
    ssl_expires = Column(DateTime, nullable=True)
    
    # IPv4 e IPv6
    ipv4 = Column(String(45), nullable=True)
    ipv6 = Column(String(45), nullable=True)
    
    # Estado
    is_active     = Column(Boolean, default=True)
    is_suspended  = Column(Boolean, default=False, nullable=False)  # suspendido individualmente

    # Subdominio: si is_subdomain=True, este "dominio" es en realidad un
    # subdominio (ej. gestion.zococoria.es) de parent_domain (zococoria.es).
    # Web (vhost/docroot) propios igual que un dominio, pero en DNS NO crea una
    # zona separada: añade un registro A/AAAA en la zona padre si esta vive en el
    # panel. Si la padre no está en el panel, cae a zona propia (como un dominio).
    is_subdomain  = Column(Boolean, default=False, nullable=False)
    parent_domain = Column(String(255), nullable=True, index=True)  # zona padre, ej: zococoria.es

    # Staging de WordPress: si este dominio es un entorno de staging clonado
    # desde otro (staging.dominio.com), apunta al Domain live del que se clonó.
    # NULL = dominio normal. Si el live se borra, el puntero queda a NULL (el
    # staging pasa a ser un subdominio normal, borrable a mano).
    staging_of_domain_id = Column(Integer,
                                  ForeignKey("domains.id", ondelete="SET NULL"),
                                  nullable=True, index=True)

    # Dominio "solo correo/DNS": NO aloja la web aquí (su registro A apunta a otro
    # servidor). No se crea vhost, pool PHP ni estructura web; el Domain es un
    # registro ligero al que se le puede colgar correo y zona DNS. public_html
    # queda vacío. Pensado para clientes que solo quieren el correo (o DNS) aquí.
    mail_dns_only = Column(Boolean, default=False, nullable=False)
    
    # FastCGI cache (Fase 14)
    fastcgi_cache_enabled    = Column(Boolean, default=False, nullable=False)
    fastcgi_cache_ttl_minutes = Column(Integer, default=60, nullable=False)

    # php.ini overrides por dominio (JSON: {"memory_limit":"256M",...}) — Fase 14.3
    php_ini_overrides = Column(Text, nullable=True)

    # Plantilla web aplicada (Fase 15)
    applied_template_id   = Column(Integer, ForeignKey("web_templates.id", ondelete="SET NULL"), nullable=True)
    applied_template_name = Column(String(64), nullable=True)
    template_nginx_extra  = Column(Text, nullable=True)

    # Directivas personalizadas por dominio (se inyectan en el vhost, además de
    # la plantilla). Validadas con nginx -t / apache configtest al guardar.
    custom_nginx_config   = Column(Text, nullable=True)
    custom_apache_config  = Column(Text, nullable=True)

    # Protección con contraseña (auth básica HTTP). El hash (apr1) va al
    # .htpasswd; aquí guardamos solo metadatos (nunca la contraseña en claro).
    httpauth_enabled    = Column(Boolean, default=False)
    httpauth_user       = Column(String(64), nullable=True)
    httpauth_pass_hash  = Column(String(255), nullable=True)

    # Redirección 301 y docroot personalizado (Fase 16)
    redirect_to    = Column(String(512), nullable=True)   # ej: https://otro.com
    custom_docroot = Column(String(512), nullable=True)   # ej: /home/user/web/domain/app/public

    # Subcarpeta del docroot que sirve la app (la aporta la plantilla: Laravel/
    # Symfony usan "public", algunos "web"). Debe PERSISTIR aquí para que cualquier
    # regeneración del vhost la conserve (si no, un dominio Laravel pierde el
    # /public al regenerar y da 404). NULL = sirve desde la raíz del docroot.
    docroot_subdir = Column(String(64), nullable=True)

    # SSL avanzado
    force_https  = Column(Boolean, default=False, nullable=False)
    hsts_enabled = Column(Boolean, default=False, nullable=False)

    # Dominio canónico: a qué variante redirigir 301 (SEO + costumbre del cliente).
    #   "www"     → dominio.com   redirige a www.dominio.com  (DEFAULT del panel)
    #   "non-www" → www.dominio.com redirige a dominio.com
    #   "none"    → sirve ambas sin redirigir (comportamiento antiguo)
    canonical_domain = Column(String(8), default="www", nullable=False)

    # Rate limiting anti-abuso (Fase 19) — off por defecto
    rate_limit_enabled = Column(Boolean, default=False, nullable=False)
    rate_limit_rps     = Column(Integer, default=10, nullable=False)
    rate_limit_burst   = Column(Integer, default=20, nullable=False)

    # Hardening PHP relajado (Fase 20): si True este dominio permite
    # exec/system/etc. open_basedir y el resto del hardening se mantienen.
    php_hardening_relaxed = Column(Boolean, default=False, nullable=False)

    # Tuning de recursos del pool PHP-FPM por dominio (Fase 21). JSON:
    # {"preset":"low|medium|high","manual":{"pm.max_children":12,...}}. None = preset medium.
    fpm_pool_overrides = Column(Text, nullable=True)

    # Redis dedicado del dominio (caché de objetos). Instancia propia con
    # socket unix en private/ y maxmemory acotado — ver scripts/redis_manager.py.
    redis_enabled      = Column(Boolean, default=False, nullable=False)
    redis_maxmemory_mb = Column(Integer, default=64, nullable=False)

    # Modo solo-lectura HTTP: bloquea POST/PUT/DELETE/PATCH excepto desde las
    # IPs indicadas. Útil para contener un CMS comprometido o proteger APIs.
    # allowed_mutation_ips: JSON array de IPs/CIDRs, ej: ["1.2.3.4","10.0.0.0/8"]
    readonly_mode_enabled  = Column(Boolean, default=False, nullable=False)
    allowed_mutation_ips   = Column(Text, nullable=True)  # JSON array, NULL = nadie

    # Headers HTTP de seguridad (X-Frame-Options, X-Content-Type-Options, etc.)
    security_headers_enabled = Column(Boolean, default=False, nullable=False)
    # HTTP/3 (QUIC) — requiere nginx 1.25+ con http_v3_module
    http3_enabled = Column(Boolean, default=False, nullable=False)

    # Bad bots bloqueados a nivel de dominio (JSON array de patrones, ej: ["zgrab","nikto"])
    blocked_user_agents = Column(Text, nullable=True)

    # Bloqueo de XML-RPC de WordPress. Desbloqueado por defecto (no rompemos la
    # app móvil/Jetpack de nadie sin avisar). Cuando un dominio recibe un ataque
    # masivo de fuerza bruta/amplificación a xmlrpc.php, el panel avisa al cliente
    # y este puede activarlo: el vhost devuelve 444 a /xmlrpc.php (corta el ataque
    # antes de arrancar PHP). Reversible desde el toggle del panel.
    xmlrpc_blocked = Column(Boolean, default=False, nullable=False)

    # Rate-limit de /wp-login.php (fuerza bruta al login de WordPress). A
    # diferencia de xmlrpc, wp-login NO se puede bloquear (es el login real), así
    # que se limita por IP: una persona necesita 1-2 intentos, un bot mete miles.
    # 0 = desactivado. >0 = nº máximo de peticiones/min por IP a /wp-login.php.
    wp_login_ratelimit = Column(Integer, default=0, nullable=False)

    # Actualizaciones automáticas seguras de WordPress (wp_safe_update): el pase
    # nocturno del panel actualiza core/plugins/temas con checkpoint previo,
    # verificación y rollback automático si el sitio se rompe.
    wp_auto_update = Column(Boolean, default=False, nullable=False)

    # Cache del análisis de ataque (lo actualiza un cron cada ~3h, ventana 24h).
    # Evita escanear los access.log en vivo cada vez que se abre la vista admin.
    wp_xmlrpc_hits       = Column(Integer, default=0, nullable=False)   # hits a xmlrpc.php
    wp_wplogin_hits      = Column(Integer, default=0, nullable=False)   # hits a wp-login.php
    wp_attack_checked_at = Column(DateTime, nullable=True)             # última medición

    # Despliegue Git (Fase 21) — repo desplegado en public_html (symlink a
    # releases/). La clave privada del deploy key NO va en BD (vive en ~/.ssh).
    git_enabled        = Column(Boolean, default=False, nullable=False)
    git_repo_url       = Column(String(512), nullable=True)
    git_branch         = Column(String(255), default="main", nullable=True)
    git_provider       = Column(String(20), default="github", nullable=True)  # github|gitlab|generic
    git_webhook_token  = Column(String(64), nullable=True, index=True)  # secreto del webhook
    git_build_commands = Column(Text, nullable=True)  # uno por línea, ejecutados como el usuario
    git_deploy_key_pub = Column(Text, nullable=True)  # clave pública SSH (la privada en ~/.ssh)
    git_keep_releases  = Column(Integer, default=5, nullable=False)

    # Estadísticas
    disk_usage = Column(Integer, default=0)  # MB (legacy)

    # Peso en disco CACHEADO (bytes). El cálculo real (du -sb) es caro: recorre
    # todo el árbol del dominio. Se calcula en background (cron 2/día) o bajo
    # demanda (botón refrescar) y se persiste aquí, para que la lista de dominios
    # cargue instantánea leyendo de BD en vez de hacer du en vivo por cada uno.
    disk_public_html_bytes = Column(BigInteger, nullable=True)
    disk_logs_bytes        = Column(BigInteger, nullable=True)
    disk_total_bytes       = Column(BigInteger, nullable=True)
    disk_calculated_at     = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ssl_renewed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    user      = relationship("User",           back_populates="domains")
    databases = relationship("ClientDatabase", back_populates="domain", cascade="all, delete-orphan")
    cron_jobs = relationship("CronJob",        back_populates="domain")
    git_deployments = relationship("GitDeployment", back_populates="domain", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Domain {self.domain_name}>"
