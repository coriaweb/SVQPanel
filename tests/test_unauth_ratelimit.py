"""
Tests del límite de correo NO autenticado (PHP/localhost) por usuario de sistema.
Usan la función PURA _compute_ratelimit_lines (sin I/O): calcula las líneas de los
mapas de rate-limit a partir de la BD, sin tocar /etc/rspamd.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.rspamd_manager import RspamdManager


def _md(domain, send_limit=0, mailboxes=()):
    o = types.SimpleNamespace()
    o.domain_name = domain
    o.send_limit_hour = send_limit
    o.mailboxes = list(mailboxes)
    return o


def _sysuser_lines(mail_domains, **kw):
    _, _, sysuser = RspamdManager._compute_ratelimit_lines(mail_domains, **kw)
    return sysuser


def test_sysuser_tope_por_defecto():
    lines = _sysuser_lines([], unauth_sysusers={"weblab94": RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR})
    assert any(l.startswith("weblab94 ") and "/ 1h" in l for l in lines)
    assert f"{RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR}" in " ".join(lines)


def test_default_es_conservador():
    # El tope por defecto del no-auth debe ser MUY bajo (empuja al cliente a SMTP).
    # 10/h: un formulario ocasional pasa; una web que envía en serio toca techo.
    assert RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR == 10


def test_dominio_con_limite_menor_baja_el_sysuser():
    # Si el dominio tiene send_limit menor que el default, el no-auth del usuario
    # se ajusta al menor (nunca por encima del default).
    md = _md("weblabers.com", send_limit=10)
    lines = _sysuser_lines(
        [md],
        domain_sysuser={"weblabers.com": "weblab94"},
        unauth_sysusers={"weblab94": RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR},
    )
    assert any(l.startswith("weblab94 10 ") for l in lines), lines


def test_dominio_con_limite_alto_se_capa_al_default():
    # Un dominio con send_limit alto NO sube el no-auth por encima del default.
    md = _md("weblabers.com", send_limit=5000)
    lines = _sysuser_lines(
        [md],
        domain_sysuser={"weblabers.com": "weblab94"},
        unauth_sysusers={"weblab94": RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR},
    )
    cap = RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR
    assert any(l.startswith(f"weblab94 {cap} ") for l in lines), lines


def test_sin_sysusers_mapa_vacio():
    assert _sysuser_lines([]) == []


def test_lineas_por_dominio_y_buzon():
    mb = types.SimpleNamespace(username="info", send_limit_hour=100)
    md = _md("weblabers.com", send_limit=300, mailboxes=[mb])
    user, domain, _ = RspamdManager._compute_ratelimit_lines([md])
    assert "weblabers.com 300 / 1h" in domain
    assert "info@weblabers.com 100 / 1h" in user
