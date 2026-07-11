"""
Validación de registros DNS antes de guardarlos.

POR QUÉ EXISTE (caso real, jul 2026):
    Un registro CAA se guardó con las comillas sin cerrar:

        @  IN  CAA  0 issue "letsencrypt.org

    BIND no rechaza SOLO ese registro: rechaza la ZONA ENTERA
    ("unbalanced quotes → zone not loaded"). El dominio dejó de resolver en el
    master del cluster y el panel lo reportaba como "ns1 caído" — un síntoma que
    no lleva a ningún sitio. Dos dominios estuvieron horas sin DNS por una comilla.

    La lección: un registro inválido NO es un problema del registro, es un
    problema de TODO el dominio. Hay que pararlo antes de que llegue a BIND.

DOS CAPAS (el validador es la primera; la segunda está en api/routes/dns.py):
    1. validate_record()  → valida el contenido según el tipo. Devuelve el
       contenido normalizado o lanza ValueError con un mensaje para el usuario.
    2. named-checkzone    → antes de publicar, se comprueba que BIND aceptaría la
       zona entera. Si no, se revierte. Es el cinturón por si el validador tiene
       un hueco (tipos raros, casos no contemplados).
"""

import ipaddress
import re
from typing import Optional

# Tags válidos de un registro CAA (RFC 8659)
CAA_TAGS = {"issue", "issuewild", "iodef", "contactemail", "contactphone"}

# Un hostname de DNS: etiquetas alfanuméricas separadas por puntos. Se admite
# el guion (no al principio/final de etiqueta) y el "_" de los DKIM/SRV/DMARC.
_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
HOSTNAME_RE = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*\.?$")

# Tipos cuyo contenido es un hostname (no una IP ni texto libre)
HOSTNAME_TYPES = {"CNAME", "MX", "NS", "PTR", "SRV", "DNAME"}

# Longitud máxima de UNA cadena TXT en el protocolo DNS (RFC 1035 §3.3.14).
# Un TXT más largo es legal, pero hay que trocearlo en varias cadenas entre
# comillas. Las claves DKIM (2048 bits) siempre superan este límite.
TXT_CHUNK = 255


def _quotes_balanced(s: str) -> bool:
    """¿Las comillas dobles están balanceadas (ignorando las escapadas \\")?"""
    return len(re.findall(r'(?<!\\)"', s or "")) % 2 == 0


