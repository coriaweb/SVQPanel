"""
Emisión SSL sin www en subdominios + destino de alertas entregable.

- Un subdominio no debe llevar www.<sub> en el cert: si resolvía al emitir y
  luego desaparecía, la renovación fallaba entera (socios.zococoria.es).
- Las alertas iban a admin@localhost y se daban por enviadas.
"""

from scripts.alerts_manager import is_deliverable_email
from scripts.ssl_manager import SSLManager


def _mgr(captured):
    m = object.__new__(SSLManager)  # sin __init__: no exige root
    m._validate_dns = lambda host, timeout=5: True  # todo "resuelve" (comodín)
    m._get_certbot_path = lambda: "/snap/bin/certbot"
    m.execute_command = lambda *a, **k: (0, "", "")

    def run(cmd, line_cb=None):
        captured.append(cmd)
        return 0, ""
    m._run_certbot = run
    return m


def _names(cmd):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "-d"]


def test_subdominio_no_lleva_www_aunque_resuelva():
    cmds = []
    _mgr(cmds).create_ssl_with_email("socios.zococoria.es", "info@svqhost.com",
                                     include_www=False)
    assert _names(cmds[0]) == ["socios.zococoria.es"]
    assert cmds[0][cmds[0].index("--cert-name") + 1] == "socios.zococoria.es"


def test_dominio_normal_sigue_llevando_www():
    cmds = []
    _mgr(cmds).create_ssl_with_email("zococoria.es", "info@svqhost.com")
    assert _names(cmds[0]) == ["zococoria.es", "www.zococoria.es"]


def test_destino_de_alertas_entregable():
    assert is_deliverable_email("info@svqhost.com")
    for bad in ("admin@localhost", "x@panel.local", "", "a@b@c.com",
                "root@svq.localdomain", "sin-arroba"):
        assert not is_deliverable_email(bad), bad
