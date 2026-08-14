"""
Fuente ÚNICA de verdad para la IP real del cliente de una petición HTTP.

⚠️ SEGURIDAD — por qué este módulo existe y por qué NO se lee el primer valor
de `X-Forwarded-For`:

`X-Forwarded-For` la puede enviar el propio cliente y nuestro nginx **no la
reemplaza: la concatena** (usa `$proxy_add_x_forwarded_for`). Si un atacante
manda `X-Forwarded-For: 1.2.3.4`, el backend recibe:

    X-Forwarded-For: 1.2.3.4, <ip_real_del_atacante>
                     ^^^^^^^ valor FALSO elegido por el atacante

Leer `xff.split(",")[0]` (lo que hacíamos hasta v0.222.1, duplicado en tres
helpers distintos) devolvía por tanto una IP arbitraria. Consecuencias reales:

  - Bypass del rate-limit de login: variando el XFF en cada intento el contador
    de fallos nunca acumula → fuerza bruta ilimitada contra el panel.
  - Bypass de la allowlist de IPs de los API tokens (`ApiToken.allowed_ips`):
    un token robado se podía usar desde cualquier IP.
  - Auditoría envenenada: el atacante elegía qué IP quedaba en
    `security_audit_log` y en el auth.log que lee fail2ban.

Orden de resolución (de más fiable a menos):

  1. `X-Real-IP` — nginx la fija SIEMPRE con `proxy_set_header X-Real-IP
     $remote_addr`, sobrescribiendo cualquier valor que enviara el cliente. Es
     la fuente fiable. Además `$remote_addr` ya viene con la IP real resuelta
     cuando está activo el `real_ip` de Cloudflare
     (`real_ip_header CF-Connecting-IP`, ver scripts/cloudflare_realip.py), así
     que este helper es correcto también detrás de Cloudflare.
  2. Último elemento de `X-Forwarded-For` — el que añade nuestro propio nginx al
     concatenar. Los anteriores son los que envió el cliente: NO son de fiar.
  3. `request.client.host` — conexión directa al backend (sin proxy delante).

Equivalente al fix de HestiaCP "Stop trusting unauthenticated proxy headers"
(hestiacp#5273).
"""

from typing import Optional

from fastapi import Request


def client_ip(request: Optional[Request]) -> Optional[str]:
    """IP real del cliente, sin confiar en cabeceras que el cliente controla.

    Devuelve None si no se puede determinar (p. ej. `request` es None).
    Ver el docstring del módulo para el porqué del orden de resolución.
    """
    if request is None:
        return None

    # 1. X-Real-IP: nginx la sobrescribe siempre → fuente fiable.
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    # 2. Último elemento del XFF: el que añadió nuestro nginx. Los de delante
    #    los puso el cliente y son falsificables, por eso NUNCA el primero.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]

    # 3. Sin proxy delante: la IP de la conexión TCP.
    if request.client:
        return request.client.host

    return None
