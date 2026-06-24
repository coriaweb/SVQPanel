"""
Tests del contador de correo enviado por hora (sent_last_hour / lógica pura).
Usa líneas REALES de mail.log para cazar el bug del regex que solo miraba
postfix/smtpd y no postfix/submission/smtpd (envío por 587/465).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.mail_stats import _count_sent_from_log


# Líneas reales: envío autenticado por submission (587) → entrega externa.
_SUBMISSION = [
    "2026-06-24T14:44:23.697433+02:00 svqhostpanel postfix/submission/smtpd[893269]: AA31D8A27A: client=localhost[::1], sasl_method=PLAIN, sasl_username=testsvq@weblabers.com",
    "2026-06-24T14:44:38.071628+02:00 svqhostpanel postfix/smtp[893279]: AA31D8A27A: to=<info@svqhost.com>, relay=mail.svqhost.com[185.104.188.200]:25, delay=14, dsn=2.0.0, status=sent (250 OK id=1wcMy5-003LI4-Aq)",
]

# Envío por smtps (465, wrappermode).
_SMTPS = [
    "2026-06-24T15:00:00.000000+02:00 svqhostpanel postfix/smtps/smtpd[900000]: BB11223344: client=localhost[::1], sasl_method=PLAIN, sasl_username=info@weblabers.com",
    "2026-06-24T15:00:01.000000+02:00 svqhostpanel postfix/smtp[900001]: BB11223344: to=<dest@externo.com>, relay=externo.com[1.2.3.4]:25, status=sent (250 OK)",
]


def test_cuenta_envio_por_submission_587():
    # cutoff 0 = no filtra por tiempo; el bug daba {} aquí.
    r = _count_sent_from_log(_SUBMISSION, cutoff=0)
    assert r == {"testsvq@weblabers.com": 1}


def test_cuenta_envio_por_smtps_465():
    r = _count_sent_from_log(_SMTPS, cutoff=0)
    assert r == {"info@weblabers.com": 1}


def test_filtra_por_emails_deseados():
    todas = _SUBMISSION + _SMTPS
    r = _count_sent_from_log(todas, cutoff=0, wanted={"testsvq@weblabers.com"})
    assert r == {"testsvq@weblabers.com": 1}


def test_no_cuenta_login_fallido():
    # SASL fallido con sasl_username=(unavailable) NO debe contar.
    lines = [
        "2026-06-24T14:45:20.589522+02:00 svqhostpanel postfix/smtpd[893647]: warning: unknown[77.83.39.52]: SASL LOGIN authentication failed: Invalid authentication mechanism, sasl_username=(unavailable)",
    ]
    assert _count_sent_from_log(lines, cutoff=0) == {}


def test_no_cuenta_correo_entrante_sin_auth():
    # Entrega a un buzón local desde fuera (sin sasl_username) no es "envío".
    lines = [
        "2026-06-24T14:05:43.044241+02:00 svqhostpanel postfix/virtual[876889]: 467168A239: to=<info@weblabers.com>, relay=virtual, status=sent (delivered to maildir)",
    ]
    assert _count_sent_from_log(lines, cutoff=0) == {}
