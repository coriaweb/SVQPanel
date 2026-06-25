"""
Tests del traductor de errores de v-backup-user (_explain_backup_error):
limpia el ruido de SSH y da mensajes accionables. Función pura.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.migration_helpers import explain_backup_error as _explain_backup_error


# Salida REAL observada: el Warning de SSH + el error de Hestia.
_DISABLED = (
    "Warning: Permanently added '185.104.188.34' (ED25519) to the list of known hosts.\n"
    "Error: user backup is disabled\n"
)


def test_detecta_backups_deshabilitados():
    msg = _explain_backup_error(_DISABLED, "", "tallereslema")
    assert "DESHABILITADOS" in msg
    assert "tallereslema" in msg
    # No debe colar el ruido de SSH en el mensaje final.
    assert "Permanently added" not in msg
    assert "Warning" not in msg


def test_detecta_comando_no_encontrado():
    err = "Warning: Permanently added 'x' to known hosts.\nbash: v-backup-user: command not found\n"
    msg = _explain_backup_error(err, "", "cliente1")
    assert "HestiaCP" in msg or "VestaCP" in msg


def test_detecta_usuario_inexistente():
    err = "Error: user tallereslema does not exist\n"
    msg = _explain_backup_error(err, "", "tallereslema")
    assert "no existe" in msg.lower()


def test_filtra_solo_warning_ssh():
    # Si solo está el Warning (sin error real), no devuelve el warning crudo.
    msg = _explain_backup_error(
        "Warning: Permanently added 'host' to the list of known hosts.\n", "", "u")
    assert "Permanently added" not in msg
    assert "u" in msg  # menciona el usuario en el fallback


def test_error_generico_se_conserva():
    msg = _explain_backup_error("Error: disk full on /backup", "", "u")
    assert "disk full" in msg
