"""
Certificado SSL PROPIO de un dominio (comprado, de un cliente, de otra CA).

Se guarda en /etc/svqpanel/ssl/<dominio>/ (fullchain.pem + privkey.pem, root 0600
la clave) y manda sobre el de Let's Encrypt mientras exista (ver ssl_paths). Al
quitarlo, el dominio vuelve solo al de Let's Encrypt si lo tenía.

Antes de instalar se comprueba TODO lo que haría fallar a nginx o al navegador:
PEM legible, la clave corresponde al certificado, no está caducado (ni aún no
válido), cubre el dominio y viene la cadena intermedia (si no la trae, muchos
móviles y `curl` dan "unable to get local issuer certificate").
"""
import os
import shutil
from datetime import datetime, timezone

from scripts import ssl_paths

MAX_PEM = 64 * 1024


class CertError(ValueError):
    pass


def _load_certs(pem: str):
    from cryptography import x509
    data = (pem or "").strip().encode()
    if not data:
        return []
    try:
        return x509.load_pem_x509_certificates(data)
    except ValueError as e:
        raise CertError(f"El certificado no es un PEM válido ({e}). Debe empezar por "
                        "-----BEGIN CERTIFICATE-----") from None


def _load_key(pem: str):
    from cryptography.hazmat.primitives import serialization
    data = (pem or "").strip().encode()
    if b"ENCRYPTED" in data:
        raise CertError("La clave privada está protegida con contraseña: quítasela antes de subirla "
                        "(openssl rsa -in clave.key -out clave-sin-pass.key)")
    try:
        return serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as e:
        raise CertError(f"La clave privada no es un PEM válido ({e}). Debe empezar por "
                        "-----BEGIN PRIVATE KEY----- (o RSA/EC PRIVATE KEY)") from None


def _pub_bytes(obj) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return obj.public_bytes(serialization.Encoding.DER,
                            serialization.PublicFormat.SubjectPublicKeyInfo)


def _names(cert):
    from cryptography import x509
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return [cn[0].value] if cn else []


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def validate(domain: str, cert_pem: str, key_pem: str, chain_pem: str = "",
             is_subdomain: bool = False) -> dict:
    """Comprueba el certificado. Devuelve info + el fullchain a escribir.
    Lanza CertError con un mensaje para el usuario si algo no cuadra."""
    from cryptography.hazmat.primitives import serialization
    for label, v in (("certificado", cert_pem), ("clave", key_pem), ("cadena", chain_pem)):
        if v and len(v) > MAX_PEM:
            raise CertError(f"El {label} es demasiado grande")
    certs = _load_certs(cert_pem)
    if not certs:
        raise CertError("Falta el certificado")
    leaf, extra = certs[0], certs[1:]
    chain = extra + _load_certs(chain_pem)
    key = _load_key(key_pem)

    if _pub_bytes(key.public_key()) != _pub_bytes(leaf.public_key()):
        raise CertError("La clave privada no corresponde a este certificado")

    now = datetime.now(timezone.utc)
    not_before = _utc(getattr(leaf, "not_valid_before_utc", None) or leaf.not_valid_before)
    not_after = _utc(getattr(leaf, "not_valid_after_utc", None) or leaf.not_valid_after)
    if not_after <= now:
        raise CertError(f"El certificado caducó el {not_after:%d/%m/%Y}")
    if not_before > now:
        raise CertError(f"El certificado aún no es válido (empieza el {not_before:%d/%m/%Y})")

    names = _names(leaf)
    if not ssl_paths.covers(names, domain):
        raise CertError(f"El certificado no cubre {domain} (cubre: {', '.join(names) or 'nada'})")
    warnings = []
    if not is_subdomain and not ssl_paths.covers(names, f"www.{domain}"):
        warnings.append(f"No cubre www.{domain}: quien entre con www verá un aviso de seguridad.")

    # ¿Es autofirmado? (emisor == sujeto) — nginx lo acepta pero el navegador no
    self_signed = leaf.issuer == leaf.subject
    if self_signed:
        warnings.append("Es un certificado autofirmado: los navegadores mostrarán un aviso.")
    elif not chain:
        raise CertError("Falta la cadena intermedia (CA bundle) que da tu proveedor. Sin ella "
                        "muchos móviles y programas no confían en el certificado.")
    elif chain[0].subject != leaf.issuer:
        raise CertError("La cadena intermedia no corresponde a este certificado (el primer "
                        "intermedio no es quien lo firmó). Revisa el orden o el fichero.")

    pem = lambda c: c.public_bytes(serialization.Encoding.PEM).decode()
    fullchain = pem(leaf) + "".join(pem(c) for c in chain)
    key_out = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return {
        "names": names, "not_before": not_before, "not_after": not_after,
        "issuer": leaf.issuer.rfc4514_string(), "self_signed": self_signed,
        "warnings": warnings, "fullchain": fullchain, "key": key_out,
    }


def install(domain: str, info: dict) -> None:
    """Escribe los ficheros (atómico; la clave 0600 root). Guarda copia del
    anterior en .prev por si hay que revertir."""
    d = ssl_paths.custom_dir(domain)
    os.makedirs(ssl_paths.CUSTOM_ROOT, mode=0o700, exist_ok=True)
    prev = d + ".prev"
    if os.path.isdir(prev):
        shutil.rmtree(prev)
    if os.path.isdir(d):
        shutil.copytree(d, prev)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fc, pk = ssl_paths.custom_paths(domain)
    for path, content, mode in ((fc, info["fullchain"], 0o644), (pk, info["key"], 0o600)):
        tmp = path + ".tmp"
        fdesc = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fdesc, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)


def restore_previous(domain: str) -> None:
    """Deshace install(): vuelve al propio anterior o, si no había, lo quita."""
    d = ssl_paths.custom_dir(domain)
    prev = d + ".prev"
    if os.path.isdir(d):
        shutil.rmtree(d)
    if os.path.isdir(prev):
        os.replace(prev, d)


def remove(domain: str) -> bool:
    d = ssl_paths.custom_dir(domain)
    existed = os.path.isdir(d)
    for path in (d, d + ".prev"):
        if os.path.isdir(path):
            shutil.rmtree(path)
    return existed
