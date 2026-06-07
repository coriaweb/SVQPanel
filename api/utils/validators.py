"""
Validadores puros (sin dependencias de FastAPI/BD) reutilizables y testeables.
"""

# Dominios que Let's Encrypt ACME rechaza (ejemplo, locales, reservados).
INVALID_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "localhost",
    "invalid", "test", "local", "localdomain",
}


def validate_acme_email(email: str) -> str:
    """
    Valida que el email sea aceptable por Let's Encrypt ACME.
    Devuelve el email limpio (minúsculas) o lanza ValueError con un mensaje
    descriptivo para mostrar al usuario.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError(
            "Se necesita un email válido para Let's Encrypt. "
            "Introdúcelo en el campo Email del formulario SSL."
        )
    domain_part = email.split("@", 1)[1]
    if domain_part in INVALID_EMAIL_DOMAINS or "." not in domain_part:
        raise ValueError(
            f"El email '{email}' no es válido para Let's Encrypt (dominio local o de ejemplo). "
            "Usa tu email real, p.ej. admin@tudominio.com"
        )
    return email
