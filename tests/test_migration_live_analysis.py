"""
Migración desde Hestia por SSH sin traer el backup para analizar, y los dos
fallos vistos con una cuenta real llamada "midominio.com":

1. El análisis lee la config EN VIVO (/usr/local/hestia/data/users/U/) y la
   reordena como un backup para reutilizar el parser (HestiaLiveBackup).
2. Los nombres de BD con punto ("midominio.com_wp") se conservan TAL CUAL: el
   wp-config los usa así; quitarles el punto dejaba la web sin BD.
3. Las rutas /home/<usuario_origen>/ de .user.ini/wp-config… se reescriben al
   usuario nuevo (Wordfence en auto_prepend_file daba fatal en todas las páginas).
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.hestia_import as hi


def _write(base, rel, text):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


@pytest.fixture
def live_dir(tmp_path):
    d = tmp_path / "midominio.com"
    _write(d, "user.conf", "FNAME='Ana' LNAME='J.' CONTACT='ana@example.com' "
                           "PACKAGE='BASICO' U_DISK='3072'\n")
    _write(d, "web.conf",
           "DOMAIN='midominio.com' ALIAS='www.midominio.com' BACKEND='PHP-8_3' "
           "SSL='yes' U_DISK='2000' SUSPENDED='no'\n"
           "DOMAIN='otro.com' ALIAS='' BACKEND='PHP-8_1' SSL='no' U_DISK='10' SUSPENDED='yes'\n"
           "DOMAIN='../malo' U_DISK='1'\n")
    _write(d, "db.conf", "DB='midominio.com_wp' DBUSER='midominio.com_wp1' "
                         "MD5='*ABC' TYPE='mysql' CHARSET='UTF8MB4' U_DISK='159'\n")
    _write(d, "mail.conf", "DOMAIN='midominio.com' U_DISK='900' SUSPENDED='no'\n")
    _write(d, "mail/midominio.com.conf",
           "ACCOUNT='info' MD5='{SHA512-CRYPT}$6$x' QUOTA='unlimited' FWD='' SUSPENDED='no'\n"
           "ACCOUNT='ventas' MD5='{SHA512-CRYPT}$6$y' QUOTA='1024' FWD='a@b.com' FWD_ONLY='yes'\n")
    _write(d, "dns.conf", "DOMAIN='midominio.com' IP='1.2.3.4' TTL='3600'\n")
    _write(d, "dns/midominio.com.conf",
           "ID='1' RECORD='@' TYPE='A' VALUE='1.2.3.4' TTL='3600'\n"
           "ID='2' RECORD='www' TYPE='CNAME' VALUE='midominio.com.' TTL='3600'\n")
    _write(d, "cron.conf", "JOB='1' MIN='*/5' HOUR='*' DAY='*' MONTH='*' WDAY='*' "
                           "CMD='php /home/midominio.com/web/midominio.com/public_html/cron.php' "
                           "SUSPENDED='no'\n")
    return str(d)


def test_analisis_en_vivo_da_el_mismo_manifiesto_que_un_backup(live_dir):
    with hi.HestiaLiveBackup(live_dir, "midominio.com") as b:
        m = b.analyze()

    assert m["live"] is True
    assert m["username"] == "midominio.com"
    assert m["user"]["contact"] == "ana@example.com"
    assert m["size_mb"] == 3072

    webs = {w["domain"]: w for w in m["web"]}
    assert set(webs) == {"midominio.com", "otro.com"}, "un nombre con .. no debe colarse como ruta"
    assert webs["midominio.com"]["php_version"] == "8.3"
    assert webs["midominio.com"]["has_data"] is True
    assert webs["midominio.com"]["disk_mb"] == 2000
    assert webs["otro.com"]["suspended"] is True

    assert m["db"][0]["db"] == "midominio.com_wp"
    assert m["db"][0]["has_dump"] is True
    assert m["db"][0]["disk_mb"] == 159

    accounts = {a["account"]: a for a in m["mail"][0]["accounts"]}
    assert set(accounts) == {"info", "ventas"}
    assert accounts["ventas"]["fwd_only"] is True

    assert m["dns"][0]["records_count"] == 2
    assert m["dns"][0]["ip"] == "1.2.3.4"
    assert len(m["cron"]) == 1


def test_analisis_en_vivo_limpia_su_tmp(live_dir):
    b = hi.HestiaLiveBackup(live_dir, "midominio.com")
    with b:
        tmp = b.tmpdir
        assert os.path.isdir(tmp)
    assert not os.path.exists(tmp)
    assert os.path.isdir(live_dir), "no debe borrar la copia en vivo (es del llamador)"


def test_ident_conserva_puntos_y_guiones():
    assert hi._ident("midominio.com_wp") == "midominio.com_wp"
    assert hi._ident("mi-dominio_db") == "mi-dominio_db"


@pytest.mark.parametrize("bad", ["a`b", "a'b", "a b", "-opcion", "", "x" * 65, "a/b"])
def test_ident_rechaza_lo_peligroso(bad):
    with pytest.raises(ValueError):
        hi._ident(bad)


def test_import_db_crea_la_bd_con_el_punto():
    sql = []
    owner = MagicMock(id=7)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    report = hi.ImportReport()
    dbinfo = {"db": "midominio.com_wp", "dbuser": "midominio.com_wp1", "md5": "*ABC",
              "type": "mysql", "charset": "utf8mb4", "_dump": None}
    with patch("api.routes.databases._run_mariadb", side_effect=sql.append), \
         patch("api.routes.databases._hash_password", return_value="h"), \
         patch("api.routes.databases._encrypt_password", return_value=None), \
         patch("api.routes.databases._generate_password", return_value="pw"), \
         patch("api.models.models_client_db.ClientDatabase", MagicMock()):
        hi.import_db(MagicMock(), dbinfo, owner, db, report)
    joined = "\n".join(sql)
    assert "CREATE DATABASE `midominio.com_wp`" in joined
    assert "'midominio.com_wp1'@'localhost'" in joined
    assert "midominiocom" not in joined


def test_reescribe_rutas_del_usuario_de_origen(tmp_path):
    ph = tmp_path / "public_html"
    old = "/home/midominio.com/web/midominio.com/public_html"
    _write(ph, ".user.ini", f"auto_prepend_file = '{old}/wordfence-waf.php'\n")
    _write(ph, "wordfence-waf.php",
           f"<?php include_once '{old}/wp-content/plugins/wordfence/waf/bootstrap.php';\n"
           "define('WFWAF_LOG_PATH', '/home/midominio.com/tmp/');\n")
    _write(ph, "wp-config.php", "<?php define('DB_NAME', 'midominio.com_wp');\n")
    _write(ph, "index.php", f"<?php // {old}\n")   # fuera de la lista: no se toca

    changed = hi._rewrite_old_home_paths(str(ph), "midominio", "midominio.com")

    assert changed[0] == "midominio.com"
    assert set(changed[1:]) == {".user.ini", "wordfence-waf.php"}
    assert (ph / ".user.ini").read_text() == \
        "auto_prepend_file = '/home/midominio/web/midominio.com/public_html/wordfence-waf.php'\n"
    waf = (ph / "wordfence-waf.php").read_text()
    assert "/home/midominio.com/" not in waf
    assert "/home/midominio/tmp/" in waf
    assert "midominio.com_wp" in (ph / "wp-config.php").read_text(), "el nombre de la BD no se toca"
    assert old in (ph / "index.php").read_text()
    assert not list(ph.glob("*.svqbak")), "nada de copias legibles desde la web"


def test_no_reescribe_si_el_usuario_no_cambia(tmp_path):
    ph = tmp_path / "public_html"
    _write(ph, ".user.ini",
           "auto_prepend_file = '/home/ana/web/midominio.com/public_html/wordfence-waf.php'\n")
    assert hi._rewrite_old_home_paths(str(ph), "ana", "midominio.com") == []
