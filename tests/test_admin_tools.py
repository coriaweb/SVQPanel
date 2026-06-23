"""
Tests de las herramientas de admin: protección de procesos críticos y
validación de queue IDs de Postfix. Funciones puras, sin tocar el sistema.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import process_manager as pm
from scripts import postfix_queue as pq


# ── Protección de procesos críticos ──────────────────────────────────────────
def test_proteger_procesos_criticos_por_nombre():
    for name in ("postgres", "nginx", "sshd", "systemd", "mariadbd", "uvicorn", "master"):
        assert pm.is_protected(name, 5000), f"{name} debería estar protegido"


def test_proteger_pid_bajo_y_init():
    assert pm.is_protected("loquesea", 1)      # init
    assert pm.is_protected("loquesea", 150)    # PID < 300 (sistema)


def test_no_protege_proceso_de_cliente():
    # Un php-fpm de pool de cliente o un proceso normal del usuario sí se puede matar
    assert not pm.is_protected("php-fpm8.3", 8123)
    assert not pm.is_protected("node", 9001)


def test_protege_el_propio_panel():
    # El propio proceso del test/panel no debe poder matarse
    assert pm.is_protected("python3", os.getpid())


def test_kill_pid_invalido():
    ok, msg = pm.kill_process(0)
    assert not ok


# ── Validación de queue IDs de Postfix ───────────────────────────────────────
def test_qid_valido():
    assert pq._valid_qid("4abcDEF123")
    assert pq._valid_qid("A1B2C3")


def test_qid_invalido_rechaza_inyeccion():
    # No debe aceptar caracteres que permitan inyección o rutas
    assert not pq._valid_qid("")
    assert not pq._valid_qid("abc; rm -rf /")
    assert not pq._valid_qid("../etc/passwd")
    assert not pq._valid_qid("ID WITH SPACE")
    assert not pq._valid_qid("a" * 40)  # demasiado largo
