"""
Tests del lector de logs por fecha del monitor de correo.

Cazan el bug de la semana del 2026-07-04: el mail.log pesaba 144 MB y el lector
antiguo escaneaba desde el principio con un tope de 30 MB, así que los días del
final del fichero eran invisibles ("No hay registros de correo para esa fecha").
El lector nuevo usa búsqueda binaria por offset (el log es cronológico).
"""

import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes import mail as mail_routes
from api.routes.mail import _log_lines_for_date, _read_mail_log_for_date


def _mk_log(days: dict[str, int]) -> str:
    """Genera contenido de log cronológico: {día: nº líneas}, longitudes variadas."""
    out = []
    for day, n in sorted(days.items()):
        for i in range(n):
            out.append(f"{day}T{i % 24:02d}:00:{i % 60:02d}.000000+02:00 host "
                       f"postfix/smtpd[{i}]: evento numero {i} " + "x" * (i % 37))
    return "\n".join(out) + "\n"


def test_dia_al_final_de_un_log_grande(tmp_path):
    """El día pedido está más allá del tope de bytes → antes salía vacío."""
    p = tmp_path / "mail.log"
    p.write_text(_mk_log({"2026-07-01": 3000, "2026-07-02": 3000, "2026-07-04": 50}))
    # Tope minúsculo comparado con el fichero: aun así debe encontrar el día 4
    lines = _log_lines_for_date(str(p), "2026-07-04", max_bytes=100_000)
    assert len(lines) == 50
    assert all(l.startswith("2026-07-04") for l in lines)


def test_dia_primero_intermedio_y_ausente(tmp_path):
    p = tmp_path / "mail.log"
    p.write_text(_mk_log({"2026-07-01": 7, "2026-07-02": 13, "2026-07-03": 5}))
    assert len(_log_lines_for_date(str(p), "2026-07-01", 10_000_000)) == 7
    assert len(_log_lines_for_date(str(p), "2026-07-02", 10_000_000)) == 13
    assert len(_log_lines_for_date(str(p), "2026-07-03", 10_000_000)) == 5
    assert _log_lines_for_date(str(p), "2026-06-15", 10_000_000) == []
    assert _log_lines_for_date(str(p), "2026-08-01", 10_000_000) == []


def test_dia_que_desborda_el_tope_conserva_las_ultimas(tmp_path):
    """Si un día pesa más que max_bytes, se guardan las líneas RECIENTES."""
    p = tmp_path / "mail.log"
    p.write_text(_mk_log({"2026-07-03": 2000}))
    lines = _log_lines_for_date(str(p), "2026-07-03", max_bytes=20_000)
    assert 0 < len(lines) < 2000
    # La última línea del día debe estar (se recorta por el principio)
    assert lines[-1].startswith("2026-07-03") and "evento numero 1999" in lines[-1]


def test_gz(tmp_path):
    p = tmp_path / "mail.log.2.gz"
    with gzip.open(p, "wt") as f:
        f.write(_mk_log({"2026-06-20": 9, "2026-06-21": 4}))
    assert len(_log_lines_for_date(str(p), "2026-06-21", 10_000_000)) == 4


def test_dia_repartido_entre_activo_y_rotado(tmp_path, monkeypatch):
    """Tras la rotación, un día puede quedar mitad en .1 y mitad en el activo:
    deben unirse en orden cronológico (rotado primero)."""
    base = tmp_path / "mail.log"
    old = tmp_path / "mail.log.1"
    old.write_text(_mk_log({"2026-07-03": 4}) +
                   "2026-07-04T00:00:01.0+02:00 host postfix/x[1]: en el rotado\n")
    base.write_text("2026-07-04T10:00:00.0+02:00 host postfix/x[2]: en el activo\n")
    monkeypatch.setattr(mail_routes, "_MAIL_LOGS", [str(base)])
    lines = _read_mail_log_for_date("2026-07-04")
    assert len(lines) == 2
    assert "en el rotado" in lines[0] and "en el activo" in lines[1]
