"""
Importador de cPanel: usuario de las copias backup-…, reenvíos (va/), crons
(cron/USUARIO) con las rutas traducidas, y extracción fuera de /tmp.
"""
import os
import tarfile

from scripts import cpanel_import as C


def _make_backup(tmp_path, root="backup-11.8.2026_10-00-00_juanp", user="juanp"):
    src = tmp_path / "src" / root
    files = {
        f"cp/{user}": "PLAN=default\nCONTACTEMAIL=juan@ejemplo.es\n",
        "userdata/main": ("main_domain: ejemplo.es\naddon_domains:\n"
                          "  tienda.es: tienda.ejemplo.es\nsub_domains:\n"
                          "  - tienda.ejemplo.es\n"),
        "userdata/ejemplo.es": f"documentroot: /home/{user}/public_html\nphpversion: ea-php81\n",
        "userdata/tienda.es": f"documentroot: /home/{user}/public_html/tienda\n",
        "userdata/tienda.ejemplo.es": f"documentroot: /home/{user}/public_html/tienda\n",
        "homedir/public_html/index.php": "<?php\n",
        "homedir/public_html/tienda/index.php": "<?php\n",
        "homedir/mail/ejemplo.es/info/cur/.keep": "",
        "homedir/mail/ejemplo.es/ventas/cur/.keep": "",
        "etc/ejemplo.es/shadow": "info:$6$abc:1::::::\nventas:$6$def:1::::::\n",
        "etc/ejemplo.es/quota": "info:1048576000\n",
        "va/ejemplo.es": ("info@ejemplo.es: info@ejemplo.es, marta.j@gmail.com\n"
                          "pedidos@ejemplo.es: ventas@ejemplo.es,otro@ejemplo.net\n"
                          "basura@ejemplo.es: :blackhole:\n"
                          "script@ejemplo.es: \"|/home/juanp/script.php\"\n"
                          "*: juanp\n"),
        "va/tienda.es": "hola@tienda.es: info@ejemplo.es\n*: info@ejemplo.es\n",
        f"cron/{user}": ("MAILTO=\"\"\nSHELL=\"/bin/bash\"\n# comentario\n"
                         f"*/5 * * * * /usr/local/bin/php /home/{user}/public_html/wp-cron.php >/dev/null 2>&1\n"
                         f"0 3 * * * /opt/cpanel/ea-php74/root/usr/bin/php /home/{user}/public_html/tienda/cron.php\n"
                         f"@daily /home/{user}/scripts/limpia.sh\n"
                         "@reboot /bin/true\n"),
    }
    for rel, content in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    tar = tmp_path / f"{root}.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:
        tf.add(src, arcname=root)
    return str(tar)


def _open(tmp_path, monkeypatch, **kw):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.setattr(C, "_tmp_dir", lambda: str(work))
    b = C.CpanelBackup(_make_backup(tmp_path, **kw))
    b.extract()
    return b, work


def test_extrae_fuera_de_tmp(tmp_path, monkeypatch):
    b, work = _open(tmp_path, monkeypatch)
    try:
        assert os.path.dirname(b.tmpdir) == str(work)
        assert os.path.basename(b.tmpdir).startswith("svq_hestia_")   # lo barre purge_migration_tmp
    finally:
        b.cleanup()


def test_usuario_de_copia_backup(tmp_path, monkeypatch):
    b, _ = _open(tmp_path, monkeypatch)
    try:
        m = b.analyze()
        assert m["username"] == "juanp"
        assert m["user"]["contact"] == "juan@ejemplo.es"
    finally:
        b.cleanup()


def test_usuario_sin_cp_por_nombre_de_carpeta(tmp_path, monkeypatch):
    b, _ = _open(tmp_path, monkeypatch, root="cpmove-pepe", user="pepe")
    try:
        os.remove(os.path.join(b.root, "cp", "pepe"))
        assert b.guess_username() == "pepe"
    finally:
        b.cleanup()


def test_reenvios(tmp_path, monkeypatch):
    b, _ = _open(tmp_path, monkeypatch)
    try:
        mail = {m["domain"]: m for m in b.analyze_mail()}
        ej = mail["ejemplo.es"]
        accs = {a["account"]: a for a in ej["accounts"]}
        # Buzón con reenviador → reenvío con copia (sin el bucle a sí mismo)
        assert accs["info"]["fwd"] == "marta.j@gmail.com" and accs["info"]["fwd_only"] is False
        assert accs["ventas"]["fwd"] is None
        # Sin buzón → alias puro; :blackhole:, tuberías y el usuario de sistema fuera
        assert ej["aliases"] == [{"source": "pedidos",
                                  "destinations": ["ventas@ejemplo.es", "otro@ejemplo.net"]}]
        # Dominio solo con reenvíos (sin buzones): también se importa, con catch-all
        t = mail["tienda.es"]
        assert t["accounts"] == [] and t["_accounts_dir"] is None
        assert {"source": "@", "destinations": ["info@ejemplo.es"]} in t["aliases"]
    finally:
        b.cleanup()


