"""
La importación de cronjobs de Hestia debe adaptar el comando a nuestro sistema:
ruta /home/viejo → /home/nuevo y la versión de PHP a la del dominio destino.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import _adapt_cron_command

INSTALLED = ["7.4", "8.0", "8.1", "8.2", "8.3"]


def test_reescribe_usuario_y_php_del_dominio():
    cmd = "/usr/bin/php8.1 /home/admin/web/socios.zococoria.es/public_html/artisan schedule:run"
    out = _adapt_cron_command(cmd, "zococori", INSTALLED,
                              {"socios.zococoria.es": "8.2"})
    assert "/home/zococori/" in out
    assert "/home/admin/" not in out
    assert "php8.2" in out and "php8.1" not in out


def test_comando_sin_php_solo_cambia_usuario():
    cmd = "/bin/bash /home/admin/web/socios.zococoria.es/public_html/deploy.sh"
    out = _adapt_cron_command(cmd, "zococori", INSTALLED, {})
    assert out == "/bin/bash /home/zococori/web/socios.zococoria.es/public_html/deploy.sh"


def test_php_no_instalada_cae_a_la_mas_alta():
    cmd = "php5.6 /home/x/web/d.com/cron.php"
    out = _adapt_cron_command(cmd, "user1", INSTALLED, {})
    # 5.6 no está instalada → la más alta disponible (8.3)
    assert "php8.3" in out


def test_respeta_php_si_no_sabemos_del_dominio_y_esta_instalada():
    cmd = "php8.1 /home/x/web/otro.com/cron.php"
    out = _adapt_cron_command(cmd, "user1", INSTALLED, {})  # no conocemos otro.com
    assert "php8.1" in out  # se mantiene (está instalada)
