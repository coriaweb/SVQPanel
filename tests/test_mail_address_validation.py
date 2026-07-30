"""
Validación de direcciones de correo (api/schemas/mail_schemas.py).

Contexto: la validación de destinos de alias, catch-all y reenvíos usaba la regex
`^[^@]+@[^@]+\\.[^@]+$`, repetida en tres sitios. `[^@]` acepta TODO menos la
arroba: espacios, tabuladores, comas, comillas, ':' y '\\'. Y `forward_to` no
tenía validación NINGUNA.

Por qué importa: estos valores se escriben tal cual en /etc/postfix/virtual_alias
(formato «clave<TAB>valor» por línea) y en el passwd-file de Dovecot (campos
separados por ':'). Un espacio o TAB en el destino hace que Postfix lea un
destino inválido y el correo reenviado se pierda en silencio; una coma se
interpreta como separador de destinos; dos puntos rompen la línea de Dovecot.

Nota de alcance: el salto de línea NO era explotable a través de la regex (con
re.match, `$` no admite un \\n intermedio), pero forward_to no pasaba por ninguna
regex, y el importador de Hestia salta Pydantic por completo. De ahí que además
se endurezcan los escritores de ficheros.
"""
import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.schemas.mail_schemas import (validate_email_address, _validate_forward_list,
                                      _validate_mailbox_username,
                                      MailAliasCreate, MailDomainCreate,
                                      MailDomainUpdate, MailboxCreate, MailboxUpdate,
                                      MAX_LOCAL_PART, MAX_EMAIL)


# ─────────────────── direcciones válidas (no romper lo bueno) ────────────────

@pytest.mark.parametrize("addr", [
    "info@ejemplo.com",
    "juan.perez@ejemplo.com",
    "pedido+web@ejemplo.co.uk",
    "a@b.io",
    "info_ventas@sub.dominio.ejemplo.es",
    "u-1@mi-dominio.com",
])
def test_direcciones_validas_pasan(addr):
    assert validate_email_address(addr) == addr


def test_normaliza_mayusculas_y_espacios_externos():
    assert validate_email_address("  INFO@Ejemplo.COM  ") == "info@ejemplo.com"


# ──────────── caracteres que corromperían los ficheros de config ─────────────

@pytest.mark.parametrize("addr,motivo", [
    ("a b@ejemplo.com",        "espacio: Postfix leería un destino inválido"),
    ("a\tb@ejemplo.com",       "TAB: es el separador clave/valor del mapa"),
    ("a\nb@ejemplo.com",       "salto de línea: partiría la línea del mapa"),
    ("a\rb@ejemplo.com",       "retorno de carro"),
    ("a,b@ejemplo.com",        "coma: Postfix la lee como separador de destinos"),
    ('"john doe"@ejemplo.com', "quoted string RFC 5322: espacio y comillas"),
    ("a:b@ejemplo.com",        "dos puntos: rompe el passwd-file de Dovecot"),
    ("a\\b@ejemplo.com",       "backslash"),
    ("a;b@ejemplo.com",        "punto y coma"),
    ("a|b@ejemplo.com",        "pipe"),
])
def test_caracteres_peligrosos_rechazados(addr, motivo):
    with pytest.raises(ValueError):
        validate_email_address(addr)


@pytest.mark.parametrize("addr", [
    ".info@ejemplo.com",     # empieza por punto
    "info.@ejemplo.com",     # acaba en punto
    "in..fo@ejemplo.com",    # dos puntos seguidos
])
def test_puntos_invalidos_por_rfc(addr):
    """Inválidos por RFC 5321 §4.1.2 y fuente típica de rechazos remotos."""
    with pytest.raises(ValueError):
        validate_email_address(addr)


@pytest.mark.parametrize("addr", [
    "sin-arroba",
    "@ejemplo.com",
    "info@",
    "info@@ejemplo.com",
    "info@sindominio",        # sin TLD
    "info@.ejemplo.com",
    "",
    "   ",
])
def test_direcciones_malformadas_rechazadas(addr):
    with pytest.raises(ValueError):
        validate_email_address(addr)


def test_none_rechazado():
    with pytest.raises(ValueError):
        validate_email_address(None)


# ──────────────────────── longitudes del RFC 5321 ────────────────────────────

