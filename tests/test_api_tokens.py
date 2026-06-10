"""
Tests del modelo ApiToken (acceso programático a la API).

Lógica pura, sin servidor ni BD: generación del secreto, hashing/verificación,
caducidad y allowlist de IPs. Cubre la parte de seguridad del token (que el hash
no sea el secreto, que un secreto alterado no valide, que un token caducado o
revocado se considere inválido, y que la allowlist de IPs deje pasar solo lo suyo).
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cargar todos los modelos para que SQLAlchemy resuelva las relationships por
# nombre (ApiToken.user -> 'User'). Es la única fuente de verdad de imports de
# modelos del proyecto; instanciar ApiToken sin esto dispara InvalidRequestError.
from api.models.database import load_all_models
load_all_models()

from api.models.models_api_token import ApiToken, TOKEN_PREFIX


# ── Generación / hashing ──
def test_generate_prefijo_y_hash_distinto_del_secreto():
    secret, token_hash, prefix = ApiToken.generate()
    assert secret.startswith(TOKEN_PREFIX)          # svq_…
    assert token_hash != secret                      # en BD nunca el secreto en claro
    assert prefix == secret[:12]                     # lo que se muestra en la UI
    assert len(token_hash) == 64                     # pbkdf2-sha256 hex


def test_matches_correcto_y_alterado():
    secret, token_hash, prefix = ApiToken.generate()
    t = ApiToken(token_hash=token_hash)
    assert t.matches(secret) is True
    assert t.matches(secret + "x") is False
    assert t.matches("svq_otrotokendistinto") is False


def test_hash_token_determinista():
    # El mismo secreto siempre da el mismo hash (necesario para buscar por hash).
    s = "svq_constante123"
    assert ApiToken.hash_token(s) == ApiToken.hash_token(s)


# ── Caducidad / revocación ──
def test_token_sin_caducidad_es_valido():
    t = ApiToken(is_revoked=False, expires_at=None)
    assert t.is_expired() is False
    assert t.is_valid() is True


def test_token_caducado_no_es_valido():
    t = ApiToken(is_revoked=False, expires_at=datetime.utcnow() - timedelta(hours=1))
    assert t.is_expired() is True
    assert t.is_valid() is False


def test_token_futuro_es_valido():
    t = ApiToken(is_revoked=False, expires_at=datetime.utcnow() + timedelta(days=1))
    assert t.is_expired() is False
    assert t.is_valid() is True


def test_token_revocado_no_es_valido():
    t = ApiToken(is_revoked=True, expires_at=None)
    assert t.is_valid() is False


# ── Allowlist de IPs ──
def test_sin_allowlist_cualquier_ip():
    t = ApiToken(allowed_ips=None)
    assert t.ip_allowed("1.2.3.4") is True
    t2 = ApiToken(allowed_ips="")
    assert t2.ip_allowed("9.9.9.9") is True


def test_allowlist_solo_deja_pasar_las_suyas():
    t = ApiToken(allowed_ips="1.2.3.4,10.0.0.1")
    assert t.ip_allowed("1.2.3.4") is True
    assert t.ip_allowed("10.0.0.1") is True
    assert t.ip_allowed("8.8.8.8") is False
    assert t.ip_allowed("") is False
