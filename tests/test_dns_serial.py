"""
Serial SOA de las zonas DNS (scripts/dns_manager.next_serial).

Contexto: había un serial hardcodeado (2026052501, es decir 25-may-2026) como
fallback en 4 sitios distintos y como default de la columna. Una constante así
envejece: en cuanto la fecha real la supera, una zona nueva nace con un serial
del PASADO. Si esa zona ya existía en los nameservers con un serial mayor (caso
típico: migración desde Hestia), el esclavo aplica la aritmética RFC 1982, ve un
serial menor, y NO transfiere la zona (anti-rollback) — la zona se queda
congelada en ns2 mientras el master sí muestra los cambios.
"""

from datetime import datetime

from scripts.dns_manager import next_serial


def _hoy_base() -> int:
    return int(datetime.utcnow().strftime("%Y%m%d")) * 100


def test_sin_serial_previo_devuelve_el_del_dia():
    assert next_serial() == _hoy_base() + 1


def test_es_estrictamente_monotono_con_un_serial_del_dia():
    """Mismo día: incrementa el contador NN."""
    base = _hoy_base()
    assert next_serial(base + 1) == base + 2
    assert next_serial(base + 41) == base + 42


def test_un_serial_viejo_salta_al_del_dia():
    """Una zona que no se toca desde hace meses arranca en la fecha de hoy."""
    assert next_serial(2026052501) == _hoy_base() + 1


def test_nunca_devuelve_un_serial_menor_o_igual_al_actual():
    """La propiedad crítica: cualquier entrada produce una salida MAYOR.

    Incluye seriales del futuro (que existen de verdad: >99 cambios en un día
    invaden fechas futuras, y las zonas migradas traen el serial del origen).
    Si esto se rompe, el esclavo deja de transferir la zona."""
    base = _hoy_base()
    for actual in [1, 1000, 2026052501, base, base + 1, base + 99,
                   base + 500, base + 100000, 2030010199, 2147483000]:
        assert next_serial(actual) > actual, f"serial no creció para {actual}"


def test_mas_de_99_cambios_en_un_dia_sigue_creciendo():
    """Con >99 cambios el formato invade la fecha siguiente (2026072999 →
    2026073000). Se acepta: pierde la semántica de fecha pero sigue siendo
    válido y monótono, que es lo que importa para la transferencia."""
    serial = next_serial()
    for _ in range(150):
        nuevo = next_serial(serial)
        assert nuevo > serial
        serial = nuevo


def test_cabe_en_uint32_y_en_integer_de_postgres():
    """BIND exige uint32 (<= 4294967295) y la columna es INTEGER de PostgreSQL
    (<= 2147483647)."""
    assert next_serial() < 2147483647


def test_no_queda_ningun_serial_hardcodeado_en_el_codigo():
    """Regresión directa: la constante 2026052501 estaba repetida en dns.py,
    domains.py, hestia_import.py (x2) y models_dns.py. Si reaparece, alguien ha
    vuelto a introducir un serial que envejece."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    culpables = []
    for sub in ("api", "scripts"):
        for f in (raiz / sub).rglob("*.py"):
            if "2026052501" in f.read_text(encoding="utf-8", errors="ignore"):
                culpables.append(str(f.relative_to(raiz)))
    assert not culpables, f"serial hardcodeado en: {culpables}"


def test_el_bump_de_la_api_delega_en_el_helper():
    """_bump_serial de api.routes.dns debe compartir la lógica, no reimplementarla
    (estaban duplicadas y divergían: '>= base' vs 'max()')."""
    from api.routes.dns import _bump_serial
    base = _hoy_base()
    assert _bump_serial(base + 5) == next_serial(base + 5)
    assert _bump_serial(2026052501) == next_serial(2026052501)


def test_el_default_de_la_columna_es_callable_y_da_el_serial_del_dia():
    """Un default literal se congelaría en la fecha en que se escribió."""
    from api.models.models_dns import DnsZone
    default = DnsZone.__table__.c.serial.default
    assert default is not None and default.is_callable, \
        "el default de serial debe ser callable, no un literal"
    assert default.arg({}) == _hoy_base() + 1