def _is_hostname(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and len(s) <= 253 and bool(HOSTNAME_RE.match(s))


def _validate_caa(content: str) -> str:
    """
    CAA:  <flags> <tag> "<valor>"     ej:  0 issue "letsencrypt.org"

    Es el que nos rompió dos zonas en producción: sin la comilla de cierre, BIND
    tira la zona entera.
    """
    if not _quotes_balanced(content):
        raise ValueError(
            'El registro CAA tiene comillas sin cerrar. '
            'El formato es: 0 issue "letsencrypt.org" '
            '(fíjate en la comilla del final).'
        )

    m = re.match(r'^\s*(\d+)\s+([A-Za-z]+)\s+"(.*)"\s*$', content or "")
    if not m:
        raise ValueError(
            'Formato de CAA no válido. Debe ser: <flags> <tag> "<valor>" — '
            'por ejemplo: 0 issue "letsencrypt.org"'
        )

    flags, tag, value = m.group(1), m.group(2).lower(), m.group(3)

    if not 0 <= int(flags) <= 255:
        raise ValueError(f"El flag de un CAA va de 0 a 255 (has puesto {flags}).")
    if tag not in CAA_TAGS:
        raise ValueError(
            f'Tag de CAA no válido: "{tag}". Los válidos son: '
            f'{", ".join(sorted(CAA_TAGS))}.'
        )
    if not value.strip():
        raise ValueError("El valor de un CAA no puede estar vacío.")

    return f'{int(flags)} {tag} "{value}"'


def _validate_txt(content: str) -> str:
    """
    TXT: solo se VALIDA, no se reescribe.

    La BD guarda el TXT en crudo (sin comillas) a propósito: es DNSManager.
    _txt_rdata() quien pone las comillas y trocea en cadenas de 255 al generar
    el zone file. Si aquí añadiéramos las comillas, se duplicarían al renderizar
    y además cambiaríamos registros existentes que hoy funcionan.

    Lo único que hay que impedir es lo que rompe la zona en BIND: comillas
    desbalanceadas.
    """
    raw = (content or "").strip()
    if not raw:
        raise ValueError("El contenido de un TXT no puede estar vacío.")

    if not _quotes_balanced(raw):
        raise ValueError(
            "El registro TXT tiene comillas sin cerrar. Cada comilla que se abre "
            "debe cerrarse (o quítalas: el panel las añade solo al publicar)."
        )

    return raw


def _validate_srv(content: str) -> str:
    """
    SRV.

    OJO con el formato: el panel guarda la PRIORIDAD en su propia columna
    (DnsRecord.priority), así que en `content` normalmente vienen solo 3 campos:

        <peso> <puerto> <destino>        ej: 0 587 mail.dominio.com.

    Pero también se admite la forma completa de 4 campos (como se escribe en un
    zone file), por si el registro llega de una importación o de la API:

        <prioridad> <peso> <puerto> <destino>
    """
    parts = (content or "").split()
    if len(parts) == 3:
        nums, target = parts[:2], parts[2]
        labels = ("peso", "puerto")
    elif len(parts) == 4:
        nums, target = parts[:3], parts[3]
        labels = ("prioridad", "peso", "puerto")
    else:
        raise ValueError(
            "Formato de SRV no válido. Debe ser: <peso> <puerto> <destino> — "
            "por ejemplo: 0 587 mail.tudominio.com "
            "(la prioridad se indica en su propio campo)."
        )

    for label, v in zip(labels, nums):
        if not v.isdigit() or not 0 <= int(v) <= 65535:
            raise ValueError(f"La/El {label} de un SRV debe ser un número de 0 a 65535.")
    if target != "." and not _is_hostname(target):
        raise ValueError(f'El destino del SRV no es un hostname válido: "{target}".')
    return content.strip()


def validate_record(record_type: str, content: str,
                    priority: Optional[int] = None) -> str:
    """
    Valida (y normaliza) el contenido de un registro DNS.

    Devuelve el contenido ya normalizado. Lanza ValueError con un mensaje
    dirigido AL USUARIO si el registro no es válido — la ruta lo convierte en un
    422 y el registro nunca llega a la BD ni a BIND.
    """
    rt = (record_type or "").upper().strip()
    val = (content or "").strip()

    if not val:
        raise ValueError("El contenido del registro no puede estar vacío.")

    if rt == "A":
        try:
            ipaddress.IPv4Address(val)
        except ValueError:
            raise ValueError(f'"{val}" no es una dirección IPv4 válida (ej: 192.0.2.1).')
        return val

    if rt == "AAAA":
        try:
            ipaddress.IPv6Address(val)
        except ValueError:
            raise ValueError(
                f'"{val}" no es una dirección IPv6 válida (ej: 2001:db8::1). '
                "Para IPv4 usa un registro de tipo A."
            )
        return val

    if rt == "CAA":
        return _validate_caa(val)

    if rt == "TXT":
        return _validate_txt(val)

    if rt == "SRV":
        return _validate_srv(val)

    if rt in HOSTNAME_TYPES:
        host = val.rstrip(".") if val != "." else val

        # Una IP "parece" un hostname válido (etiquetas separadas por puntos), y
        # BIND la acepta sin rechistar — pero rompe el servicio: un MX o un CNAME
        # DEBEN apuntar a un nombre, no a una dirección (RFC 2181 §10.3). Es un
        # error habitual del cliente y el correo deja de entregarse sin más pista.
        try:
            ipaddress.ip_address(host)
            raise ValueError(
                f'Un registro {rt} debe apuntar a un nombre de dominio, no a una '
                f'IP ("{val}"). Crea un registro A/AAAA con la IP y apunta el {rt} '
                f"a ese nombre (ej: mail.tudominio.com)."
            )
        except ValueError as e:
            # ip_address() lanza ValueError si NO es una IP → es lo que queremos.
            # Pero si el ValueError es el NUESTRO (el de arriba), hay que propagarlo.
            if str(e).startswith(f"Un registro {rt}"):
                raise

        if not _is_hostname(host):
            raise ValueError(
                f'"{val}" no es un hostname válido para un registro {rt}. '
                "Debe ser un nombre de dominio (ej: servidor.dominio.com)."
            )
        return val

    # Tipos que no validamos explícitamente (SOA, NAPTR, TLSA, SSHFP…): solo
    # comprobamos las comillas, que es lo que tumba la zona en BIND. El cinturón
    # de named-checkzone se encarga del resto.
    if not _quotes_balanced(val):
        raise ValueError(
            f"El registro {rt} tiene comillas sin cerrar: cada comilla que se "
            "abre debe cerrarse."
        )
    return val
