"""
Tests de la renovación de sesión (JWT del panel).

Contexto: el token de sesión dura 24 h y NO se renovaba nunca — no existía
refresh. Al cumplirse el plazo, la sesión moría a mitad de trabajo: la petición
siguiente devolvía 401 y el frontend expulsaba al login sin explicar nada, así
que el usuario lo vivía como "el panel me ha echado" o "mi contraseña ya no
vale" (visto en producción: un cliente con 13 login_failed seguidos tras
caducarle la sesión).

Ahora `POST /api/auth/refresh` re-emite el token a un usuario YA autenticado.
Lo que se prueba aquí es la parte de seguridad de esa renovación:

  - que renovar produzca un token válido y con la misma identidad,
  - que un token CADUCADO no se pueda usar para renovar (si no, la sesión sería
    eterna y el plazo de 24 h no serviría de nada),
  - que el token siga firmado: alterar el payload lo invalida.

Lógica pura sobre el modelo User, sin servidor ni BD.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import jwt
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-para-los-tests-de-refresh-0123456789")

from api.models.database import load_all_models
load_all_models()

from api.models.models_user import User
from api.utils.secret import get_secret_key


def _user(**kw):
    u = User(**{"id": 7, "username": "punctunm", "email": "c@ejemplo.com",
                "role": "user", "is_admin": False, **kw})
    return u


# ── El token que se emite es válido y conserva la identidad ──

def test_el_token_renovado_es_valido_y_mantiene_la_identidad():
    u = _user()
    nuevo = u.generate_token()
    payload = User.verify_token(nuevo)
    assert payload["sub"] == "7"
    assert payload["username"] == "punctunm"
    assert payload["role"] == "user"
    assert payload["is_admin"] is False


def test_renovar_alarga_la_caducidad():
    """El sentido de renovar es justo ese: que la sesión no muera a las 24 h."""
    u = _user()
    corto = u.generate_token(expires_hours=1)
    largo = u.generate_token(expires_hours=24)
    exp_corto = User.verify_token(corto)["exp"]
    exp_largo = User.verify_token(largo)["exp"]
    assert exp_largo > exp_corto


def test_el_token_por_defecto_dura_24h_exactas():
    """Regresión: `exp` se construía con `datetime.utcnow()` NAIVE, y PyJWT lo
    interpretaba como hora LOCAL al convertirlo a timestamp. En un servidor en
    Europe/Madrid (+02:00) el token duraba 26 h en vez de 24 (25 en invierno):
    el plazo real no era el declarado y variaba con la zona del servidor.

    Se compara contra `now(timezone.utc)` — el instante absoluto —, NO contra
    `utcnow()` naive, que es justo lo que ocultaba el fallo.
    """
    u = _user()
    payload = User.verify_token(u.generate_token())
    ahora = int(datetime.now(timezone.utc).timestamp())
    faltan = payload["exp"] - ahora
    assert 24 * 3600 - 60 <= faltan <= 24 * 3600, (
        f"el token dura {faltan / 3600:.2f} h, deberían ser 24")


# ── Un token caducado NO sirve para renovar ──

def test_token_caducado_no_valida():
    """Si un token caducado pudiera renovarse, la sesión sería ETERNA y el
    plazo de 24 h no serviría de nada. Debe obligar a iniciar sesión."""
    u = _user()
    caducado = u.generate_token(expires_hours=-1)   # ya expirado
    with pytest.raises(Exception):                   # ExpiredSignature → 401
        User.verify_token(caducado)


def test_token_justo_expirado_no_valida():
    """Frontera: exp en el pasado inmediato tampoco puede colarse."""
    secret = get_secret_key()
    payload = {"sub": "7", "username": "punctunm",
               "exp": datetime.utcnow() - timedelta(seconds=1)}
    token = jwt.encode(payload, secret, algorithm="HS256")
    with pytest.raises(Exception):
        User.verify_token(token)


# ── La firma sigue protegiendo el contenido ──

def test_token_firmado_con_otro_secreto_no_valida():
    payload = {"sub": "7", "username": "punctunm", "is_admin": True,
               "exp": datetime.utcnow() + timedelta(hours=24)}
    ajeno = jwt.encode(payload, "otro-secreto-distinto", algorithm="HS256")
    with pytest.raises(Exception):
        User.verify_token(ajeno)


def test_no_se_puede_escalar_a_admin_editando_el_payload():
    """Cambiar is_admin a mano invalida la firma: renovar no es una vía para
    ganar privilegios."""
    u = _user(is_admin=False)
    token = u.generate_token()
    cabecera, cuerpo, firma = token.split(".")
    falso = jwt.encode({"sub": "7", "username": "punctunm", "is_admin": True,
                        "exp": datetime.utcnow() + timedelta(hours=24)},
                       "secreto-inventado", algorithm="HS256")
    # Payload manipulado + firma original → no valida
    manipulado = f"{cabecera}.{falso.split('.')[1]}.{firma}"
    with pytest.raises(Exception):
        User.verify_token(manipulado)


def test_la_identidad_del_token_renovado_no_cambia_de_usuario():
    """Renovar re-emite para el MISMO usuario, nunca para otro."""
    a, b = _user(id=7, username="punctunm"), _user(id=99, username="otro")
    assert User.verify_token(a.generate_token())["sub"] == "7"
    assert User.verify_token(b.generate_token())["sub"] == "99"
