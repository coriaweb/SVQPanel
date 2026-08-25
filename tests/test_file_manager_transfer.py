"""Tests de mover/copiar/comprimir del administrador de archivos.

Lo que se protege aquí es la contención: todas las operaciones tienen que
quedar encerradas en el public_html del dominio. Un symlink dentro del
dominio que apunte fuera es el caso que _safe_join() por sí solo no cubre
(valida la ruta pedida, no el destino del enlace).
"""

import os
import sys
import zipfile

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.file_manager import (  # noqa: E402
    TransferRequest,
    _assert_inside,
    _escaping_links_ignore,
    _safe_join,
    _tree_size,
    _unique_destination,
)


class _FakeDomain:
    """Lo mínimo que _resolve_dest_domain mira de un dominio."""
    def __init__(self, domain_id, user_id, public_html=""):
        self.id = domain_id
        self.user_id = user_id
        self.public_html = public_html


class _FakeUser:
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role


@pytest.fixture
def domain_root(tmp_path):
    """public_html de un dominio, y un 'fuera' que nunca debe alcanzarse."""
    root = tmp_path / "web" / "midominio.com" / "public_html"
    root.mkdir(parents=True)
    outside = tmp_path / "secreto"
    outside.mkdir()
    (outside / "passwd").write_text("root:x:0:0", encoding="utf-8")
    return os.path.realpath(str(root)), str(outside)


# ── _safe_join: path traversal clásico ────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../secreto",
    "../../secreto/passwd",
    "wp-content/../../../secreto",
    "..\\..\\secreto",
])
def test_safe_join_bloquea_traversal(domain_root, evil):
    root, _ = domain_root
    with pytest.raises(HTTPException) as exc:
        _safe_join(root, evil)
    assert exc.value.status_code == 400


def test_safe_join_trata_la_ruta_absoluta_como_relativa(domain_root):
    """'/etc/passwd' NO escapa: el lstrip('/') lo ancla dentro del dominio.

    Es el comportamiento correcto (queda en <public_html>/etc/passwd), pero
    conviene fijarlo: si alguien quitara el lstrip, os.path.join con una ruta
    absoluta descartaría la raíz y sí se escaparía.
    """
    root, _ = domain_root
    target = _safe_join(root, "/etc/passwd")
    assert target.startswith(root)


def test_safe_join_permite_ruta_interna(domain_root):
    root, _ = domain_root
    os.makedirs(os.path.join(root, "wp-content", "uploads"))
    target = _safe_join(root, "wp-content/uploads")
    assert target.startswith(root)


# ── _assert_inside: symlink que escapa ────────────────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="symlinks requieren privilegios en Windows")
def test_assert_inside_rechaza_symlink_que_escapa(domain_root):
    root, outside = domain_root
    link = os.path.join(root, "atajo")
    os.symlink(outside, link)
    # _safe_join no basta: la ruta pedida es interna, el destino no.
    with pytest.raises(HTTPException) as exc:
        _assert_inside(root, link)
    assert exc.value.status_code == 400


@pytest.mark.skipif(os.name == "nt", reason="symlinks requieren privilegios en Windows")
def test_assert_inside_acepta_symlink_interno(domain_root):
    root, _ = domain_root
    real = os.path.join(root, "uploads")
    os.makedirs(real)
    link = os.path.join(root, "atajo")
    os.symlink(real, link)
    _assert_inside(root, link)  # no debe lanzar


def test_assert_inside_acepta_ruta_normal(domain_root):
    root, _ = domain_root
    f = os.path.join(root, "index.php")
    open(f, "w").close()
    _assert_inside(root, f)


# ── copytree: el ignore descarta enlaces que salen ────────────────────────

@pytest.mark.skipif(os.name == "nt", reason="symlinks requieren privilegios en Windows")
def test_ignore_descarta_solo_los_enlaces_que_escapan(domain_root):
    root, outside = domain_root
    carpeta = os.path.join(root, "tema")
    os.makedirs(carpeta)
    open(os.path.join(carpeta, "style.css"), "w").close()
    os.symlink(outside, os.path.join(carpeta, "fuga"))
    os.symlink(root, os.path.join(carpeta, "interno"))

    ignore = _escaping_links_ignore(root)
    skipped = ignore(carpeta, os.listdir(carpeta))

    assert "fuga" in skipped          # apunta fuera → se omite
    assert "style.css" not in skipped  # archivo normal → se copia
    assert "interno" not in skipped    # enlace dentro → se copia


# ── _tree_size: no sigue enlaces (ni cuenta lo de fuera) ──────────────────

def test_tree_size_suma_archivos(domain_root):
    root, _ = domain_root
    (open(os.path.join(root, "a.txt"), "w")).write("x" * 100)
    sub = os.path.join(root, "sub")
    os.makedirs(sub)
    (open(os.path.join(sub, "b.txt"), "w")).write("y" * 50)
    assert _tree_size(root) == 150


