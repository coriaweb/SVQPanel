"""
Tests del resumen de correo saliente no autenticado (build_rows): combina
límites + enviados en %/estado. Función pura, sin tocar logs ni sistema.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.outbound_mail import build_rows, accepted_hostnames


def _row(rows, user):
    return next(r for r in rows if r["user"] == user)


def test_estado_ok_por_debajo_del_80():
    rows = build_rows({"weblab94": 50}, {"weblab94": 10})
    r = _row(rows, "weblab94")
    assert r["pct"] == 20 and r["state"] == "ok"


def test_estado_warn_cerca_del_limite():
    rows = build_rows({"u": 50}, {"u": 45})  # 90%
    assert _row(rows, "u")["state"] == "warn"


def test_estado_blocked_al_alcanzar_el_limite():
    rows = build_rows({"u": 50}, {"u": 50})
    assert _row(rows, "u")["state"] == "blocked"
    rows2 = build_rows({"u": 50}, {"u": 70})  # superado
    assert _row(rows2, "u")["state"] == "blocked"


def test_usuario_sin_envios_aparece_ok():
    rows = build_rows({"weblab94": 50}, {})
    r = _row(rows, "weblab94")
    assert r["sent_last_hour"] == 0 and r["state"] == "ok"


def test_orden_mas_cargados_primero():
    rows = build_rows({"a": 50, "b": 50}, {"a": 5, "b": 49})
    # b (98%) debe ir antes que a (10%)
    assert rows[0]["user"] == "b"


def test_sin_limite_no_rompe():
    # Usuario con envíos pero sin límite configurado → pct 0, estado ok
    rows = build_rows({}, {"x": 3})
    r = _row(rows, "x")
    assert r["limit"] == 0 and r["pct"] == 0 and r["state"] == "ok"


def test_hostnames_aceptados_fqdn_y_corto():
    # Regresión del bug: el sender del log usa el FQDN, getfqdn daba el corto →
    # contaba 0. Deben aceptarse AMBOS.
    s = accepted_hostnames("svqhostpanel.svqhost.red")
    assert "svqhostpanel.svqhost.red" in s
    assert "svqhostpanel" in s


def test_hostnames_solo_corto():
    assert accepted_hostnames("svqhostpanel") == {"svqhostpanel"}


def test_recipients_top_cuenta_y_ordena():
    from scripts.outbound_mail import _top_recipients
    top = _top_recipients(["a@x.com", "a@x.com", "b@y.com"])
    # 'a@x.com' aparece 2 veces → primero
    assert top[0] == {"to": "a@x.com", "count": 2}
    assert {"to": "b@y.com", "count": 1} in top


def test_build_rows_incluye_recipients():
    rows = build_rows({"weblab94": 50}, {"weblab94": 2},
                      recipients={"weblab94": ["x@a.com", "x@a.com"]})
    r = _row(rows, "weblab94")
    assert r["recipients"][0] == {"to": "x@a.com", "count": 2}