def test_crons_con_rutas_de_svqpanel(tmp_path, monkeypatch):
    b, _ = _open(tmp_path, monkeypatch)
    try:
        crons = b.analyze()["cron"]
        assert len(crons) == 3                      # variables, comentario y @reboot fuera
        assert crons[0]["min"] == "*/5" and crons[0]["origin"] == "cPanel"
        assert crons[0]["cmd"].startswith(
            "/usr/bin/php /home/juanp/web/ejemplo.es/public_html/wp-cron.php")
        # El docroot más largo gana: public_html/tienda → tienda.es (o su subdominio)
        assert "/usr/bin/php7.4 /home/juanp/web/tienda." in crons[1]["cmd"]
        assert "/public_html/cron.php" in crons[1]["cmd"]
        # @daily → 0 0 * * *; fuera de un docroot la ruta se deja (sin web/)
        assert [crons[2][k] for k in ("min", "hour", "day", "month", "wday")] == ["0", "0", "*", "*", "*"]
        assert crons[2]["cmd"] == "/home/juanp/scripts/limpia.sh"
    finally:
        b.cleanup()


def test_cron_adaptado_al_usuario_nuevo():
    from scripts.hestia_import import _adapt_cron_command
    cmd = C._cpanel_cron_cmd("/opt/cpanel/ea-php74/root/usr/bin/php /home2/viejo/public_html/x.php",
                             [("public_html", "ejemplo.es")])
    assert cmd == "/usr/bin/php7.4 /home/viejo/web/ejemplo.es/public_html/x.php"
    out = _adapt_cron_command(cmd, "nuevo", ["8.1", "8.3"], {"ejemplo.es": "8.3"})
    assert out == "/usr/bin/php8.3 /home/nuevo/web/ejemplo.es/public_html/x.php"


def test_import_cron_comenta_el_origen():
    import inspect
    from scripts import hestia_import as H
    assert "job.get('origin') or 'Hestia'" in inspect.getsource(H.import_cron)


def test_import_mail_crea_los_alias(monkeypatch):
    from types import SimpleNamespace
    from scripts import hestia_import as H
    from api.models.database import load_all_models
    load_all_models()

    class Rep:
        def __init__(self): self.ok_, self.fail_ = [], []
        def ok(self, *a): self.ok_.append(a)
        def fail(self, *a): self.fail_.append(a)

    class Mgr:
        def __init__(self): self.calls = []
        def create_alias(self, *a): self.calls.append(("alias",) + a)
        def set_catch_all(self, *a): self.calls.append(("catch",) + a)

    class DB:
        def __init__(self): self.added = []
        def add(self, o): self.added.append(o)
        def commit(self): pass
        def rollback(self): pass

    mgr, db, rep = Mgr(), DB(), Rep()
    md = SimpleNamespace(id=7, domain_name="ejemplo.es")
    H._import_mail_aliases(mgr, md, [
        {"source": "pedidos", "destinations": ["a@ejemplo.net", "b@ejemplo.net"]},
        {"source": "@", "destinations": ["info@ejemplo.es"]},
        {"source": "malo", "destinations": ["no es un email"]},
    ], db, rep)
    assert mgr.calls == [("alias", "ejemplo.es", "pedidos", "a@ejemplo.net,b@ejemplo.net"),
                         ("catch", "ejemplo.es", "info@ejemplo.es")]
    assert [a.source for a in db.added] == ["pedidos", "@"]
    assert len(rep.fail_) == 1


def test_subidas_a_disco(tmp_path, monkeypatch):
    import starlette.formparsers as fp
    from api.utils import upload_tmp
    orig = fp.SpooledTemporaryFile
    monkeypatch.setattr(upload_tmp.os, "name", "posix")
    try:
        assert upload_tmp.install(str(tmp_path / "up"))
        f = fp.SpooledTemporaryFile(max_size=10)
        # El directorio con el que se creará el fichero al pasar de max_size. (En
        # Linux el temporal es anónimo, O_TMPFILE: no tiene un nombre que mirar.)
        assert f._TemporaryFileArgs["dir"] == str(tmp_path / "up")
        f.write(b"x" * 100)                      # supera max_size → a disco
        assert f._rolled
        f.close()
    finally:
        fp.SpooledTemporaryFile = orig
