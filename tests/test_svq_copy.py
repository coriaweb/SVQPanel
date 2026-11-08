"""
Migrador SVQPanel → SVQPanel, fase 3: copia de datos (rsync de /home, BDs en
streaming, permisos, verificación). Sin red: comandos inspeccionados y procesos
locales que hacen de origen/destino.
"""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import svq_copy as C

PY = sys.executable


def test_rsync_con_contrasena():
    r = C.Remote({"host": "203.0.113.10", "password": "secreta"})
    argv = r.rsync_home("marta")
    assert argv[:3] == ["sshpass", "-e", "rsync"]
    assert "-aHAX" in argv and "--delete" in argv
    assert "--numeric-ids" not in argv          # los UID cambian: mapear por NOMBRE
    assert argv[-2:] == ["root@203.0.113.10:/home/marta/", "/home/marta/"]
    ex = [argv[i + 1] for i, a in enumerate(argv) if a == "--exclude"]
    assert ex == ["/web/*/logs/", "/web/*/tmp/"]
    assert "secreta" not in " ".join(argv)       # la contraseña va por entorno
    assert r.env()["SSHPASS"] == "secreta"


def test_rsync_con_clave_sin_sshpass():
    with C.Remote({"host": "203.0.113.10", "key": "-----BEGIN KEY-----", "port": 2222}) as r:
        argv = r.rsync_home("marta")
        assert argv[0] == "rsync"
        e = argv[argv.index("-e") + 1]
        assert "-i " in e and "-p 2222" in e
        keyfile = r.keyfile
    import os
    assert not os.path.exists(keyfile)          # la clave temporal se borra


def test_copy_home_codigos_de_rsync():
    r = C.Remote({"host": "h"})
    out = "Number of regular files transferred: 1,234\nTotal transferred file size: 5.678.901 bytes\n"
    ok = lambda rc: (lambda *a, **k: SimpleNamespace(returncode=rc, stdout=out, stderr="boom"))
    assert C.copy_home(r, "marta", runner=ok(0)) == {"files": 1234, "bytes": 5678901, "vanished": False}
    assert C.copy_home(r, "marta", runner=ok(24))["vanished"] is True   # correo que entra: normal
    with pytest.raises(C.CopyError, match="rsync falló"):
        C.copy_home(r, "marta", runner=ok(23))
    with pytest.raises(C.CopyError):
        C.copy_home(r, "../etc", runner=ok(0))


def test_permisos_y_quota_del_correo(monkeypatch):
    # pwd no existe en Windows: módulo falso (en Linux sustituye al real)
    monkeypatch.setitem(sys.modules, "pwd",
                        SimpleNamespace(getpwnam=lambda u: SimpleNamespace(pw_uid=1042)))
    calls = []
    C.fix_after_copy("marta", ["ejemplo.es"], True, runner=lambda cmd, **k: calls.append(cmd))
    assert ["chgrp", "www-data", "/home/marta/web/ejemplo.es"] in calls
    assert ["chown", "www-data:www-data", "/home/marta/web/ejemplo.es/tmp"] in calls
    assert ["chattr", "-R", "-p", "1042", "+P", "/home/marta/mail"] in calls


def _fake_popen(src_code, dst_code, sink):
    """Sustituye ssh+dump y mariadb por dos procesos Python reales en tubería."""
    def popen(argv, **kw):
        if "--default-character-set=utf8mb4" in argv and argv[-1] == "marta_wp":
            code = f"import sys; data=sys.stdin.read(); open(r'{sink}','w').write(data); sys.exit({dst_code})"
        else:
            assert argv[0] in ("sshpass", "ssh") and "-C" in argv     # comprimido por SSH
            assert "mariadb-dump" in argv[-1] and "--single-transaction" in argv[-1]
            code = f"import sys; sys.stdout.write('CREATE TABLE t (a int);\\n'*1000); sys.exit({src_code})"
        kw.pop("env", None)
        return subprocess.Popen([PY, "-c", code], **kw)
    return popen


