"""
Modelo de configuración del panel (tabla singleton — siempre un único registro)
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from api.models.database import Base



class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # Panel
    panel_name = Column(String(255), default="SVQPanel")
    panel_version = Column(String(50), default="0.1.0")

    # Red - IPv4
    server_ipv4 = Column(String(45), nullable=True)          # IP pública del servidor

    # Red - IPv6
    ipv6_enabled = Column(Boolean, default=False)             # IPv6 activado
    ipv6_range = Column(String(50), nullable=True)            # Rango /64, ej: 2a01:4f8:1:2::/64
    ipv6_gateway = Column(String(50), nullable=True)          # Gateway IPv6 (opcional)
    panel_ipv6 = Column(String(50), nullable=True)            # IPv6 dedicada del panel (::1 del rango)
    network_interface = Column(String(20), default="eth0")    # Interfaz de red (eth0, ens3…)

    # PHP — fallback solo si el install no fija uno; el install lo sobreescribe
    # con la versión más reciente realmente instalada.
    php_default_version = Column(String(10), default="8.3")

    # Backup del propio panel — nº de copias diarias a conservar (rotación).
    panel_backup_retention = Column(Integer, default=15)

    # File Manager - Límites de subida
    max_upload_mb = Column(Integer, default=100)              # MB máximo por archivo
    max_text_file_mb = Column(Integer, default=2)             # MB máximo para editar en el panel
    max_extract_mb = Column(Integer, default=500)             # MB máximo para extraer ZIPs

    # SSL del propio panel
    panel_hostname = Column(String(255), nullable=True)       # Hostname del panel (ej: panel.midominio.com)
    ssl_panel_enabled = Column(Boolean, default=False)        # SSL emitido y activo para el panel
    ssl_panel_expires = Column(DateTime, nullable=True)       # Fecha de expiración del cert
    force_https = Column(Boolean, default=False)              # Redirigir HTTP → HTTPS del panel

    # Sistema
    timezone = Column(String(64), default="UTC")             # Zona horaria del servidor

    # ── Política de contraseñas ────────────────────────────────────────────
    # Reglas mínimas para las contraseñas que se establecen DESDE el panel
    # (usuarios, buzones, BD…). Configurable por el admin en Settings. La API
    # las valida (no solo el frontend) y el generador del panel las respeta.
    pwd_min_length   = Column(Integer, default=12)            # longitud mínima
    pwd_require_upper  = Column(Boolean, default=True)        # al menos 1 mayúscula
    pwd_require_lower  = Column(Boolean, default=True)        # al menos 1 minúscula
    pwd_require_digit  = Column(Boolean, default=True)        # al menos 1 número
    pwd_require_symbol = Column(Boolean, default=False)       # al menos 1 símbolo

    # Nameservers propios del panel (Fase A). Si están vacíos y hay cluster, se
    # derivan de los hostnames de los nodos; si no, del placeholder histórico.
    dns_ns1 = Column(String(255), nullable=True)              # ns1.tudominio.com
    dns_ns2 = Column(String(255), nullable=True)              # ns2.tudominio.com

    # SMTP relay GLOBAL (smarthost) — para enviar cuando el ISP bloquea el :25.
    # La contraseña se guarda en el password map de Postfix (0600), no aquí.
    relay_enabled  = Column(Boolean, default=False)
    relay_host     = Column(String(255), nullable=True)       # smtp.proveedor.com
    relay_port     = Column(Integer, default=587)
    relay_username = Column(String(255), nullable=True)       # vacío = sin auth

    # ── Whitelist de IPs para el acceso al panel ───────────────────────────
    # Si está activo, nginx solo deja acceder al panel (puerto dedicado) a las
    # IPs/CIDR de la lista. El .well-known (ACME) queda siempre permitido para
    # que certbot pueda renovar el SSL del panel. Rescate por SSH si te bloqueas:
    #   python -m api.cli panel_whitelist_disable
    panel_whitelist_enabled = Column(Boolean, default=False)
    panel_whitelist_ips     = Column(Text, nullable=True)   # una IP/CIDR por línea

    # ── SMTP saliente del PANEL (avisos, alertas, notificaciones) ──────────
    # Independiente del relay de clientes: lo usa el propio panel para enviar
    # sus correos (recuperación, avisos de cuota, expiración SSL, etc.) desde
    # un From real en lugar de root@localhost. La contraseña se guarda cifrada.
    panel_smtp_enabled    = Column(Boolean, default=False)
    panel_smtp_host       = Column(String(255), nullable=True)   # smtp.dominio.com
    panel_smtp_port       = Column(Integer, default=587)
    panel_smtp_security   = Column(String(16), default="starttls")  # none | starttls | ssl
    panel_smtp_username   = Column(String(255), nullable=True)
    panel_smtp_password   = Column(Text, nullable=True)          # cifrada con Fernet
    panel_smtp_from_email = Column(String(255), nullable=True)   # avisos@dominio.com
    panel_smtp_from_name  = Column(String(255), default="SVQPanel")

    # Cluster DNS — clave TSIG compartida master↔slave (ver models_dns_node.py)
    dns_tsig_name   = Column(String(64), nullable=True)       # nombre de la clave, ej: svq-xfer
    dns_tsig_secret = Column(String(128), nullable=True)      # secreto base64
    dns_tsig_algo   = Column(String(32), default="hmac-sha256")
    # Identificador único y estable de ESTA instalación del panel. Se usa como
    # namespace en los nodos DNS para que varios paneles compartan ns1/ns2 sin
    # pisarse las configuraciones. Se genera al primer load_cluster() si está vacío.
    dns_panel_id    = Column(String(32), nullable=True)       # ej: p7a3f9e2
    # Último health-check del cluster (lo escribe el timer; lo lee la UI)
    dns_cluster_health_json = Column(Text, nullable=True)     # JSON con rows+summary
    dns_cluster_health_at   = Column(DateTime, nullable=True) # cuándo se calculó

    # ── Licencia del panel (lo escribe el chequeo periódico; lo lee la UI) ──
    license_valid      = Column(Boolean, default=False)       # ¿licencia válida ahora?
    license_plan       = Column(String(32), nullable=True)    # beta | pro | ...
    license_expires    = Column(DateTime, nullable=True)      # caducidad de la licencia
    license_checked_at = Column(DateTime, nullable=True)      # última validación
    license_reason     = Column(String(48), nullable=True)    # ok | no_key | offline | ...

    # Greylisting global del correo. True = activo (cada dominio puede excluirse
    # con MailDomain.greylist_enabled=False). False = desactivado para TODOS.
    greylisting_enabled = Column(Boolean, default=True, nullable=False)

    # Mover spam (X-Spam: Yes de Rspamd) a la carpeta Junk. True = activo (cada
    # dominio puede excluirse con MailDomain.spam_to_junk_enabled=False).
    spam_to_junk_enabled = Column(Boolean, default=True, nullable=False)

    # Timestamps
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Settings panel={self.panel_name} ipv6={self.ipv6_range}>"
