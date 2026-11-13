"""Subcuentas SFTP: carpeta de inicio (-d) y solo lectura (-R) en sshd."""
import os

from scripts import sftp_account_manager as sam
from scripts import sftp_manager


def test_contenido_por_subcuenta():
    c = sam.sshd_accounts_content([
        {"username": "oskarbiapi_inovpecas", "mount_name": "inovpecas-sa", "read_only": True},
        {"username": "u_dev1", "mount_name": "public_html", "read_only": False},
    ])
    assert "Match User oskarbiapi_inovpecas\n    ForceCommand internal-sftp -R -d /inovpecas-sa\n" in c
    assert "Match User u_dev1\n    ForceCommand internal-sftp -d /public_html\n" in c


def test_nombre_de_carpeta_raro_no_lleva_d():
    c = sam.sshd_accounts_content([
        {"username": "u_a", "mount_name": "mi carpeta", "read_only": True},
        {"username": "u_b", "mount_name": "100%", "read_only": False},
        {"username": "u_c", "mount_name": "..", "read_only": False},
    ])
    assert "Match User u_a\n    ForceCommand internal-sftp -R\n" in c
    assert "Match User u_b\n    ForceCommand internal-sftp\n" in c
    assert "Match User u_c\n    ForceCommand internal-sftp\n" in c


def test_usuario_no_valido_se_omite():
    c = sam.sshd_accounts_content([{"username": "x\nMatch All", "mount_name": "a"}])
    assert "Match User" not in c and "Match All" not in c


def test_se_carga_antes_que_el_bloque_del_grupo():
    # sshd lee sshd_config.d/*.conf en orden alfabético y se queda con el primer
    # ForceCommand: el de la subcuenta tiene que ir antes que el genérico.
    a = os.path.basename(sam.SSHD_ACCOUNTS_PATH)
    g = os.path.basename(sftp_manager.SSHD_SNIPPET_PATH)
    assert sorted([g, a]) == [a, g]


def test_sync_valida_y_restaura_si_sshd_t_falla(tmp_path, monkeypatch):
    path = tmp_path / "svqpanel-sftp-accounts.conf"
    path.write_text("ANTERIOR")
    monkeypatch.setattr(sam, "SSHD_ACCOUNTS_PATH", str(path))
    calls = []

    def fake_run(cmd, input_text=None, timeout=15):
        calls.append(cmd)
        return (1, "", "bad config") if cmd[:2] == ["sshd", "-t"] else (0, "", "")
    monkeypatch.setattr(sam, "_run", fake_run)
    ok, msg = sam.sync_sshd([{"username": "u_a", "mount_name": "x", "read_only": True}])
    assert not ok and "sshd -t" in msg
    assert path.read_text() == "ANTERIOR"
    assert not any("reload" in c for c in calls)


def test_sync_ok_recarga_e_idempotente(tmp_path, monkeypatch):
    path = tmp_path / "svqpanel-sftp-accounts.conf"
    monkeypatch.setattr(sam, "SSHD_ACCOUNTS_PATH", str(path))
    calls = []
    monkeypatch.setattr(sam, "_run", lambda cmd, input_text=None, timeout=15: (calls.append(cmd) or (0, "", "")))
    acc = [{"username": "u_a", "mount_name": "x", "read_only": True}]
    assert sam.sync_sshd(acc) == (True, "updated")
    assert "internal-sftp -R -d /x" in path.read_text()
    assert ["systemctl", "reload", "ssh"] in calls
    calls.clear()
    assert sam.sync_sshd(acc) == (True, "unchanged")
    assert calls == []


def test_sync_primera_vez_falla_borra_el_fichero(tmp_path, monkeypatch):
    path = tmp_path / "svqpanel-sftp-accounts.conf"
    monkeypatch.setattr(sam, "SSHD_ACCOUNTS_PATH", str(path))
    monkeypatch.setattr(sam, "_run", lambda cmd, input_text=None, timeout=15: (1, "", "x"))
    ok, _ = sam.sync_sshd([{"username": "u_a", "mount_name": "x"}])
    assert not ok and not path.exists()
