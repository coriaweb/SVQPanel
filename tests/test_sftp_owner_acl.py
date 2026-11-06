"""Subcuentas SFTP: la web (owner) debe poder escribir en lo que sube la subcuenta
(social.beyuri.com: «no deja escribir en uploads/2026/11» aunque estuviera a 777)."""
from scripts import sftp_account_manager as S


def test_grant_owner_access_solo_lo_de_la_subcuenta(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(S, "_run", lambda cmd, **k: calls.append(cmd) or (0, "", ""))
    ok, _ = S.grant_owner_access("beyuric", "beyuric_social", str(tmp_path))
    assert ok
    # ACL por defecto en TODAS las carpetas (lo nuevo nace escribible por la web)
    assert calls[0] == ["find", str(tmp_path), "-xdev", "-type", "d", "!", "-user", "root",
                        "-exec", "setfacl", "-d", "-m", "u:beyuric:rwX", "{}", "+"]
    # Acceso SOLO a lo que creó la subcuenta (no se amplía nada más)
    assert calls[1] == ["find", str(tmp_path), "-xdev", "-user", "beyuric_social",
                        "-exec", "setfacl", "-m", "u:beyuric:rwX", "{}", "+"]


def test_grant_owner_access_target_inexistente(monkeypatch):
    monkeypatch.setattr(S, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe ejecutar")))
    assert S.grant_owner_access("u", "u_x", "/no/existe")[0] is False


def test_create_account_da_escritura_a_la_web():
    import inspect
    src = inspect.getsource(S.create_account)
    assert "grant_owner_access(owner, username, target)" in src
