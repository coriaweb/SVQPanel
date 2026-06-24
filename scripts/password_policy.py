"""
Política de contraseñas del panel: validación y generación.

Funciones PURAS (sin I/O) para que sean fáciles de testear y de usar tanto en la
API (forzar la política) como — replicando la misma lógica — en el frontend.

La política se define con un dict:
    {"min_length": 12, "require_upper": True, "require_lower": True,
     "require_digit": True, "require_symbol": False}
"""
import secrets
import string

# Símbolos permitidos (evitamos ambiguos tipo comillas que rompen shells/SQL).
SYMBOLS = "!@#$%&*()-_=+[]{}.,?"

DEFAULT_POLICY = {
    "min_length": 12,
    "require_upper": True,
    "require_lower": True,
    "require_digit": True,
    "require_symbol": False,
}


def normalize_policy(raw: dict | None) -> dict:
    """Completa una política parcial con los valores por defecto y sanea tipos."""
    p = dict(DEFAULT_POLICY)
    if raw:
        for k in p:
            if k in raw and raw[k] is not None:
                p[k] = raw[k]
    # min_length con suelo razonable (nunca menos de 6 aunque el admin lo baje).
    try:
        p["min_length"] = max(6, int(p["min_length"]))
    except (TypeError, ValueError):
        p["min_length"] = DEFAULT_POLICY["min_length"]
    for k in ("require_upper", "require_lower", "require_digit", "require_symbol"):
        p[k] = bool(p[k])
    return p


def policy_from_settings(settings) -> dict:
    """Extrae el dict de política desde el objeto Settings (BD)."""
    return normalize_policy({
        "min_length": getattr(settings, "pwd_min_length", None),
        "require_upper": getattr(settings, "pwd_require_upper", None),
        "require_lower": getattr(settings, "pwd_require_lower", None),
        "require_digit": getattr(settings, "pwd_require_digit", None),
        "require_symbol": getattr(settings, "pwd_require_symbol", None),
    })


def load_policy(db) -> dict:
    """Carga la política vigente desde la BD (o la de por defecto si falla)."""
    try:
        from api.models.models_settings import Settings
        s = db.query(Settings).first()
        if s:
            return policy_from_settings(s)
    except Exception:
        pass
    return dict(DEFAULT_POLICY)


def enforce_or_400(password: str, db) -> None:
    """Valida contra la política de la BD; lanza HTTP 400 si no cumple.

    Pensado para usar en los endpoints de la API que establecen contraseñas.
    """
    errors = validate_password(password, load_policy(db))
    if errors:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="La contraseña no cumple la política: " + "; ".join(errors),
        )


def validate_password(password: str, policy: dict | None = None) -> list[str]:
    """Devuelve la lista de incumplimientos (vacía = la contraseña es válida)."""
    p = normalize_policy(policy)
    errors = []
    if not password or len(password) < p["min_length"]:
        errors.append(f"Debe tener al menos {p['min_length']} caracteres")
    if p["require_upper"] and not any(c.isupper() for c in password):
        errors.append("Debe incluir al menos una mayúscula")
    if p["require_lower"] and not any(c.islower() for c in password):
        errors.append("Debe incluir al menos una minúscula")
    if p["require_digit"] and not any(c.isdigit() for c in password):
        errors.append("Debe incluir al menos un número")
    if p["require_symbol"] and not any(c in SYMBOLS for c in password):
        errors.append("Debe incluir al menos un símbolo")
    return errors


def is_valid(password: str, policy: dict | None = None) -> bool:
    return not validate_password(password, policy)


def generate_password(policy: dict | None = None, length: int | None = None) -> str:
    """Genera una contraseña aleatoria (CSPRNG) que CUMPLE la política.

    Garantiza al menos un carácter de cada clase requerida y rellena el resto con
    el conjunto permitido; baraja para no dejar las clases obligatorias al inicio.
    """
    p = normalize_policy(policy)
    n = max(length or p["min_length"], p["min_length"])
    # Conjuntos según política. Siempre incluimos letras para legibilidad.
    pools = []
    required = []
    if p["require_lower"]:
        pools.append(string.ascii_lowercase); required.append(string.ascii_lowercase)
    if p["require_upper"]:
        pools.append(string.ascii_uppercase); required.append(string.ascii_uppercase)
    if p["require_digit"]:
        pools.append(string.digits); required.append(string.digits)
    if p["require_symbol"]:
        pools.append(SYMBOLS); required.append(SYMBOLS)
    # Si la política no exige nada, usamos un conjunto sano por defecto.
    if not pools:
        pools = [string.ascii_letters, string.digits]
    alphabet = "".join(pools)

    # Un carácter garantizado por cada clase requerida.
    chars = [secrets.choice(group) for group in required]
    # Rellenar hasta n.
    while len(chars) < n:
        chars.append(secrets.choice(alphabet))
    # Barajar con CSPRNG (no usar random.shuffle).
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    pwd = "".join(chars)
    # Por construcción cumple, pero por seguridad reintenta si algún azar raro falla.
    if not is_valid(pwd, p):
        return generate_password(p, n)
    return pwd
