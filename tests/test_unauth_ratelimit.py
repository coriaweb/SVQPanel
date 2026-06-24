"""
Tests del límite de correo NO autenticado (PHP/localhost) por usuario de sistema.
Verifica que rebuild_ratelimit_from_db genera el mapa sysuser con el tope
conservador correcto, sin tocar el sistema (mock de escritura/reload).
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.rspamd_manager import RspamdManager


def _mgr_capturando():
    """Instancia RspamdManager sin root, capturando los mapas escritos."""
    mgr = RspamdManager.__new__(RspamdManager)
    captured = {}
    mgr._write_map = lambda path, lines: captured.__setitem__(path, list(lines))
    mgr._reload_rspamd = lambda: None
    # Evitar que escriba el Lua/conf reales: parchear open vía un no-op temporal.
    mgr._captured = captured
    return mgr, captured


def _md(domain, send_limit=0, mailboxes=()):
    o = types.SimpleNamespace()
    o.domain_name = domain
    o.send_limit_hour = send_limit
    o.mailboxes = list(mailboxes)
    return o


def _run(mgr, mail_domains, **kw):
    # Parchear la escritura de Lua/conf (usa open) por un no-op.
    import builtins
    real_open = builtins.open
    def fake_open(path, *a, **k):
        if str(path).endswith((".lua", ".lua.tmp", ".conf", ".conf.tmp")):
            class _F:
                def __enter__(self): return self
                def __exit__(self, *x): return False
                def write(self, *_): pass
            return _F()
        return real_open(path, *a, **k)
    builtins.open = fake_open
    # os.replace sobre el tmp del lua/conf también hay que neutralizarlo.
    import os as _os
    real_replace = _os.replace
    _os.replace = lambda a, b: None
    try:
        mgr.rebuild_ratelimit_from_db(mail_domains, reload=False, **kw)
    finally:
        builtins.open = real_open
        _os.replace = real_replace


def test_sysuser_tope_por_defecto():
    mgr, cap = _mgr_capturando()
    _run(mgr, [], unauth_sysusers={"weblab94": RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR})
    lines = cap.get(RspamdManager.RATELIMIT_SYSUSER_MAP, [])
    assert any(l.startswith("weblab94 ") and "/ 1h" in l for l in lines)
    assert f"{RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR}" in " ".join(lines)


def test_default_es_conservador():
    # El tope por defecto del no-auth debe ser bajo (<= 100/h)
    assert RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR <= 100


def test_dominio_con_limite_menor_baja_el_sysuser():
    # Si el dominio de correo tiene send_limit menor que el default, el no-auth
    # del usuario se ajusta al menor (nunca por encima del default).
    mgr, cap = _mgr_capturando()
    md = _md("weblabers.com", send_limit=10)
    _run(mgr, [md],
         domain_sysuser={"weblabers.com": "weblab94"},
         unauth_sysusers={"weblab94": RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR})
    lines = cap.get(RspamdManager.RATELIMIT_SYSUSER_MAP, [])
    # 10 < 50 → debe quedar 10
    assert any(l.startswith("weblab94 10 ") for l in lines), lines


def test_sin_sysusers_mapa_vacio():
    mgr, cap = _mgr_capturando()
    _run(mgr, [])
    assert cap.get(RspamdManager.RATELIMIT_SYSUSER_MAP, []) == []
