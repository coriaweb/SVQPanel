"""Importador de CWP: parser del export (cwp_export.sh) → manifiesto común."""
import io
import os
import tarfile

import pytest

from scripts import cwp_import as C

U = "acme"
ROOT = f"cwpmove-{U}"


def _tsv(header, *rows):
    return "\t".join(header) + "\n" + "".join("\t".join(r) + "\n" for r in rows)


FILES = {
    "cwp/user.tsv": _tsv(["id", "username", "domain", "ip_address", "email", "package"],
                         ["7", U, "acme.es", "185.104.188.17", "it@acme.es", "8"]),
    "cwp/package.tsv": _tsv(["id", "package_name"], ["8", "Basico"]),
    "cwp/domains.tsv": _tsv(["domain", "path"], ["tienda.com", f"/home/{U}/public_html/tienda"]),
    "cwp/subdomains.tsv": _tsv(["subdomain", "domain", "path"], ["blog", "acme.es", f"/home/{U}/blog"]),
    "cwp/php.tsv": _tsv(["domain", "php", "docroot"],
                        ["acme.es", "56", f"/home/{U}/public_html"],
                        ["tienda.com", "74", f"/home/{U}/public_html/tienda"],
                        ["blog.acme.es", "82", f"/home/{U}/blog"]),
    "cwp/ssl.tsv": "domain\nacme.es\n",
    "cwp/maildomains.tsv": _tsv(["domain"], ["acme.es"]),
    "cwp/mailbox.tsv": _tsv(
        ["username", "password", "quota", "active", "domain", "local_part", "maildir"],
        ["info@acme.es", "{SHA512-CRYPT}$6$abc$def", "1073741824", "1", "acme.es", "info", "acme.es/info/"],
        ["ventas@acme.es", "$1$xy$z", "0", "1", "acme.es", "ventas", "acme.es/ventas/"],
        ["vacio@acme.es", "{MD5-CRYPT}", "0", "1", "acme.es", "vacio", "acme.es/vacio/"],
        ["baja@acme.es", "{MD5-CRYPT}$1$q$w", "0", "0", "acme.es", "baja", "acme.es/baja/"]),
    "cwp/alias.tsv": _tsv(
        ["address", "goto", "active", "domain"],
        ["info@acme.es", "info@acme.es,jefe@gmail.com", "1", "acme.es"],     # con copia
        ["ventas@acme.es", "comercial@gmail.com", "1", "acme.es"],          # solo reenvío
        ["web@acme.es", "info@acme.es", "1", "acme.es"],                    # alias puro
        ["@acme.es", "info@acme.es", "1", "acme.es"],                       # catch-all
        ["info@acme.es", "info@acme.es", "1", "acme.es"]),                  # a sí mismo
    "cwp/vacation.tsv": _tsv(["email", "subject", "body", "active", "domain"],
                             ["info@acme.es", "Fuera", "Vuelvo el lunes\\nGracias", "1", "acme.es"]),
    "cwp/extra_dirs.tsv": _tsv(["name", "kb"], ["includes", "2048"]),
    "cwp/sizes.tsv": _tsv(["kind", "name", "kb"], ["web", "x", "10240"], ["mail", "y", "20480"]),
    "mysql/acme_wp.create": "CREATE DATABASE `acme_wp`;\n",
    "mysql/acme_wp.sql": "CREATE TABLE t (id int);\n",
    "mysql.sql": ("GRANT USAGE ON *.* TO 'acme_wp'@'localhost' IDENTIFIED BY PASSWORD '*ABC';\n"
                  "GRANT ALL PRIVILEGES ON `acme_wp`.* TO 'acme_wp'@'localhost';\n"),
    "dnszones/acme.es.db": ("$TTL 14400\n@ IN SOA ns1.x. root.x. (1 3600 600 86400 3600)\n"
                            "@ IN A 185.104.188.17\nwww IN CNAME acme.es.\n"
                            "@ IN MX 10 mail.acme.es.\n"),
    f"cron/{U}": ("MAILTO=x\n*/5 * * * * /opt/alt/php-fpm74/usr/bin/php "
                  f"/home/{U}/public_html/tienda/cron.php\n"),
    "homedir/public_html/index.php": "<?php include '/home/acme/public_html/tienda/x.php';\n",
    "homedir/public_html/tienda/config.php": "<?php $dir='/home/acme/public_html/tienda/up';\n",
    "homedir/blog/index.html": "hola\n",
    # Sin ':' en los nombres de Maildir: Windows (donde también corren los tests) no los admite.
    "homedir/mail/acme.es/info/cur/1.a": "From: a\n\nhola\n",
    "homedir/mail/acme.es/info/.spam/cur/2.b": "spam1\n",
    "homedir/mail/acme.es/info/.Spam/new/3.c": "spam2\n",
    "homedir/mail/acme.es/info/subscriptions": "INBOX.Sent\n",
}


