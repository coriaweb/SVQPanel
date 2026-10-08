"""
Dónde está el certificado de un nombre, y qué nombres cubre.

Un dominio puede tener su certificado en dos sitios:
  - Propio (subido por el cliente):  /etc/svqpanel/ssl/<dominio>/{fullchain,privkey}.pem
  - Let's Encrypt (certbot):         /etc/letsencrypt/live/<dominio>/{fullchain,privkey}.pem
Manda el PROPIO si existe: así, al quitarlo, el dominio vuelve solo al de Let's
Encrypt (si lo había) sin reemitir nada.

`covers()` entiende comodines: *.dominio.com cubre mail.dominio.com (un nivel),
pero no dominio.com ni a.b.dominio.com (como los navegadores y los MTA).
"""
import os
import subprocess
from typing import List, Optional, Tuple

CUSTOM_ROOT = "/etc/svqpanel/ssl"
LE_ROOT = "/etc/letsencrypt/live"


def custom_dir(name: str) -> str:
    return os.path.join(CUSTOM_ROOT, name)


def custom_paths(name: str) -> Tuple[str, str]:
    d = custom_dir(name)
    return os.path.join(d, "fullchain.pem"), os.path.join(d, "privkey.pem")


def le_paths(name: str) -> Tuple[str, str]:
    d = os.path.join(LE_ROOT, name)
    return os.path.join(d, "fullchain.pem"), os.path.join(d, "privkey.pem")


def has_custom(name: str) -> bool:
    fc, pk = custom_paths(name)
    return os.path.isfile(fc) and os.path.isfile(pk)


def has_le(name: str) -> bool:
    return os.path.isfile(le_paths(name)[0])


def cert_paths(name: str) -> Tuple[str, str]:
    """(fullchain, privkey) que debe servir `name`. Si no hay ninguno devuelve
    las rutas de Let's Encrypt (lo que se escribía siempre hasta ahora)."""
    return custom_paths(name) if has_custom(name) else le_paths(name)


def existing_cert(name: str) -> Optional[str]:
    """fullchain que existe para `name` (propio o Let's Encrypt), o None."""
    fc = cert_paths(name)[0]
    return fc if os.path.isfile(fc) else None


def source(name: str) -> Optional[str]:
    """'custom' | 'letsencrypt' | None."""
    if has_custom(name):
        return "custom"
    return "letsencrypt" if has_le(name) else None


def covers(sans, host: str) -> bool:
    """¿La lista de nombres del certificado cubre `host`? Con comodín de un nivel."""
    host = (host or "").lower().rstrip(".")
    for san in sans or []:
        san = (san or "").lower().rstrip(".")
        if san == host:
            return True
        if san.startswith("*.") and "." in host:
            label, rest = host.split(".", 1)
            if label and rest == san[2:]:
                return True
    return False


def cert_sans(cert_path: str) -> List[str]:
    """Nombres (SAN) del primer certificado del fichero. [] si no se puede leer."""
    try:
        from cryptography import x509
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return ext.value.get_values_for_type(x509.DNSName)
    except Exception:
        pass
    try:   # sin cryptography: openssl
        out = subprocess.run(["openssl", "x509", "-in", cert_path, "-noout", "-ext", "subjectAltName"],
                             capture_output=True, text=True, timeout=10).stdout
        return [t[4:] for t in out.replace(",", " ").split() if t.startswith("DNS:")]
    except Exception:
        return []


def names_of(name: str) -> List[str]:
    """SAN del certificado que sirve `name` ([] si no tiene)."""
    fc = existing_cert(name)
    return cert_sans(fc) if fc else []
