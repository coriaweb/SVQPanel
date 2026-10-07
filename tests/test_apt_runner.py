"""apt_runner: comandos de apt y lectura del estado del trabajo en segundo plano."""
import json

from scripts import apt_runner


def test_comandos_seguros():
    up = apt_runner._build_cmd("upgrade", None)
    assert up[1] == "upgrade" and "-y" in up
    assert "Dpkg::Options::=--force-confold" in up
    assert "full-upgrade" not in up and "dist-upgrade" not in up

    one = apt_runner._build_cmd("upgrade", "nginx")
    assert one[-1] == "nginx" and "--only-upgrade" in one
    assert "--no-remove" in one          # nunca desinstalar otros paquetes
    assert "--allow-downgrades" not in one

    rep = apt_runner._build_cmd("repair", None)
    assert rep[-2:] == ["--configure", "-a"] and "--force-confold" in rep


def _job(monkeypatch, tmp_path, meta, output=None, rc=None, active=False):
    monkeypatch.setattr(apt_runner, "JOB_DIR", str(tmp_path))
    monkeypatch.setattr(apt_runner, "META", str(tmp_path / "meta.json"))
    monkeypatch.setattr(apt_runner, "LOG", str(tmp_path / "output.log"))
    monkeypatch.setattr(apt_runner, "RC", str(tmp_path / "rc"))
    monkeypatch.setattr(apt_runner, "_unit_active", lambda unit: active)
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    if output is not None:
        (tmp_path / "output.log").write_text(output)
    if rc is not None:
        (tmp_path / "rc").write_text(f"{rc}\n")


def test_sin_trabajo(monkeypatch, tmp_path):
    monkeypatch.setattr(apt_runner, "META", str(tmp_path / "no.json"))
    assert apt_runner.status() == {"exists": False, "running": False}


def test_en_curso(monkeypatch, tmp_path):
    _job(monkeypatch, tmp_path, {"kind": "upgrade", "unit": "u1"},
         output="Unpacking php8.4-xml ...\n", active=True)
    st = apt_runner.status()
    assert st["running"] is True and st["success"] is False
    assert st["returncode"] is None
    assert "Unpacking" in st["output"]


def test_terminado_ok(monkeypatch, tmp_path):
    _job(monkeypatch, tmp_path, {"kind": "upgrade", "package": None, "unit": "u1"},
         output="64 upgraded, 0 newly installed\n", rc=0)
    st = apt_runner.status()
    assert st["running"] is False and st["success"] is True


def test_bloqueado_por_desinstalar(monkeypatch, tmp_path):
    _job(monkeypatch, tmp_path, {"kind": "upgrade", "package": "mysql-common", "unit": "u1"},
         output="E: Packages need to be removed but remove is disabled.\n", rc=100)
    st = apt_runner.status()
    assert st["success"] is False and st["blocked_removal"] is True


def test_unidad_muerta_sin_rc_es_fallo(monkeypatch, tmp_path):
    # La unidad desapareció sin escribir rc (matada): no puede contar como éxito
    _job(monkeypatch, tmp_path, {"kind": "upgrade", "unit": "u1"}, output="", active=False)
    st = apt_runner.status()
    assert st["running"] is False and st["returncode"] == 1 and st["success"] is False


def test_no_arranca_dos_a_la_vez(monkeypatch, tmp_path):
    _job(monkeypatch, tmp_path, {"kind": "upgrade", "unit": "u1"}, active=True)
    res = apt_runner.start("upgrade")
    assert res["started"] is False