def test_bd_en_streaming(tmp_path):
    sink = tmp_path / "importado.sql"
    sql = []
    C.copy_database(C.Remote({"host": "h", "password": "x"}), "marta_wp",
                    popen=_fake_popen(0, 0, sink), local_sql=sql.append, mariadb_bin="mariadb")
    assert sql == ["DROP DATABASE IF EXISTS `marta_wp`;",
                   "CREATE DATABASE `marta_wp` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"]
    assert sink.read_text().count("CREATE TABLE") == 1000


def test_bd_fallo_en_cada_lado(tmp_path):
    r = C.Remote({"host": "h"})
    with pytest.raises(C.CopyError, match="volcar en el origen"):
        C.copy_database(r, "marta_wp", popen=_fake_popen(3, 0, tmp_path / "a"),
                        local_sql=lambda s: None, mariadb_bin="mariadb")
    with pytest.raises(C.CopyError, match="importar en el destino"):
        C.copy_database(r, "marta_wp", popen=_fake_popen(0, 1, tmp_path / "b"),
                        local_sql=lambda s: None, mariadb_bin="mariadb")
    with pytest.raises(C.CopyError):
        C.copy_database(r, "x`; DROP DATABASE mysql; --", local_sql=lambda s: None)


def test_verificacion_compara_origen_y_destino():
    r = C.Remote({"host": "h"})
    web = "/home/marta/web/ejemplo.es/public_html"
    mail = "/home/marta/mail/ejemplo.es"

    def runner(cmd, **k):
        remote = cmd[0] in ("ssh", "sshpass")
        text = cmd[-1]
        if "information_schema" in text:
            out = "wp_posts\nwp_options\n"
        elif "UNION ALL" in text:
            out = "wp_posts\t120\nwp_options\t300\n"
        elif remote:
            out = f"{web}\t500\t9000\n{mail}\t80\t4000\n"
        else:
            out = f"{web}\t500\t9000\n{mail}\t78\t3900\n"     # 2 correos entraron después
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    v = C.verify(r, "marta", ["ejemplo.es"], ["ejemplo.es"], ["marta_wp"], runner=runner,
                 local_rows=lambda sql: [["wp_posts", "120"], ["wp_options", "299"]])
    assert v["web"][0]["same"] is True
    assert v["mail"][0]["same"] is False                 # informa, pero no tumba la verificación
    assert v["db"][0]["diff"] == [{"table": "wp_options", "src": "300", "dst": "299"}]
    assert v["ok"] is False                              # la BD sí cuenta


def test_run_copy_sigue_tras_un_fallo(monkeypatch):
    from scripts.hestia_import import ImportReport
    monkeypatch.setattr(C, "copy_home", lambda *a, **k: (_ for _ in ()).throw(C.CopyError("red caída")))
    monkeypatch.setattr(C, "fix_after_copy", lambda *a, **k: [])
    copied = []
    monkeypatch.setattr(C, "copy_database", lambda r, name, *a, **k: copied.append(name))
    data = {"username": "marta", "tables": {
        "domains": [{"domain_name": "ejemplo.es"}],
        "client_databases": [{"db_name": "marta_wp"}, {"db_name": "marta_shop"}]}}
    rep = ImportReport()
    C.run_copy({"host": "h"}, data, rep, do_verify=False)
    assert [e["type"] for e in rep.errors] == ["copy-home"]
    assert copied == ["marta_wp", "marta_shop"]


def test_cli_migrar_exige_yes(monkeypatch, capsys):
    from api import cli
    import scripts.svq_import as I
    monkeypatch.setattr(I, "fetch_export", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe conectar")))
    assert cli.cmd_svq_migrate("203.0.113.10", "marta") == 2
    assert "--yes" in capsys.readouterr().err


def test_cli_registrado():
    import inspect
    from api import cli
    src = inspect.getsource(cli)
    for c in ('"svq_plan"', '"svq_migrate"', '"svq_resync"'):
        assert c in src
