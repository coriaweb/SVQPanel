"""
Tests de la validación de la consola WP-CLI (validate_cli_command).
No tocan el sistema: solo la lógica de admisión de comandos.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.wp_manager import validate_cli_command, WpError


def test_comando_normal_pasa():
    assert validate_cli_command("plugin list --status=active") == \
        ["plugin", "list", "--status=active"]


def test_wp_inicial_se_quita():
    assert validate_cli_command("wp core version") == ["core", "version"]


def test_comillas_se_respetan():
    args = validate_cli_command("search-replace 'https://a.com' 'https://b.com' --dry-run")
    assert args == ["search-replace", "https://a.com", "https://b.com", "--dry-run"]


def test_flags_peligrosos_bloqueados():
    for cmd in (
        "plugin list --path=/etc",
        "core version --ssh=root@otro",
        "option get siteurl --http=https://otro.com",
        "eval 'x' --require=/tmp/mal.php",
        "cli info --exec='code'",
        "db export --prompt",
        "plugin list --PATH=/etc",          # case-insensitive
    ):
        with pytest.raises(WpError):
            validate_cli_command(cmd)


def test_comandos_interactivos_bloqueados():
    for cmd in ("shell", "db cli", "wp shell", "db cli --extra"):
        with pytest.raises(WpError):
            validate_cli_command(cmd)


def test_vacios_y_multilinea_bloqueados():
    for cmd in ("", "   ", "wp", "plugin list\nrm -rf /", "x" * 3000):
        with pytest.raises(WpError):
            validate_cli_command(cmd)


def test_db_query_si_esta_permitido():
    # 'db cli' es interactivo (bloqueado) pero 'db query' con SQL inline no.
    assert validate_cli_command('db query "SELECT 1"') == ["db", "query", "SELECT 1"]
