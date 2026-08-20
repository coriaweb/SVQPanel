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


# ── Allowlist: IPv6 y prefijos CIDR (v0.226.0) ──
# El caso real que motivó esto: la web de gestión llamaba a la API saliendo por
# IPv6 y la allowlist, solo IPv4, la rechazaba con un 403.
IPV6_REAL = "2001:678:ff4:d48d:c525:53d9:5bda:3c5c"


def test_allowlist_admite_ipv6_exacta():
    t = ApiToken(allowed_ips=IPV6_REAL)
    assert t.ip_allowed(IPV6_REAL) is True
    assert t.ip_allowed("2001:678:ff4:d48d::1") is False


def test_ipv6_se_compara_normalizada_no_como_texto():
    """La misma IPv6 escrita de dos formas es la misma IP."""
    t = ApiToken(allowed_ips="2001:0678:0ff4:d48d:c525:53d9:5bda:3c5c")
    assert t.ip_allowed(IPV6_REAL) is True


def test_allowlist_admite_prefijo_cidr():
    """Un /64 cubre toda la subred: necesario si la IPv6 de salida rota (SLAAC)."""
    t = ApiToken(allowed_ips="2001:678:ff4:d48d::/64")
    assert t.ip_allowed(IPV6_REAL) is True
    assert t.ip_allowed("2001:678:ff4:d48d:ffff:ffff:ffff:ffff") is True
    assert t.ip_allowed("2001:678:ff4:ffff::1") is False


def test_cidr_ipv4():
    t = ApiToken(allowed_ips="203.0.113.0/24")
    assert t.ip_allowed("203.0.113.9") is True
    assert t.ip_allowed("203.0.114.9") is False


def test_ipv4_e_ipv6_conviven_en_la_misma_allowlist():
    t = ApiToken(allowed_ips="185.104.188.71,2001:678:ff4:d48d::/64")
    assert t.ip_allowed("185.104.188.71") is True
    assert t.ip_allowed(IPV6_REAL) is True
    assert t.ip_allowed("8.8.8.8") is False


def test_no_hay_cruce_entre_familias():
    """Una IPv4 no puede colarse por un rango IPv6 ni al revés."""
    t6 = ApiToken(allowed_ips="2001:678:ff4:d48d::/64")
    assert t6.ip_allowed("1.2.3.4") is False
    t4 = ApiToken(allowed_ips="203.0.113.0/24")
    assert t4.ip_allowed(IPV6_REAL) is False


def test_entrada_corrupta_se_ignora_sin_romper():
    """Una entrada ilegible en BD no debe autorizar ni reventar la petición."""
    t = ApiToken(allowed_ips="no-es-una-ip," + IPV6_REAL)
    assert t.ip_allowed(IPV6_REAL) is True
    t2 = ApiToken(allowed_ips="no-es-una-ip")
    assert t2.ip_allowed(IPV6_REAL) is False


def test_ip_invalida_nunca_pasa():
    t = ApiToken(allowed_ips="2001:678:ff4:d48d::/64")
    assert t.ip_allowed("") is False
    assert t.ip_allowed("no-una-ip") is False
    assert t.ip_allowed(None) is False