@pytest.fixture
def backup(tmp_path):
    tar_path = tmp_path / "acme.tar"
    with tarfile.open(tar_path, "w") as tf:
        for name, content in FILES.items():
            data = content.encode()
            ti = tarfile.TarInfo(f"{ROOT}/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    with C.CwpBackup(str(tar_path)) as b:
        yield b


def test_tsv_escapes_y_null():
    rows = C.parse_tsv("a\tb\tc\nx\\ty\tNULL\tl1\\nl2\n")
    assert rows == [{"a": "x\ty", "b": "", "c": "l1\nl2"}]


def test_hashes():
    assert C.cwp_hash("{SHA512-CRYPT}$6$a$b") == "{SHA512-CRYPT}$6$a$b"
    assert C.cwp_hash("$1$a$b") == "$1$a$b"
    assert C.cwp_hash("{MD5-CRYPT}") == ""      # buzón sin contraseña
    assert C.cwp_hash("") == ""


def test_manifiesto_web(backup):
    m = backup.analyze()
    assert m["system"] == "cwp" and m["username"] == U
    assert m["user"]["contact"] == "it@acme.es" and m["user"]["package"] == "Basico"
    web = {w["domain"]: w for w in m["web"]}
    assert set(web) == {"acme.es", "tienda.com", "blog.acme.es"}
    assert web["acme.es"]["php_version"] == "5.6" and web["acme.es"]["ssl"]
    assert web["tienda.com"]["php_version"] == "7.4"
    # tienda.com vive DENTRO del public_html de acme.es → no se copia aparte,
    # apunta a la carpeta del principal (y si no se importa, copia de respaldo).
    assert web["tienda.com"]["_nested_in"] == {"domain": "acme.es", "rel": "tienda"}
    assert web["tienda.com"]["_data_dir"] is None and not web["tienda.com"]["has_data"]
    assert web["tienda.com"]["_nested_data_dir"].replace("\\", "/").endswith("homedir/public_html/tienda")
    assert web["acme.es"]["_nested_in"] is None and web["acme.es"]["has_data"]
    assert web["blog.acme.es"]["has_data"] and web["blog.acme.es"]["_nested_in"] is None
    # Las raíces se importan antes que las anidadas
    order = [w["domain"] for w in m["web"]]
    assert order.index("acme.es") < order.index("tienda.com")
    assert any("tienda.com (/tienda)" in w for w in m["warnings"])
    assert m["size_mb"] == 30


def test_docroot_compartido_misma_carpeta(tmp_path):
    files = dict(FILES)
    files["cwp/subdomains.tsv"] = _tsv(["subdomain", "domain", "path"],
                                       ["kilika", "acme.es", f"/home/{U}/public_html/app"],
                                       ["berona", "acme.es", f"/home/{U}/public_html/app"])
    files["cwp/php.tsv"] = _tsv(["domain", "php", "docroot"],
                                ["acme.es", "82", f"/home/{U}/public_html"])
    files["homedir/public_html/app/index.php"] = "<?php\n"
    tar_path = tmp_path / "x.tar"
    with tarfile.open(tar_path, "w") as tf:
        for name, content in files.items():
            data = content.encode()
            ti = tarfile.TarInfo(f"{ROOT}/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    with C.CwpBackup(str(tar_path)) as b:
        web = {w["domain"]: w for w in b.analyze()["web"]}
    assert web["kilika.acme.es"]["_nested_in"] == {"domain": "acme.es", "rel": "app"}
    assert web["berona.acme.es"]["_nested_in"] == {"domain": "acme.es", "rel": "app"}


def test_validate_custom_docroot():
    from scripts.utils import validate_custom_docroot as v
    assert v("/home/acme/web/acme.es/public_html/app/", "acme", must_exist=False) \
        == "/home/acme/web/acme.es/public_html/app"
    assert v("", "acme") is None
    for bad in ("/home/otro/web/x.com/public_html",      # otro cliente
                "/etc", "/home/acme", "/home/acme/web", "/home/acme/web/",
                "/home/acme/web/x/../../otro",           # ..
                "/home/acme/web/x;\n  location / {",     # inyección en el vhost
                "/home/acme/web/x y", "relativa/x"):
        with pytest.raises(ValueError):
            v(bad, "acme", must_exist=False)


def test_open_basedir_incluye_custom_docroot():
    from scripts.php_ini_manager import _security_block
    ob = lambda cd: next(l for l in _security_block("acme", "sub.acme.es", custom_docroot=cd)
                         if "open_basedir" in l)
    assert ob("/home/acme/web/acme.es/public_html/app").endswith(
        ":/home/acme/web/acme.es/public_html/app")
    # Dentro de su propio public_html: no hace falta añadirlo
    assert ob("/home/acme/web/sub.acme.es/public_html/x").count("public_html") == 1
    # Fuera del árbol del dueño: se ignora (nunca abre el open_basedir)
    assert "/etc" not in ob("/etc") and "/home/otro" not in ob("/home/otro/web/a/public_html")


def test_manifiesto_correo(backup):
    m = backup.analyze()
    (dom,) = m["mail"]
    acc = {a["account"]: a for a in dom["accounts"]}
    assert acc["info"]["md5"].startswith("{SHA512-CRYPT}")
    assert acc["info"]["quota"] == "1024"
    assert acc["info"]["fwd"] == "jefe@gmail.com" and not acc["info"]["fwd_only"]
    assert acc["ventas"]["fwd"] == "comercial@gmail.com" and acc["ventas"]["fwd_only"]
    assert acc["vacio"]["md5"] == ""
    assert acc["baja"]["suspended"]
    aliases = {a["source"]: a["destinations"] for a in dom["aliases"]}
    assert aliases == {"web": ["info@acme.es"], "@": ["info@acme.es"]}
    assert any("sin contraseña" in w and "vacio@acme.es" in w for w in m["warnings"])
    assert any("includes" in w for w in m["warnings"])


def test_spam_fundido_en_junk(backup):
    info = os.path.join(backup.root, "homedir", "mail", "acme.es", "info")
    assert not os.path.exists(os.path.join(info, ".spam"))
    assert not os.path.exists(os.path.join(info, ".Spam"))
    assert os.listdir(os.path.join(info, ".Junk", "cur")) == ["2.b"]
    assert os.listdir(os.path.join(info, ".Junk", "new")) == ["3.c"]
    assert not os.path.exists(os.path.join(info, "subscriptions"))
    assert backup._mail_moved == 2


def test_bd_dns_cron(backup):
    m = backup.analyze()
    (d,) = m["db"]
    assert d["db"] == "acme_wp" and d["dbuser"] == "acme_wp" and d["md5"] == "*ABC"
    (z,) = m["dns"]
    assert z["domain"] == "acme.es" and z["ip"] == "185.104.188.17"
    (cron,) = m["cron"]
    # tienda.com es anidada: su cron.php real queda dentro de la carpeta de acme.es
    assert cron["cmd"] == f"/usr/bin/php7.4 /home/{U}/web/acme.es/public_html/tienda/cron.php"
    assert cron["min"] == "*/5" and cron["origin"] == "CWP"


def test_sieve_sin_inbox_y_spam_a_junk():
    src = 'require "fileinto";\nif header :contains "X-Spam" "Yes" { fileinto "INBOX.spam"; }\n' \
          'elsif address :is "from" "a@b" { fileinto :copy "INBOX.Clientes"; }\n'
    out = C.adapt_cwp_sieve(src)
    assert 'fileinto "Junk"' in out
    assert 'fileinto :copy "Clientes"' in out


def test_reescribe_rutas_de_cwp(tmp_path):
    main = tmp_path / "main"
    (main / "tienda").mkdir(parents=True)
    (main / "index.php").write_text("<?php include '/home/acme/public_html/tienda/x.php'; "
                                    "$r='/home/acme/public_html';\n")
    (main / "foto.jpg").write_bytes(b"/home/acme/public_html")
    mapping = [("/home/acme/public_html", "/home/nuevo/web/acme.es/public_html"),
               ("/home/acme/public_html/tienda", "/home/nuevo/web/tienda.com/public_html"),
               ("/home/acme", "/home/nuevo")]
    changed = C.rewrite_paths(str(main), mapping)
    text = (main / "index.php").read_text()
    assert "/home/nuevo/web/tienda.com/public_html/x.php" in text
    assert "$r='/home/nuevo/web/acme.es/public_html'" in text
    assert changed == ["index.php"]
    assert (main / "foto.jpg").read_bytes() == b"/home/acme/public_html"   # binarios intactos
