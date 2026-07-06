"""
Envío de correo saliente del PANEL (avisos, alertas, notificaciones).

Usa el SMTP configurado en Settings (panel_smtp_*), de modo que los correos
del panel salgan desde un remitente real (avisos@dominio.com) en lugar de
root@localhost. La contraseña se guarda cifrada con Fernet (PANEL_ENCRYPTION_KEY).

Uso:
    from scripts.panel_mailer import send_panel_email, send_test_email
    send_panel_email(db, to="user@x.com", subject="Aviso", body_text="...")
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

logger = logging.getLogger(__name__)

PANEL_ENCRYPTION_KEY = os.getenv("PANEL_ENCRYPTION_KEY", "")


def _get_fernet():
    if not PANEL_ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(PANEL_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def encrypt_password(plain: str) -> str:
    """Cifra una contraseña con Fernet. Si no hay clave, la devuelve en claro
    (mejor que perder la config; en producción siempre habrá clave)."""
    if not plain:
        return ""
    f = _get_fernet()
    if not f:
        logger.warning("PANEL_ENCRYPTION_KEY no configurada; guardando SMTP pass sin cifrar")
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_password(enc: str) -> str:
    """Descifra. Si no parece cifrado (sin clave), lo devuelve tal cual."""
    if not enc:
        return ""
    f = _get_fernet()
    if not f:
        return enc
    try:
        return f.decrypt(enc.encode()).decode()
    except Exception:
        # Posiblemente se guardó en claro antes de tener clave
        return enc


def _smtp_config(settings):
    """Extrae la config SMTP del objeto Settings; lanza ValueError si falta algo."""
    if not settings or not settings.panel_smtp_enabled:
        raise ValueError("El SMTP del panel no está activado en Configuración.")
    host = (settings.panel_smtp_host or "").strip()
    if not host:
        raise ValueError("Falta el host SMTP.")
    from_email = (settings.panel_smtp_from_email or settings.panel_smtp_username or "").strip()
    if not from_email:
        raise ValueError("Falta la dirección 'From' del SMTP.")
    return {
        "host": host,
        "port": int(settings.panel_smtp_port or 587),
        "security": (settings.panel_smtp_security or "starttls").lower(),
        "username": (settings.panel_smtp_username or "").strip(),
        "password": decrypt_password(settings.panel_smtp_password or ""),
        "from_email": from_email,
        "from_name": _effective_from_name(settings),
    }


def _effective_from_name(settings) -> str:
    """Nombre del remitente. Si hay marca blanca y el admin dejó el from_name
    por defecto ('SVQPanel' o vacío), los correos salen con la marca del cliente."""
    from_name = (settings.panel_smtp_from_name or "").strip()
    brand = (getattr(settings, "brand_name", None) or "").strip()
    if brand and from_name in ("", "SVQPanel"):
        return brand
    return from_name or "SVQPanel"


def _send(cfg, to_email, subject, body_text, body_html=None):
    """Envía un correo con la config dada. Lanza excepción si falla."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["from_email"]))
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    timeout = 20
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=timeout)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout)

    try:
        server.ehlo()
        if cfg["security"] == "starttls":
            server.starttls()
            server.ehlo()
        if cfg["username"]:
            server.login(cfg["username"], cfg["password"])
        server.sendmail(cfg["from_email"], [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_panel_email(db, to, subject, body_text, body_html=None, settings=None):
    """
    Envía un correo del panel usando la config SMTP de Settings.
    `db` se usa para cargar Settings si no se pasa `settings`.
    Devuelve True si se envió; lanza excepción con mensaje claro si falla.
    """
    if settings is None:
        from api.routes.settings import get_or_create_settings
        settings = get_or_create_settings(db)
    cfg = _smtp_config(settings)
    _send(cfg, to, subject, body_text, body_html)
    logger.info(f"Correo del panel enviado a {to}: {subject}")
    return True


def send_test_email(settings, to):
    """
    Envía un correo de prueba con la config dada (objeto Settings, ya con la
    contraseña que el usuario acaba de introducir o la guardada).
    """
    cfg = _smtp_config(settings)
    panel = cfg["from_name"]
    accent = (getattr(settings, "brand_accent_color", None) or "").strip() or "#f08a2a"
    subject = f"Correo de prueba — {panel}"
    body = (
        "¡Funciona!\n\n"
        f"Este es un correo de prueba enviado por {panel} a través del SMTP "
        f"configurado ({cfg['host']}:{cfg['port']}).\n\n"
        "Si lo recibes, los avisos del panel se entregarán correctamente desde "
        f"{cfg['from_email']}.\n"
    )
    html = f"""<div style="font-family:sans-serif;max-width:520px">
      <h2 style="color:{accent}">¡Funciona! ✅</h2>
      <p>Este es un correo de prueba enviado por <strong>{panel}</strong> a través del SMTP
      configurado (<code>{cfg['host']}:{cfg['port']}</code>).</p>
      <p>Los avisos del panel se entregarán desde <strong>{cfg['from_email']}</strong>.</p>
    </div>"""
    _send(cfg, to, subject, body, html)
    logger.info(f"Correo de prueba enviado a {to}")
    return True
