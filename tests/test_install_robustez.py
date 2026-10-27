"""
Fallos de install.sh vistos instalando servidores Debian 13 limpios (oct 2026).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / "install.sh").read_text(encoding="utf-8")


def test_sin_password_fija_de_postgresql():
    """La contraseña de panel_user era igual en todas las instalaciones y pública."""
    for f in ("install.sh", "api/models/database.py", "scripts/panel_backup_manager.py"):
        assert "panel_password_123" not in (ROOT / f).read_text(encoding="utf-8"), f
    assert "PASSWORD '${PANEL_DB_PASS}'" in INSTALL
    assert "panel_user:${PANEL_DB_PASS}@" in INSTALL


def test_apt_espera_al_lock_de_dpkg():
    """apt-daily cogía el lock a mitad del install y set -e lo abortaba."""
    assert 'DPkg::Lock::Timeout' in INSTALL
    assert "trap _restore_apt_timers EXIT" in INSTALL


def test_fallo_del_ssl_del_panel_no_aborta_el_install():
    """Con set -e, un heredoc suelto que salía con 1 mataba el install antes del fallback."""
    m = re.search(r"python << 'PANELSSLEOF'(.*)", INSTALL)
    assert m and "|| _PANEL_SSL_RC=$?" in m.group(1)
    assert "if [[ $? -eq 0 ]]" not in INSTALL.split("PANELSSLEOF")[2][:200]


def test_puertos_de_correo_solo_con_correo():
    assert 'if [[ "$INSTALL_MAIL" != true ]]; then\n    sed -i "s|elements = { 22, 80, 443, 25,' in INSTALL
