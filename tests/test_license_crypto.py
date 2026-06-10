"""
Tests de la criptografía del cliente de licencias (Ed25519).

Lo más crítico del sistema de licencias: nadie puede forjar una respuesta
"valid:true" sin la clave privada. Verificamos:
 - _canonical_message produce el mismo JSON que firma el Laravel
   (json_encode con JSON_UNESCAPED_SLASHES|UNICODE → separators sin espacios).
 - Una firma válida se acepta y una firma corrupta se rechaza (propiedad Ed25519).
"""
import os
import sys
import json
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# La cripto necesita 'cryptography'; si falta en el entorno, saltar.
cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.license_client import _canonical_message, _verify_signature
import scripts.license_client as lic


def test_canonical_message_sin_espacios_y_slashes_sin_escapar():
    # Debe coincidir con json_encode(JSON_UNESCAPED_SLASHES|UNICODE) de PHP:
    # separadores sin espacios y las barras NO escapadas.
    payload = {"valid": True, "url": "https://x.com/a", "plan": "beta"}
    msg = _canonical_message(payload).decode()
    assert " " not in msg.replace('"valid"', "").replace('"url"', "").replace('"plan"', "")  # sin espacios entre tokens
    assert "https://x.com/a" in msg          # slash NO escapado (no \/)
    assert "\\/" not in msg


def test_firma_valida_se_acepta(monkeypatch):
    # Generamos un par de claves de prueba y "embebemos" la pública en el módulo.
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY_B64", base64.b64encode(pub_raw).decode())

    payload = {"valid": True, "plan": "beta", "key": "ABC"}
    sig = priv.sign(_canonical_message(payload))
    sig_b64 = base64.b64encode(sig).decode()

    assert _verify_signature(payload, sig_b64) is True


def test_firma_corrupta_se_rechaza(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY_B64", base64.b64encode(pub_raw).decode())

    payload = {"valid": True, "plan": "beta"}
    sig = priv.sign(_canonical_message(payload))
    # Corromper la firma (un byte distinto)
    bad = bytearray(sig); bad[0] ^= 0x01
    assert _verify_signature(payload, base64.b64encode(bytes(bad)).decode()) is False


def test_payload_modificado_invalida_la_firma(monkeypatch):
    # Firmar un payload y luego cambiarlo → la firma ya no debe validar
    # (impide forjar "valid:true" a partir de una respuesta legítima).
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    monkeypatch.setattr(lic, "LICENSE_PUBLIC_KEY_B64", base64.b64encode(pub_raw).decode())

    original = {"valid": False, "plan": "beta"}
    sig = base64.b64encode(priv.sign(_canonical_message(original))).decode()

    tampered = {"valid": True, "plan": "pro"}   # atacante cambia a valid:true
    assert _verify_signature(tampered, sig) is False
