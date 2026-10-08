"""Consumo de CPU/RAM por dominio: muestreador de /proc, log de FPM y agregación."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import domain_resources as dr
from api.routes.domain_resources import build_series


def _proc(root, pid, comm, cmd, utime, stime, start, pss_kb):
    d = root / str(pid)
    d.mkdir(exist_ok=True)
    # campos tras ")": state(0) ... utime(11) stime(12) ... starttime(19)
    rest = ["S"] + ["0"] * 10 + [str(utime), str(stime)] + ["0"] * 6 + [str(start)] + ["0"] * 5
    (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(rest))
    (d / "cmdline").write_bytes(cmd.encode() + b"\0" * 20)
    (d / "smaps_rollup").write_text(f"Rss: {pss_kb * 3} kB\nPss: {pss_kb} kB\n")


@pytest.fixture
def proc(tmp_path):
    root = tmp_path / "proc"
    root.mkdir()
    return root


def test_pool_name():
    assert dr.pool_name("mi-web.example.com") == "svqpanel_mi_web_example_com"


def test_scan_cuenta_deltas_y_procesos_nuevos(proc, tmp_path):
    s = dr.ResourceSampler(proc_dir=str(proc), log_glob=str(tmp_path / "none*.log"))
    _proc(proc, 10, "php-fpm8.4", "php-fpm: master process (/etc/php/8.4/fpm/php-fpm.conf)", 900, 100, 1, 9000)
    _proc(proc, 11, "php-fpm8.4", "php-fpm: pool svqpanel_uno_com", 500, 100, 5, 40000)
    _proc(proc, 12, "nginx", "nginx: worker process", 999, 999, 5, 1000)
    s.scan()                       # 1ª pasada: solo línea base, la CPU vieja no cuenta
    acc, scans = s.take_bucket()
    assert scans == 1 and acc["svqpanel_uno_com"]["ticks"] == 0
    assert acc["svqpanel_uno_com"]["mem_max_kb"] == 40000      # PSS, no RSS
    assert set(acc) == {"svqpanel_uno_com"}                     # ni el master ni nginx

    _proc(proc, 11, "php-fpm8.4", "php-fpm: pool svqpanel_uno_com", 530, 120, 5, 50000)  # +50
    _proc(proc, 13, "php-fpm8.4", "php-fpm: pool svqpanel_uno_com", 20, 5, 77, 30000)    # nuevo: +25
    _proc(proc, 14, "php-fpm8.5", "php-fpm: pool svqpanel_dos_es", 7, 3, 80, 10000)      # nuevo: +10
    s.scan()
    acc, scans = s.take_bucket()
    assert acc["svqpanel_uno_com"]["ticks"] == 75
    assert acc["svqpanel_uno_com"]["procs_max"] == 2
    assert acc["svqpanel_uno_com"]["mem_max_kb"] == 80000
    assert acc["svqpanel_dos_es"]["ticks"] == 10

    # pid reutilizado por otro proceso (otro starttime) → cuenta como nuevo
    _proc(proc, 11, "php-fpm8.4", "php-fpm: pool svqpanel_uno_com", 4, 1, 999, 1000)
    s.scan()
    acc, _ = s.take_bucket()
    assert acc["svqpanel_uno_com"]["ticks"] == 5


def test_log_max_children_con_rotacion(tmp_path):
    log = tmp_path / "php8.4-fpm.log"
    log.write_text("[07-Oct-2026 12:22:27] WARNING: [pool svqpanel_uno_com] server reached max_children setting (10)\n")
    s = dr.ResourceSampler(proc_dir=str(tmp_path), log_glob=str(tmp_path / "php*-fpm.log"))
    s.scan_logs()                  # arranca desde el final: lo antiguo no cuenta
    assert s.take_bucket()[0] == {}
    with open(log, "a") as f:
        f.write("[08-Oct-2026 02:16:25] WARNING: [pool svqpanel_uno_com] server reached max_children setting (10), consider raising it\n"
                "[08-Oct-2026 02:16:26] WARNING: [pool svqpanel_dos_es] server reached pm.max_children setting (5)\n"
                "[08-Oct-2026 02:16:27] NOTICE: otra cosa\n")
    s.scan_logs()
    acc, _ = s.take_bucket()
    assert acc["svqpanel_uno_com"]["hits"] == 1 and acc["svqpanel_dos_es"]["hits"] == 1
    log.write_text("[08-Oct-2026 03:00:00] WARNING: [pool svqpanel_uno_com] server reached max_children setting (10)\n")  # rotado
    s.scan_logs()
    assert s.take_bucket()[0]["svqpanel_uno_com"]["hits"] == 1


def _row(ts, cpu=0.0, mem=0.0, mem_max=0.0, procs=0, hits=0):
    return SimpleNamespace(ts=datetime.utcfromtimestamp(ts), cpu_seconds=cpu, mem_avg_mb=mem,
                           mem_max_mb=mem_max, procs_max=procs, maxchildren_hits=hits)


def test_build_series_rellena_huecos_y_resume(monkeypatch):
    monkeypatch.setattr(dr, "_NCPU", 4)
    start, end = 1_800_000_000 // 3600 * 3600, 1_800_000_000 // 3600 * 3600 + 7200
    rows = [_row(start, cpu=120, mem=100, mem_max=150, procs=3),      # 120s CPU en 5 min, 4 núcleos → 10%
            _row(start + 300, cpu=0, mem=50, mem_max=60, procs=1, hits=2)]
    out = build_series(rows, start, end, 3600)
    p = out["points"]
    assert len(p) == 2 and p[1]["cpu"] == 0 and p[1]["mem"] == 0       # hora sin filas = 0
    assert p[0]["cpu"] == round(120 / 3600 / 4 * 100, 2)
    assert p[0]["mem"] == round(150 / 12, 1)                            # media sobre los 12 slots
    s = out["summary"]
    assert s["cpu_peak"] == 10.0 and s["mem_peak"] == 150 and s["hits"] == 2 and s["procs_peak"] == 3


# ── Endpoints (BD SQLite) ───────────────────────────────────────────────────
from tests.test_user_admin_protection import db, _add  # noqa: E402,F401
from api.models.models_domain import Domain  # noqa: E402
from api.models.models_domain_resources import DomainResourceSample  # noqa: E402
from api.routes import domain_resources as R  # noqa: E402


def test_endpoints(db, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(dr, "_NCPU", 4)
    admin = _add(db, 1, "root1", role="admin", is_admin=True)
    c1 = _add(db, 5, "c1"); c2 = _add(db, 6, "c2")
    db.add_all([Domain(id=1, user_id=5, domain_name="uno.com", php_version="8.4", public_html="/p"),
                Domain(id=2, user_id=6, domain_name="dos.es", php_version="8.4", public_html="/p")])
    end = int(datetime.utcnow().timestamp() // 300) * 300
    db.add_all([DomainResourceSample(domain_id=1, ts=datetime.utcfromtimestamp(end - 600), cpu_seconds=60,
                                     mem_avg_mb=100, mem_max_mb=120, procs_max=2, maxchildren_hits=1),
                DomainResourceSample(domain_id=2, ts=datetime.utcfromtimestamp(end - 300), cpu_seconds=300,
                                     mem_avg_mb=50, mem_max_mb=50, procs_max=1),
                DomainResourceSample(domain_id=1, ts=datetime.utcfromtimestamp(end - 2 * 86400), cpu_seconds=999)])
    db.commit()

    out = R.domain_resources(1, range="24h", current_user=c1, db=db)
    assert len(out["points"]) == 288
    assert out["summary"]["cpu_seconds"] == 60 and out["summary"]["hits"] == 1   # la de hace 2 días no entra
    assert out["summary"]["cpu_peak"] == 5.0          # 60 s en 5 min con 4 núcleos
    assert out["pool"]["max_children"]
    with pytest.raises(HTTPException) as e:           # dominio de otro cliente
        R.domain_resources(2, range="24h", current_user=c1, db=db)
    assert e.value.status_code == 404

    top = R.top_consumers(range="24h", limit=20, current_user=admin, db=db)["domains"]
    assert [d["domain"] for d in top] == ["dos.es", "uno.com"]
    assert top[1]["owner"] == "c1" and top[1]["hits"] == 1
