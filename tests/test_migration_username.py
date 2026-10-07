"""Nombre de usuario propuesto para el cliente nuevo al migrar.

Bug: la UI usaba manifest.system ("hestia") como nombre del cliente. El usuario
real sale del nombre del .tar de v-backup-user o de la carpeta cpmove-USUARIO.
"""
from scripts.hestia_import import username_from_backup_name


def test_nombre_de_v_backup_user():
    assert username_from_backup_name("obradormarilo.2026-10-07_16-40-01.tar") == "obradormarilo"
    assert username_from_backup_name("Cliente_1.2025-01-02_03-04-05.tar") == "cliente_1"


def test_nombres_que_no_son_de_hestia():
    assert username_from_backup_name("tmpk2j3h4.tar") == ""
    assert username_from_backup_name("backup.tar") == ""
    assert username_from_backup_name("") == ""
