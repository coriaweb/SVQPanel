"""
El helper client_ip() NO debe confiar en cabeceras que el cliente controla.

Contexto: nuestro nginx CONCATENA la X-Forwarded-For (usa
$proxy_add_x_forwarded_for), no la reemplaza. Si el cliente envía
`X-Forwarded-For: 1.2.3.4`, el backend recibe "1.2.3.4, <ip_real>". Leer el
PRIMER valor (lo que hacíamos hasta v0.222.1) devolvía la IP elegida por el
atacante, lo que permitía saltarse el rate-limit de login y la allowlist de IPs
de los API tokens.

Equivalente al fix de HestiaCP "Stop trusting unauthenticated proxy headers"
(hestiacp#5273).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.utils.client_ip import client_ip


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Mímica mínima de starlette.Request: headers case-insensitive + client."""

    def __init__(self, headers=None, client_host="9.9.9.9"):
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = _FakeClient(client_host) if client_host else None

    @property
    def headers(self):
        return self._headers


ATACANTE = "9.9.9.9"      # IP real de la conexión (la que añade nuestro nginx)
FALSA = "1.2.3.4"         # IP que el atacante intenta hacer pasar por suya


def test_no_usa_el_primer_valor_del_xff_falsificado():
    """El caso del ataque: XFF spoofeada + la real concatenada por nginx."""
    req = _FakeRequest({"X-Forwarded-For": f"{FALSA}, {ATACANTE}"})
    assert client_ip(req) == ATACANTE


def test_x_real_ip_tiene_prioridad_sobre_el_xff():
    """nginx fija X-Real-IP con $remote_addr, sobrescribiendo al cliente."""
    req = _FakeRequest({
        "X-Real-IP": ATACANTE,
        "X-Forwarded-For": f"{FALSA}, {ATACANTE}",
    })
    assert client_ip(req) == ATACANTE


def test_cadena_de_proxies_devuelve_el_ultimo_salto():
    """Con varios valores, el fiable es el último (lo puso nuestro nginx)."""
    req = _FakeRequest({"X-Forwarded-For": f"{FALSA}, 8.8.8.8, {ATACANTE}"})
    assert client_ip(req) == ATACANTE


def test_sin_cabeceras_usa_la_ip_de_la_conexion():
    assert client_ip(_FakeRequest({})) == ATACANTE


def test_x_real_ip_vacia_no_tapa_el_fallback():
    """Una X-Real-IP en blanco no debe devolverse como IP válida."""
    req = _FakeRequest({"X-Real-IP": "   ",
                        "X-Forwarded-For": f"{FALSA}, {ATACANTE}"})
    assert client_ip(req) == ATACANTE


def test_xff_solo_con_comas_cae_a_la_conexion():
    assert client_ip(_FakeRequest({"X-Forwarded-For": " , , "})) == ATACANTE


def test_sin_request_ni_client_devuelve_none():
    assert client_ip(None) is None
    assert client_ip(_FakeRequest({}, client_host=None)) is None


def test_los_tres_modulos_comparten_el_mismo_helper():
    """auth_log y security_audit deben re-exportar, no reimplementar: si alguien
    vuelve a copiar la versión insegura, este test lo caza."""
    from api.utils.auth_log import client_ip as desde_auth_log
    from api.utils.security_audit import client_ip as desde_audit

    assert desde_auth_log is client_ip
    assert desde_audit is client_ip
