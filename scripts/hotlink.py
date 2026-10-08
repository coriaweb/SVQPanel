"""
Protección contra hotlinking por dominio: que otras webs no muestren tus
imágenes (o vídeos, PDFs) gastando tu ancho de banda.

Domain.hotlink_protection (JSON):
    {"enabled": true, "types": ["images", "media", "docs"],
     "allow_search": true,      # buscadores y redes sociales (Google Imágenes, miniaturas al compartir)
     "allow": ["socio.com"]}    # más webs que sí pueden (y sus subdominios)

En nginx, sin location nuevos (no chocan con la caché de estáticos ni con las
plantillas): un map por $http_referer dice si viene de una web ajena, otro
combina eso con la extensión de $uri, y el server{} hace
`if ($svq_hotlink_<dominio>) { return 403; }`.

Siempre pasan: sin referer (entrar directo, apps, clientes de correo, muchos
navegadores con privacidad estricta), referer que no es una URL (lo recortan
algunos proxies), la propia web, sus subdominios y sus alias.
"""
import json
import re

TYPES = {
    "images": ("jpe?g", "png", "gif", "webp", "avif", "svg", "bmp", "ico"),
    "media":  ("mp4", "webm", "ogv", "mov", "mp3", "ogg", "wav", "m4a"),
    "docs":   ("pdf", "zip", "rar", "7z", "docx?", "xlsx?", "pptx?"),
}
# Buscadores y redes sociales (Google Imágenes, previsualizaciones al compartir…).
# Marcas con cualquier dominio de país (google.es, google.co.uk…) y dominios exactos.
# Anclados al FINAL del nombre: google.webajena.com no cuela.
SEARCH_BRANDS = ("google", "bing", "yahoo", "yandex", "baidu", "duckduckgo", "ecosia", "qwant", "pinterest")
SEARCH_EXACT = ("googleusercontent.com", "gstatic.com", "facebook.com", "fbcdn.net", "instagram.com",
                "whatsapp.com", "whatsapp.net", "twitter.com", "x.com", "t.co", "linkedin.com",
                "telegram.org", "t.me", "reddit.com", "tiktok.com")
_TLD_RX = r"(com|net|org|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})"
MAX_ALLOW = 100
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def defaults() -> dict:
    return {"enabled": False, "types": ["images"], "allow_search": True, "allow": []}


def parse(raw) -> dict:
    out = defaults()
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
            for k in out:
                if data.get(k) is not None:
                    out[k] = data[k]
        except (ValueError, TypeError):
            pass
    return out


def _norm_domain(value: str) -> str:
    v = (value or "").strip().lower().rstrip(".")
    for prefix in ("https://", "http://"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    v = v.split("/")[0].split(":")[0]
    if v.startswith("*."):
        v = v[2:]
    if v.startswith("www."):
        v = v[4:]   # el dominio ya incluye sus subdominios
    return v


def validate(data: dict) -> tuple:
    errors = []
    s = defaults()
    s["enabled"] = bool(data.get("enabled"))
    s["allow_search"] = bool(data.get("allow_search", True))
    types = [t for t in (data.get("types") or []) if t in TYPES]
    bad = [t for t in (data.get("types") or []) if t not in TYPES]
    if bad:
        errors.append("Tipo de fichero no válido: " + ", ".join(map(str, bad)))
    if s["enabled"] and not types:
        errors.append("Elige al menos un tipo de fichero que proteger")
    s["types"] = [t for t in TYPES if t in types]
    allow = []
    for d in data.get("allow") or []:
        n = _norm_domain(str(d))
        if not n:
            continue
        if not _DOMAIN_RE.match(n):
            errors.append(f"Dominio no válido en las webs permitidas: {d}")
            continue
        if n not in allow:
            allow.append(n)
    if len(allow) > MAX_ALLOW:
        errors.append(f"Máximo {MAX_ALLOW} webs permitidas")
    s["allow"] = allow
    return s, errors


def deny_var(domain: str) -> str:
    return "$svq_hotlink_" + domain.replace(".", "_").replace("-", "_")


def render_maps(domain: str, settings: dict, aliases=()) -> str:
    """maps (nivel http). Vacío si la protección está desactivada."""
    if not settings.get("enabled") or not settings.get("types"):
        return ""
    k = domain.replace(".", "_").replace("-", "_")
    own = [domain] + [a for a in aliases if a] + list(settings.get("allow") or [])
    own_rx = "|".join(re.escape(d) for d in dict.fromkeys(own))
    exts = "|".join(e for t in settings["types"] for e in TYPES[t])
    ref = [
        f"map $http_referer $svq_ref_{k} {{",
        "    default 1;                                   # viene de otra web",
        '    "" 0;                                        # sin referer: directo, apps, correo',
        '    "~^(?!https?://)" 0;                         # recortado por un proxy',
        f'    "~*^https?://([^/]+\\.)?({own_rx})(:[0-9]+)?(/|$)" 0;   # la propia web, alias y permitidas',
    ]
    if settings.get("allow_search", True):
        brands = "|".join(SEARCH_BRANDS)
        exact = "|".join(re.escape(d) for d in SEARCH_EXACT)
        ref.append(f'    "~*^https?://([^/]+\\.)?(({brands})\\.{_TLD_RX}|{exact})(:[0-9]+)?(/|$)" 0;'
                   "   # buscadores y redes sociales")
    ref.append("}")
    final = [
        f'map "$svq_ref_{k}:$uri" $svq_hotlink_{k} {{',
        "    default 0;",
        f'    "~*^1:.*\\.({exts})$" 1;',
        "}",
    ]
    return ("# Protección contra hotlinking (lo genera el panel)\n"
            + "\n".join(ref) + "\n" + "\n".join(final) + "\n")