def test_parte_local_maxima():
    assert validate_email_address("a" * MAX_LOCAL_PART + "@ejemplo.com")
    with pytest.raises(ValueError, match="antes de la @"):
        validate_email_address("a" * (MAX_LOCAL_PART + 1) + "@ejemplo.com")


def test_direccion_total_maxima():
    """Antes 'a'*300 + '@e.com' pasaba la regex laxa."""
    with pytest.raises(ValueError):
        validate_email_address("a" * 300 + "@ejemplo.com")


def test_dominio_demasiado_largo():
    largo = ".".join(["a" * 60] * 5) + ".com"    # > 255
    with pytest.raises(ValueError):
        validate_email_address("info@" + largo)


# ───────────────── forward_to: lista separada por comas ─────────────────────

def test_forward_lista_valida():
    r = _validate_forward_list("uno@a.com, dos@b.com")
    assert r == "uno@a.com, dos@b.com"


def test_forward_normaliza_y_deduplica():
    """Un destino repetido duplicaría cada correo reenviado."""
    assert _validate_forward_list("A@x.com, a@x.com , b@y.com") == "a@x.com, b@y.com"


def test_forward_vacio_es_vacio():
    assert _validate_forward_list("") == ""
    assert _validate_forward_list("   ") == ""
    assert _validate_forward_list(None) is None


@pytest.mark.parametrize("valor", [
    "bueno@a.com, a b@mal.com",       # un destino con espacio
    "bueno@a.com, sin-arroba",
    'bueno@a.com, "x y"@mal.com',
    "a b@mal.com",
])
def test_forward_rechaza_si_algun_destino_es_invalido(valor):
    """Antes NINGÚN elemento se validaba: iban crudos a virtual_alias."""
    with pytest.raises(ValueError):
        _validate_forward_list(valor)


def test_forward_limita_el_numero_de_destinos():
    muchos = ", ".join(f"u{i}@x.com" for i in range(25))
    with pytest.raises(ValueError, match="Demasiados"):
        _validate_forward_list(muchos)


# ─────────────────── integración con los schemas Pydantic ───────────────────

def test_mailbox_update_valida_forward_to():
    """El hueco principal: MailboxUpdate.forward_to era Optional[str] puro."""
    with pytest.raises(ValidationError):
        MailboxUpdate(forward_to="a b@ejemplo.com")
    ok = MailboxUpdate(forward_to="dest@ejemplo.com")
    assert ok.forward_to == "dest@ejemplo.com"


def test_alias_destination_validado():
    with pytest.raises(ValidationError):
        MailAliasCreate(source="info", destination="a b@ejemplo.com")
    a = MailAliasCreate(source="Info", destination="  DEST@Ejemplo.com ")
    assert a.source == "info" and a.destination == "dest@ejemplo.com"


def test_alias_source_acepta_catch_all():
    assert MailAliasCreate(source="@", destination="d@e.com").source == "@"


def test_alias_source_rechaza_puntos_invalidos():
    """La validación de source estaba duplicada inline y sin el check de puntos."""
    with pytest.raises(ValidationError):
        MailAliasCreate(source="in..fo", destination="d@e.com")


def test_catch_all_validado_en_create_y_update():
    for cls in (MailDomainCreate, MailDomainUpdate):
        kw = {"domain_name": "ejemplo.com"} if cls is MailDomainCreate else {}
        with pytest.raises(ValidationError):
            cls(catch_all="a b@ejemplo.com", **kw)
        obj = cls(catch_all="  BUZON@Ejemplo.com ", **kw)
        assert obj.catch_all == "buzon@ejemplo.com"
        assert cls(catch_all="", **kw).catch_all is None


def test_mailbox_username_rechaza_puntos_invalidos():
    for mal in ["in..fo", ".info", "info."]:
        with pytest.raises(ValueError):
            _validate_mailbox_username(mal)
    assert _validate_mailbox_username("in.fo") == "in.fo"


def test_mailbox_create_sigue_aceptando_lo_normal():
    m = MailboxCreate(username="Info", password="Passw0rd!x")
    assert m.username == "info"


def test_autoreply_subject_sin_saltos_de_linea():
    """El asunto va a una cabecera del Sieve: un \\n inyectaría cabeceras."""
    with pytest.raises(ValidationError):
        MailboxUpdate(autoreply_subject="Fuera\nBcc: x@y.com")
    assert MailboxUpdate(autoreply_subject=" De vacaciones ").autoreply_subject \
        == "De vacaciones"
