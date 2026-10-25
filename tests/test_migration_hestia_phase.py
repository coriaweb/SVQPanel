"""
Fase del backup de Hestia en la UI: mientras v-backup-user trabaja en el origen
se lee su log (/backup/USUARIO.log) y se muestra en qué va. Caso real: Hestia
esperando minutos a que bajara la carga antes de volcar las BDs, con la UI
congelada en "Generando el backup…" como si el panel se hubiera colgado.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import migrations as mig
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


# ── reparto de la barra: generar (0-25) · descargar (25-50) · importar (50-100) ──
def test_porcentaje_de_generacion_por_seccion():
    assert mig._hestia_backup_pct("") is None
    p_web = mig._hestia_backup_pct("-- WEB --\n2026-10-24 12:45:20 capsevilla.com\n")
    p_mail = mig._hestia_backup_pct(LOG_MAIL)
    p_db = mig._hestia_backup_pct(LOG_MAIL + "-- DB --\n")
    p_fin = mig._hestia_backup_pct(LOG_MAIL + "-- DB --\n2026-10-24 12:55:00 Runtime: 17 minutes\n")
    assert 0 < p_web < p_mail < p_db < p_fin < mig.PROGRESS_GENERATE[1]


def test_porcentaje_de_descarga():
    lo, hi = mig.PROGRESS_DOWNLOAD
    assert mig._download_pct(0, 1000) == lo
    assert lo < mig._download_pct(500, 1000) < hi
    assert mig._download_pct(5000, 1000) == hi - 1          # el .tar puede ocupar más o menos que U_DISK
    assert lo <= mig._download_pct(10**9, 0) < hi           # sin tamaño estimado


class _FakeDB:
    def __init__(self):
        self.writes = []

    def execute(self, _sql, params):
        self.writes.append((params["p"], params["d"]))

    def commit(self):
        pass

    def close(self):
        pass


def _prog(window):
    p = mig._JobProgress.__new__(mig._JobProgress)       # sin __init__: no abre sesión de BD
    p.job_id, p._db, p._total, p._done, p._detail, p._last_flush = 1, _FakeDB(), 1, 0, "", 0.0
    p._lo, p._hi = window
    p._fixed_pct = None
    return p


def test_importacion_ocupa_su_tramo():
    p = _prog((50, 99))
    p.set_total(1000)
    p.set_phase("Extrayendo el backup…")
    assert p._db.writes[-1][0] == 50                        # empieza donde acabó la descarga
    p._last_flush = 0
    p.add(500)
    assert 70 <= p._db.writes[-1][0] <= 76                  # a mitad de su tramo, no al 50 %
    p._last_flush = 0
    p.add(10_000)
    assert p._db.writes[-1][0] == 99                        # tope 99: el 100 lo pone el cierre del job


def test_subida_o_ruta_usa_toda_la_barra():
    p = _prog((0, 99))
    p.set_total(1000)
    p._last_flush = 0
    p.add(500)
    assert 48 <= p._db.writes[-1][0] <= 50


def test_set_percent_para_fases_sin_bytes():
    p = _prog(mig.PROGRESS_GENERATE)
    p.set_percent(17, "copiando las bases de datos…")
    assert p._db.writes[-1] == (17, "copiando las bases de datos…")


def test_sin_log_no_cambia_nada():
    assert _hestia_backup_phase("") is None
    assert _hestia_backup_phase("\n\n") is None
