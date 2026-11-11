"""Subcuentas SFTP: cambiar la carpeta de la jaula sin recrear la cuenta.

Origen (Oskarbi, nov 2026): el cliente movió con mv la carpeta montada. La cuenta
seguía viéndola gracias al bind-mount, pero fstab guardaba la ruta vieja y al
reiniciar habría montado una carpeta vacía o inexistente.
"""
import os

import pytest

from scripts import sftp_account_manager as S


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home" / "cli"
    (home / "web" / "dom.com" / "public_html" / "resources").mkdir(parents=True)
    (home / "web" / "dom.com" / "public_html" / "imagenes").mkdir(parents=True)
    jail = home / S.JAILS_SUBDIR / "img"
    (jail / "resources").mkdir(parents=True)
    (jail / ".ssh").mkdir()
    fstab = tmp_path / "fstab"
    old = str(home / "web" / "dom.com" / "public_html" / "resources")
    fstab.write_text(f"UUID=x / ext4 defaults 0 1\n"
                     f"{old} {jail}/resources none bind 0 0  {S.FSTAB_MARK}\n"
                     f"/otra {jail}/resources2 none bind 0 0  {S.FSTAB_MARK}\n")

    state = {"mounted": {str(jail / "resources")}, "calls": [], "fail_mount": False}

    def fake_run(cmd, input_text=None, timeout=15):
        state["calls"].append(cmd)
        if cmd[0] == "mountpoint":
            return (0 if cmd[-1] in state["mounted"] else 1), "", ""
        if cmd[0] == "umount":
            state["mounted"].discard(cmd[-1])
            return 0, "", ""
        if cmd[0] == "mount":
            if state["fail_mount"] and cmd[2] != old:
                return 32, "", "boom"
            state["mounted"].add(cmd[-1])
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(S, "_run", fake_run)
    monkeypatch.setattr(S, "owner_home", lambda owner: str(home))
    monkeypatch.setattr(S, "FSTAB", str(fstab))
    return {"home": home, "jail": str(jail), "old": old, "fstab": fstab, "state": state}


def _change(env, new):
    return S.change_target("cli", "cli_img", env["jail"], env["old"], "resources", new)


def test_cambia_montaje_fstab_y_acl(env):
    ok, msg, info = _change(env, "web/dom.com/public_html/imagenes")
    assert ok, msg
    new = str(env["home"] / "web" / "dom.com" / "public_html" / "imagenes")
    assert info == {"target_path": new, "mount_name": "imagenes"}
    new_mp = os.path.join(env["jail"], "imagenes")
    assert env["state"]["mounted"] == {new_mp}
    fstab = env["fstab"].read_text()
    assert f"{new} {new_mp} none bind" in fstab
    assert f"{env['jail']}/resources " not in fstab
    # La línea de OTRA cuenta (…/resources2) no se toca: antes se comparaba por subcadena
    assert f"{env['jail']}/resources2 " in fstab
    # El mountpoint viejo (vacío) se retira; las ACL pasan de la vieja a la nueva
    assert not os.path.exists(os.path.join(env["jail"], "resources"))
    calls = env["state"]["calls"]
    assert ["setfacl", "-R", "-x", "u:cli_img", env["old"]] in calls
    assert ["setfacl", "-R", "-m", "u:cli_img:rwX", new] in calls
    revoke = calls.index(["setfacl", "-R", "-x", "u:cli_img", env["old"]])
    assert revoke < calls.index(["setfacl", "-R", "-m", "u:cli_img:rwX", new])


def test_si_falla_el_montaje_vuelve_a_la_carpeta_vieja(env):
    env["state"]["fail_mount"] = True
    ok, msg, _ = _change(env, "web/dom.com/public_html/imagenes")
    assert not ok and "mount --bind" in msg
    assert env["state"]["mounted"] == {os.path.join(env["jail"], "resources")}
    assert f"{env['old']} {env['jail']}/resources none bind" in env["fstab"].read_text()


@pytest.mark.parametrize("ruta", ["../../etc", "/etc", f"{S.JAILS_SUBDIR}/img", "web/no-existe"])
def test_rechaza_rutas_fuera_o_invalidas(env, ruta):
    ok, _, _ = _change(env, ruta)
    assert not ok
    assert env["state"]["mounted"] == {os.path.join(env["jail"], "resources")}


def test_misma_carpeta_no_hace_nada(env):
    ok, msg, _ = _change(env, "web/dom.com/public_html/resources")
    assert ok and msg == "sin cambios"
    assert not any(c[0] in ("umount", "mount") for c in env["state"]["calls"])


def test_mount_name_no_pisa_ssh():
    assert S.mount_name_for("/home/u/.ssh") == "data"
    assert S.mount_name_for("/home/u/web/x/") == "x"
