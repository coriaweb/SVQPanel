"""
Un cliente no puede crear una cuenta con el nombre de un usuario del sistema
o de un servicio que gestiona el panel (root, www-data, postfix, vmail…).

Ojo con la distinción, que es la parte sutil:
  - validate_new_username() → CREAR: formato + no reservado.
  - validate_username()     → cuentas EXISTENTES: solo formato. Si rechazara los
    reservados, un admin llamado `admin` no podría cambiar su contraseña ni ser
    borrado (delete_user/change_password validan con ella).

Equivalente al fix de HestiaCP "Added that local usernames can't be used in
Hestia" (hestiacp#5134).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import (
    RESERVED_USERNAMES,
    validate_new_username,
    validate_username,
)


@pytest.mark.parametrize("nombre", [
    "root", "www-data", "postfix", "vmail", "mysql", "postgres",
    "nobody", "sshd", "svqpanel", "bind", "clamav",
])
def test_no_se_puede_crear_una_cuenta_con_nombre_reservado(nombre):
    assert not validate_new_username(nombre)


def test_admin_no_esta_reservado():
    """install.sh permite elegir `admin` como usuario del panel (SVQ_ADMIN_USER).
    Si lo bloqueáramos, esas instalaciones no podrían recrear/migrar su admin."""
    assert validate_new_username("admin")
    assert validate_new_username("administrator")


@pytest.mark.parametrize("nombre", ["ROOT", "Www-Data", "PostFix", "VMail"])
def test_los_reservados_se_rechazan_sin_importar_mayusculas(nombre):
    """Linux distingue mayúsculas, pero `useradd Root` seguiría colisionando en
    la práctica (y confunde al panel), así que se comparan en minúsculas."""
    assert not validate_new_username(nombre)


@pytest.mark.parametrize("nombre", ["cliente1", "juan_perez", "svqhost", "_svq_a3f9"])
def test_los_nombres_normales_siguen_valiendo(nombre):
    assert validate_new_username(nombre)


@pytest.mark.parametrize("nombre", ["1user", "a", "user con espacios", "user;rm -rf", ""])
def test_el_validador_de_creacion_tambien_exige_formato_valido(nombre):
    assert not validate_new_username(nombre)


def test_las_cuentas_existentes_reservadas_siguen_siendo_gestionables():
    """REGRESIÓN: validate_username() se usa en delete_user/change_password.
    Debe seguir aceptando `admin` o el cambio de contraseña del admin rompería."""
    assert validate_username("admin")
    assert validate_username("root")


def test_create_user_rechaza_un_nombre_reservado():
    """El bloqueo está en el punto de creación real, no solo en el validador.

    Se parchea _validate_root porque UserManager exige root al instanciarse (y
    os.geteuid no existe en Windows). El nombre se valida antes de tocar el SO,
    así que no se ejecuta ningún useradd.
    """
    from unittest.mock import patch

    from scripts.user_manager import UserManager

    with patch("scripts.base.SystemManager._validate_root", return_value=None):
        with pytest.raises(ValueError, match="reserved"):
            UserManager().create_user("www-data", "test@example.com", "Passw0rd!23")


def test_la_lista_cubre_las_cuentas_de_los_servicios_que_gestionamos():
    for critico in ("root", "www-data", "vmail", "postfix", "dovecot", "mysql"):
        assert critico in RESERVED_USERNAMES
