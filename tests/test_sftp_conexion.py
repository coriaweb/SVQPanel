"""
Datos de conexión SFTP que enseña la ficha: la huella del servidor tiene que ser
la misma que calcula ssh-keygen (y la que FileZilla/WinSCP muestran al conectar).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_huella_igual_que_ssh_keygen(tmp_path):
    from api.routes.sftp import host_fingerprints
    # Clave de host real del .223; ssh-keygen -lf da SHA256:DZQJwZhF…UrS7JA
    (tmp_path / "ssh_host_ed25519_key.pub").write_text(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUzf/UwdGImCETwPogGY2KKa3+3J0H24lCGMdn+uSqt root@svq-beyuri1\n")
    assert host_fingerprints(str(tmp_path)) == [
        {"type": "ssh-ed25519", "sha256": "SHA256:DZQJwZhFlqQy/NMQANvWZM5OM8mPg7c6taLE2rUS7JA"}]


def test_sin_claves_no_falla(tmp_path):
    from api.routes.sftp import host_fingerprints
    (tmp_path / "ssh_host_rsa_key.pub").write_text("basura")
    assert host_fingerprints(str(tmp_path)) == []
