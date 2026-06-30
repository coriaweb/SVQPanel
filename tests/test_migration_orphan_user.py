"""
Test: la migración reutiliza un usuario del SO huérfano en vez de fallar.

Si un intento de migración anterior creó el usuario del sistema (useradd) pero
falló antes de registrarlo en el panel, queda huérfano: existe en el SO pero no
en la BD del panel. Reintentar debe REUTILIZARLO (resetear su contraseña), no
petar con "User already exists".
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cargar todos los modelos antes de tocar el mapper de User (las relationships
# en string, p.ej. 'Domain', necesitan que todas las clases estén registradas).
from api.models.database import load_all_models
load_all_models()

import api.routes.migrations as mig


def _run_create(user_exists_in_so):
    """Llama a _create_target_user con UserManager mockeado; devuelve el mock."""
    mgr = MagicMock()
    mgr.user_exists.return_value = user_exists_in_so

    db = MagicMock()
    # No existe en el panel.
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("scripts.user_manager.UserManager", return_value=mgr), \
         patch("scripts.utils.validate_username", return_value=True), \
         patch("scripts.utils.validate_email", return_value=True), \
         patch("scripts.password_policy.load_policy", return_value={}), \
         patch("scripts.password_policy.validate_password", return_value=[]), \
         patch("scripts.password_policy.generate_password", return_value="Genpw123!x"), \
         patch.object(mig.User, "set_password", lambda self, p: None):
        mig._create_target_user(db, "institut", "a@b.com", None)
    return mgr


def test_usuario_huerfano_en_so_se_reutiliza():
    mgr = _run_create(user_exists_in_so=True)
    # NO debe crear (ya existe); debe resetear la contraseña.
    mgr.create_user.assert_not_called()
    mgr.change_password.assert_called_once()


def test_usuario_nuevo_se_crea_normal():
    mgr = _run_create(user_exists_in_so=False)
    mgr.create_user.assert_called_once()
    mgr.change_password.assert_not_called()
