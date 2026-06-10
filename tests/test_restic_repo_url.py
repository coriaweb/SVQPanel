"""
Tests de build_repo_url del motor de backups (restic).

Genera la URL del repositorio según el destino (local / SFTP / S3). Es lógica
pura crítica: una URL mal formada manda los backups al sitio equivocado.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.restic_manager import build_repo_url


def test_repo_local():
    url = build_repo_url({"destination_type": "local", "local_path": "/backups"},
                         "user1", "ejemplo.com")
    assert url == "/backups/restic/user1/ejemplo.com"


def test_repo_local_default_path():
    # Sin local_path → /backups por defecto
    url = build_repo_url({"destination_type": "local"}, "user1", "ejemplo.com")
    assert url.startswith("/backups/restic/")


def test_repo_sftp():
    url = build_repo_url({
        "destination_type": "sftp", "sftp_host": "backup.host.com",
        "sftp_user": "svq", "sftp_path": "/data",
    }, "user1", "ejemplo.com")
    assert url == "sftp:svq@backup.host.com:/data/restic/user1/ejemplo.com"


def test_repo_s3():
    url = build_repo_url({
        "destination_type": "s3", "s3_endpoint": "s3.amazonaws.com",
        "s3_bucket": "mibucket", "s3_prefix": "svq",
    }, "user1", "ejemplo.com")
    assert url.startswith("s3:")
    assert "mibucket" in url
    assert "ejemplo.com" in url


def test_repo_usuario_y_dominio_en_la_ruta():
    # El repo siempre va segmentado por usuario/dominio (aislamiento)
    url = build_repo_url({"destination_type": "local", "local_path": "/b"},
                         "cliente9", "tienda.com")
    assert "cliente9" in url
    assert "tienda.com" in url