@pytest.mark.skipif(os.name == "nt", reason="symlinks requieren privilegios en Windows")
def test_tree_size_no_sigue_symlinks(domain_root):
    root, outside = domain_root
    grande = os.path.join(outside, "grande.bin")
    with open(grande, "wb") as fh:
        fh.write(b"0" * 10_000)
    os.symlink(grande, os.path.join(root, "enlace"))
    # Cuenta el enlace, no los 10 KB de destino.
    assert _tree_size(root) < 1000


# ── _unique_destination: duplicar sin pisar ───────────────────────────────

def test_unique_destination_conserva_extension(tmp_path):
    d = str(tmp_path)
    open(os.path.join(d, "foto.jpg"), "w").close()
    resultado = _unique_destination(d, "foto.jpg")
    assert os.path.basename(resultado) == "foto (copia).jpg"


def test_unique_destination_incrementa(tmp_path):
    d = str(tmp_path)
    open(os.path.join(d, "foto.jpg"), "w").close()
    open(os.path.join(d, "foto (copia).jpg"), "w").close()
    resultado = _unique_destination(d, "foto.jpg")
    assert os.path.basename(resultado) == "foto (copia 2).jpg"


def test_unique_destination_respeta_tar_gz(tmp_path):
    d = str(tmp_path)
    open(os.path.join(d, "backup.tar.gz"), "w").close()
    resultado = _unique_destination(d, "backup.tar.gz")
    # La doble extensión se conserva entera, no queda "backup.tar (copia).gz"
    assert os.path.basename(resultado) == "backup (copia).tar.gz"


def test_unique_destination_libre_devuelve_el_nombre(tmp_path):
    resultado = _unique_destination(str(tmp_path), "nuevo.txt")
    assert os.path.basename(resultado) == "nuevo.txt"


# ── Mover/copiar entre dominios: solo del mismo propietario ───────────────

def _resolve(dest_domain_id, source_domain, current_user, visible):
    """Llama a _resolve_dest_domain con un _get_domain_or_404 simulado.

    'visible' son los dominios que el usuario puede ver segun su rol; si el
    destino no esta, se simula el 404 que devolveria la consulta filtrada.
    """
    payload = TransferRequest(paths=["x"], dest="", dest_domain_id=dest_domain_id)

    def fake_get(domain_id, db, user):
        for d in visible:
            if d.id == domain_id:
                return d
        raise HTTPException(status_code=404, detail="Dominio no encontrado o sin permisos")

    import api.routes.file_manager as fm
    original = fm._get_domain_or_404
    fm._get_domain_or_404 = fake_get
    try:
        return fm._resolve_dest_domain(payload, source_domain, None, current_user)
    finally:
        fm._get_domain_or_404 = original


def test_sin_dest_domain_usa_el_de_origen():
    origen = _FakeDomain(1, user_id=7)
    user = _FakeUser(7, "user")
    assert _resolve(None, origen, user, [origen]) is origen


def test_mismo_dominio_explicito_usa_el_de_origen():
    origen = _FakeDomain(1, user_id=7)
    user = _FakeUser(7, "user")
    assert _resolve(1, origen, user, [origen]) is origen


def test_cliente_puede_mover_entre_sus_dos_dominios():
    """El caso del cliente con dos dominios suyos: debe funcionar."""
    origen = _FakeDomain(1, user_id=7)
    destino = _FakeDomain(2, user_id=7)
    user = _FakeUser(7, "user")
    assert _resolve(2, origen, user, [origen, destino]) is destino


def test_reseller_no_puede_cruzar_entre_dos_clientes_distintos():
    """Un reseller VE ambos dominios, pero son de clientes distintos: 403.

    Cada dominio corre bajo su propio usuario del sistema; cruzarlos mezclaria
    cuentas que el aislamiento PHP mantiene separadas.
    """
    origen = _FakeDomain(1, user_id=10)   # cliente A
    destino = _FakeDomain(2, user_id=11)  # cliente B
    reseller = _FakeUser(5, "reseller")
    with pytest.raises(HTTPException) as exc:
        _resolve(2, origen, reseller, [origen, destino])
    assert exc.value.status_code == 403


def test_reseller_si_puede_entre_dominios_del_mismo_cliente():
    origen = _FakeDomain(1, user_id=10)
    destino = _FakeDomain(2, user_id=10)
    reseller = _FakeUser(5, "reseller")
    assert _resolve(2, origen, reseller, [origen, destino]) is destino


def test_admin_si_puede_cruzar_entre_cuentas():
    origen = _FakeDomain(1, user_id=10)
    destino = _FakeDomain(2, user_id=11)
    admin = _FakeUser(1, "admin")
    assert _resolve(2, origen, admin, [origen, destino]) is destino


def test_dominio_destino_ajeno_da_404_no_403():
    """Si el usuario ni siquiera ve el destino, corta antes de mirar el dueño."""
    origen = _FakeDomain(1, user_id=7)
    ajeno = _FakeDomain(99, user_id=42)
    user = _FakeUser(7, "user")
    with pytest.raises(HTTPException) as exc:
        _resolve(99, origen, user, [origen])   # 'ajeno' no es visible
    assert exc.value.status_code == 404
    assert ajeno.user_id == 42  # el dominio existe, pero no para este usuario
