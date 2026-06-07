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


class OwnerAssignmentError(ValueError):
    """Error de asignación de propietario de un recurso (BD/correo/DNS).

    Lleva un `status_code` HTTP sugerido (400 = falta/ inválido, 403 = sin
    permiso, 404 = no existe) para que la ruta lo mapee a HTTPException.
    """
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_owner_assignment(
    *,
    actor_role: str,
    actor_id: int,
    actor_is_admin: bool,
    requested_user_id,
    owner_exists: bool,
    owner_is_admin: bool,
    owner_parent_id,
    resource_label: str = "este recurso",
) -> int:
    """
    Política común para asignar propietario a un recurso de cliente (base de
    datos, dominio de correo, zona DNS): NUNCA pertenece a un administrador,
    igual que un dominio. Devuelve el `user_id` propietario resuelto o lanza
    OwnerAssignmentError con el status_code adecuado.

    Reglas:
      - Usuario normal: propietario = él mismo (se ignora requested_user_id).
      - Admin/reseller: requested_user_id es OBLIGATORIO; el destino debe existir
        y NO ser admin. Un reseller (no admin) solo puede asignar a sus clientes
        (owner == él, o owner.parent_id == él).

    Los flags `owner_*` los rellena la ruta tras buscar el usuario en la BD;
    así esta función no depende de la BD y es testeable.
    """
    is_admin_or_reseller = actor_role in ("admin", "reseller") or actor_is_admin

    if not is_admin_or_reseller:
        return actor_id

    if not requested_user_id:
        raise OwnerAssignmentError(
            f"Debes seleccionar el usuario propietario de {resource_label}.", 400)

    if not owner_exists:
        raise OwnerAssignmentError("Usuario propietario no encontrado", 404)

    if owner_is_admin:
        raise OwnerAssignmentError(
            f"No se puede asignar {resource_label} a una cuenta de administrador. "
            "Elige un usuario cliente.", 400)

    # Reseller (no admin global) solo puede asignar a sus propios clientes
    if actor_role == "reseller" and not actor_is_admin:
        if requested_user_id != actor_id and owner_parent_id != actor_id:
            raise OwnerAssignmentError(
                f"No puedes asignar {resource_label} a usuarios que no son tus clientes.", 403)

    return requested_user_id
