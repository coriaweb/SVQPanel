"""
Tests de la lógica pura del manager de auto-actualizaciones (conteo de paquetes
de seguridad en la salida de `apt-get -s upgrade`).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.auto_updates import count_security_upgrades


_APT_OUTPUT = """Reading package lists...
Building dependency tree...
Inst libssl3 [3.0.11-1] (3.0.14-1~deb12u1 Debian:12.7/stable, Debian-Security:12/stable-security [amd64])
Conf libssl3 (3.0.14-1~deb12u1 Debian-Security:12/stable-security [amd64])
Inst curl [7.88.1-10] (7.88.1-10+deb12u7 Debian-Security:12/stable-security [amd64])
Inst some-normal-pkg [1.0] (1.1 Debian:12.7/stable [amd64])
Conf curl (7.88.1-10+deb12u7 Debian-Security:12/stable-security [amd64])
"""


def test_cuenta_solo_paquetes_de_seguridad():
    # 2 "Inst ... Debian-Security" (libssl3, curl); el normal NO cuenta.
    assert count_security_upgrades(_APT_OUTPUT) == 2


def test_salida_vacia():
    assert count_security_upgrades("") == 0


def test_sin_actualizaciones_de_seguridad():
    out = "Inst foo [1.0] (1.1 Debian:12.7/stable [amd64])\n"
    assert count_security_upgrades(out) == 0


def test_reconoce_sufijo_security():
    out = "Inst bar [1.0] (1.1 Ubuntu:22.04/jammy-security [amd64])\n"
    assert count_security_upgrades(out) == 1
