"""
Fase del backup de Hestia en la UI: mientras v-backup-user trabaja en el origen
se lee su log (/backup/USUARIO.log) y se muestra en qué va. Caso real: Hestia
esperando minutos a que bajara la carga antes de volcar las BDs, con la UI
congelada en "Generando el backup…" como si el panel se hubiera colgado.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.migrations import _hestia_backup_phase

LOG_MAIL = """-- WEB --
2026-10-24 12:45:20 capsevilla.com
2026-10-24 12:45:36 capsevilla.es
2026-10-24 12:45:36 *** 2 domains ***

-- MAIL --
2026-10-24 12:45:36 capsevilla.com
"""


def test_seccion_y_elemento_en_curso():
    assert _hestia_backup_phase(LOG_MAIL) == \
        "Generando el backup en el origen: copiando el correo (capsevilla.com)…"


def test_cabecera_recien_empezada():
    assert _hestia_backup_phase(LOG_MAIL + "2026-10-24 12:45:53 *** 1 domain ***\n\n-- DB --\n") == \
        "Generando el backup en el origen: copiando las bases de datos…"


def test_espera_por_carga():
    log = LOG_MAIL + "-- DB --\n2026-10-24 12:46:53 Load Average 4\n"
    msg = _hestia_backup_phase(log)
    assert "espera a que baje la carga" in msg and "carga 4" in msg


def test_carga_ya_superada_sigue_con_la_fase():
    log = "-- DB --\n2026-10-24 12:46:53 Load Average 4\n-- USER DIRECTORIES --\n" \
          "2026-10-24 12:51:56 adding .bash_logout\n"
    assert _hestia_backup_phase(log) == \
        "Generando el backup en el origen: copiando los archivos del usuario (adding .bash_logout)…"


def test_final():
    log = "-- SUMMARY --\n2026-10-24 12:55:00 Local: /backup/capsevilla.2026-10-24_12-38-20.tar\n" \
          "2026-10-24 12:55:00 Runtime: 17 minutes\n"
    assert _hestia_backup_phase(log) == "El Hestia de origen está terminando el backup…"


def test_sin_log_no_cambia_nada():
    assert _hestia_backup_phase("") is None
    assert _hestia_backup_phase("\n\n") is None
