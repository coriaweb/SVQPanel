"""status() de panel_updater: progreso de update.sh leído del log y del lock."""
import os

from scripts import panel_updater


LOG = (
    "[2026-10-05 03:00:01] \x1b[0;34m=== SVQPanel Update — v0.1.0 — 2026-10-05 03:00:01 ===\x1b[0m\n"
    "[2026-10-05 03:00:04] \x1b[0;32m=== Update completado: v0.1.0 (sin cambio de versión) ===\x1b[0m\n"
    "[2026-10-07 14:47:58] \x1b[0;34m=== SVQPanel Update — v0.1.0 — 2026-10-07 14:47:58 ===\x1b[0m\n"
    "[2026-10-07 14:48:00] \x1b[1;33m→ Frontend cambió — reconstruyendo...\x1b[0m\n"
    "dist/assets/index-abc.js   196.26 kB\n"
)


def _patch(monkeypatch, tmp_path, log_text, lock_pid=None):
    log = tmp_path / "update.log"
    log.write_text(log_text, encoding="utf-8")
    lock = tmp_path / "update.lock"
    if lock_pid is not None:
        lock.write_text(str(lock_pid))
    monkeypatch.setattr(panel_updater, "UPDATE_LOG", str(log))
    monkeypatch.setattr(panel_updater, "UPDATE_LOCK", str(lock))


def test_solo_la_ultima_ejecucion_y_sin_ansi_ni_salida_npm(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, LOG, lock_pid=os.getpid())
    st = panel_updater.status()
    assert st["running"] is True
    assert st["started"] == "2026-10-07 14:47:58"
    assert st["completed"] is False
    assert len(st["steps"]) == 2
    assert all("\x1b" not in s for s in st["steps"])
    assert not any("dist/assets" in s for s in st["steps"])


def test_completado_y_lock_huerfano(monkeypatch, tmp_path):
    text = LOG + "[2026-10-07 14:48:16] === Update completado: v0.1.0 → v0.2.0 ===\n"
    _patch(monkeypatch, tmp_path, text, lock_pid=999999999)
    st = panel_updater.status()
    assert st["running"] is False
    assert st["completed"] is True
    assert st["failed"] is False


def test_fallo_y_sin_log(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, LOG + "[2026-10-07 14:48:01]   ✗ 0200-x FALLÓ\n")
    assert panel_updater.status()["failed"] is True
    monkeypatch.setattr(panel_updater, "UPDATE_LOG", str(tmp_path / "no-existe.log"))
    st = panel_updater.status()
    assert st["steps"] == [] and st["started"] is None
