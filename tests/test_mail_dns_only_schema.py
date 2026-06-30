"""
Tests del flag mail_dns_only en los schemas de dominio.

Un dominio "solo correo/DNS" no aloja la web aquí (su registro A apunta a otro
servidor): se usa para clientes que solo quieren el correo y/o la zona DNS. El
flag debe viajar en la creación y devolverse en la respuesta.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.schemas.domain_schemas import DomainCreate, DomainResponse


def test_create_acepta_mail_dns_only():
    d = DomainCreate(user_id=1, domain_name="dafer.es", mail_dns_only=True,
                     dns_enabled=True, mail_enabled=True)
    assert d.mail_dns_only is True
    # PHP no es obligatorio para este caso (tiene default).
    assert d.php_version == "8.2"


def test_create_default_es_false():
    d = DomainCreate(user_id=1, domain_name="ejemplo.com")
    assert d.mail_dns_only is False


def test_response_expone_mail_dns_only():
    r = DomainResponse(id=1, user_id=1, domain_name="dafer.es",
                       php_version="8.2", mail_dns_only=True)
    assert r.mail_dns_only is True
