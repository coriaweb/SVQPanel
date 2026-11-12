"""PUT /domains/{id}: redirect_to y custom_docroot van tal cual al vhost nginx
(`return 301 <url>$request_uri;` / `root <ruta>;`) → no pueden llevar caracteres
que permitan inyectar directivas."""
import pytest
from pydantic import ValidationError

from api.schemas.domain_schemas import DomainUpdate


@pytest.mark.parametrize("url", [
    "https://ejemplo.com",
    "https://ejemplo.com/ruta?a=1&b=2#x",
    "http://sub.ejemplo.com:8080/a%20b",
])
def test_redirect_valida(url):
    assert DomainUpdate(redirect_to=url).redirect_to == url


@pytest.mark.parametrize("url", [
    "https://x.com; location / { alias /etc/; }",
    "https://x.com\n}",
    "https://x.com/{",
    'https://x.com/"',
    "https://x.com/$host",
    "ftp://x.com",
])
def test_redirect_inyeccion_rechazada(url):
    with pytest.raises(ValidationError):
        DomainUpdate(redirect_to=url)


@pytest.mark.parametrize("path", [
    "/home/a/web/x.com/public_html;",
    "/home/a/web/x.com/public_html\n  location",
    "/home/a/web/x.com/{",
    "/home/a/web/../../etc",
    "relativa",
])
def test_docroot_inyeccion_rechazada(path):
    with pytest.raises(ValidationError):
        DomainUpdate(custom_docroot=path)


@pytest.mark.parametrize("p,ok", [
    ("AhrefsBot", True), ("(semrush|mj12)bot", True), (r"bot\d+", True), ("O'Reilly", True),
    ("x\\", False), ("x\ny", False), ("a;b", False), ("a{", False), ('a"b', False),
    ("x" * 201, False), (r"ok\\", True),
])
def test_patron_user_agent(p, ok):
    from scripts.utils import is_safe_ua_pattern
    assert is_safe_ua_pattern(p) is ok


def test_custom_config_solo_admin():
    import inspect
    from api.routes import domains
    from api.dependencies import require_admin
    dep = inspect.signature(domains.update_custom_config).parameters["current_user"].default
    assert dep.dependency is require_admin


def test_docroot_vacio_borra():
    assert DomainUpdate(custom_docroot="").custom_docroot is None
