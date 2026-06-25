"""
Catálogo de países para bloqueo geográfico (geo-blocking) por listas IP.

Cada país se traduce a una lista IP `block` cuya URL es la zona CIDR agregada de
ipdeny.com (fuente pública y fiable, formato CIDR, URL predecible que solo
cambia el código de país). El sistema de listas IP existente se encarga de
descargar, parsear y aplicar a nftables, con refresco automático.

No imponemos una lista cerrada: ofrecemos un catálogo amplio y el admin activa
los países que quiera con un clic.
"""

from typing import List, Dict

# Plantilla de URL: solo cambia el código ISO-3166 alpha-2 en minúsculas.
# 'aggregated' = rangos CIDR ya agregados (menos entradas, más eficiente en nft).
IPDENY_URL_TMPL = "https://www.ipdeny.com/ipblocks/data/aggregated/{cc}-aggregated.zone"


def country_url(cc: str) -> str:
    return IPDENY_URL_TMPL.format(cc=cc.lower())


# Catálogo curado. 'risk' es una pista para la UI (alto = origen frecuente de
# ataques a hosting). El admin decide; esto es solo orientativo.
#   cc: código ISO-2 | name: nombre | flag: emoji bandera | risk: high|medium
COUNTRY_CATALOG: List[Dict] = [
    {"cc": "dz", "name": "Argelia",             "flag": "🇩🇿", "risk": "medium"},
    {"cc": "ar", "name": "Argentina",           "flag": "🇦🇷", "risk": "medium"},
    {"cc": "sa", "name": "Arabia Saudí",        "flag": "🇸🇦", "risk": "medium"},
    {"cc": "bd", "name": "Bangladés",           "flag": "🇧🇩", "risk": "medium"},
    {"cc": "by", "name": "Bielorrusia",         "flag": "🇧🇾", "risk": "medium"},
    {"cc": "bo", "name": "Bolivia",             "flag": "🇧🇴", "risk": "medium"},
    {"cc": "br", "name": "Brasil",              "flag": "🇧🇷", "risk": "high"},
    {"cc": "bg", "name": "Bulgaria",            "flag": "🇧🇬", "risk": "high"},
    {"cc": "kh", "name": "Camboya",             "flag": "🇰🇭", "risk": "medium"},
    {"cc": "cl", "name": "Chile",               "flag": "🇨🇱", "risk": "medium"},
    {"cc": "cn", "name": "China",               "flag": "🇨🇳", "risk": "high"},
    {"cc": "co", "name": "Colombia",            "flag": "🇨🇴", "risk": "medium"},
    {"cc": "kp", "name": "Corea del Norte",     "flag": "🇰🇵", "risk": "high"},
    {"cc": "kr", "name": "Corea del Sur",       "flag": "🇰🇷", "risk": "medium"},
    {"cc": "eg", "name": "Egipto",              "flag": "🇪🇬", "risk": "medium"},
    {"cc": "ae", "name": "Emiratos Árabes",     "flag": "🇦🇪", "risk": "medium"},
    {"cc": "ec", "name": "Ecuador",             "flag": "🇪🇨", "risk": "medium"},
    {"cc": "ee", "name": "Estonia",             "flag": "🇪🇪", "risk": "medium"},
    {"cc": "ph", "name": "Filipinas",           "flag": "🇵🇭", "risk": "medium"},
    {"cc": "ge", "name": "Georgia",             "flag": "🇬🇪", "risk": "medium"},
    {"cc": "gh", "name": "Ghana",               "flag": "🇬🇭", "risk": "medium"},
    {"cc": "hk", "name": "Hong Kong",           "flag": "🇭🇰", "risk": "medium"},
    {"cc": "in", "name": "India",               "flag": "🇮🇳", "risk": "high"},
    {"cc": "id", "name": "Indonesia",           "flag": "🇮🇩", "risk": "high"},
    {"cc": "iq", "name": "Irak",                "flag": "🇮🇶", "risk": "medium"},
    {"cc": "ir", "name": "Irán",                "flag": "🇮🇷", "risk": "high"},
    {"cc": "jp", "name": "Japón",               "flag": "🇯🇵", "risk": "medium"},
    {"cc": "kz", "name": "Kazajistán",          "flag": "🇰🇿", "risk": "medium"},
    {"cc": "ke", "name": "Kenia",               "flag": "🇰🇪", "risk": "medium"},
    {"cc": "kg", "name": "Kirguistán",          "flag": "🇰🇬", "risk": "medium"},
    {"cc": "lv", "name": "Letonia",             "flag": "🇱🇻", "risk": "medium"},
    {"cc": "lt", "name": "Lituania",            "flag": "🇱🇹", "risk": "medium"},
    {"cc": "ma", "name": "Marruecos",           "flag": "🇲🇦", "risk": "medium"},
    {"cc": "mx", "name": "México",              "flag": "🇲🇽", "risk": "medium"},
    {"cc": "md", "name": "Moldavia",            "flag": "🇲🇩", "risk": "medium"},
    {"cc": "ng", "name": "Nigeria",             "flag": "🇳🇬", "risk": "high"},
    {"cc": "pk", "name": "Pakistán",            "flag": "🇵🇰", "risk": "medium"},
    {"cc": "pa", "name": "Panamá",              "flag": "🇵🇦", "risk": "medium"},
    {"cc": "py", "name": "Paraguay",            "flag": "🇵🇾", "risk": "medium"},
    {"cc": "pe", "name": "Perú",                "flag": "🇵🇪", "risk": "medium"},
    {"cc": "ro", "name": "Rumanía",             "flag": "🇷🇴", "risk": "high"},
    {"cc": "ru", "name": "Rusia",               "flag": "🇷🇺", "risk": "high"},
    {"cc": "rs", "name": "Serbia",              "flag": "🇷🇸", "risk": "medium"},
    {"cc": "sg", "name": "Singapur",            "flag": "🇸🇬", "risk": "medium"},
    {"cc": "lk", "name": "Sri Lanka",           "flag": "🇱🇰", "risk": "medium"},
    {"cc": "za", "name": "Sudáfrica",           "flag": "🇿🇦", "risk": "medium"},
    {"cc": "th", "name": "Tailandia",           "flag": "🇹🇭", "risk": "medium"},
    {"cc": "tw", "name": "Taiwán",              "flag": "🇹🇼", "risk": "medium"},
    {"cc": "tz", "name": "Tanzania",            "flag": "🇹🇿", "risk": "medium"},
    {"cc": "tn", "name": "Túnez",               "flag": "🇹🇳", "risk": "medium"},
    {"cc": "tr", "name": "Turquía",             "flag": "🇹🇷", "risk": "medium"},
    {"cc": "ua", "name": "Ucrania",             "flag": "🇺🇦", "risk": "high"},
    {"cc": "uz", "name": "Uzbekistán",          "flag": "🇺🇿", "risk": "medium"},
    {"cc": "ve", "name": "Venezuela",           "flag": "🇻🇪", "risk": "medium"},
    {"cc": "vn", "name": "Vietnam",             "flag": "🇻🇳", "risk": "high"},
]

_BY_CC = {c["cc"]: c for c in COUNTRY_CATALOG}

# Prefijo del nombre de lista IP que generamos por país, para identificarlas.
LIST_NAME_PREFIX = "geo_"


def list_name_for(cc: str) -> str:
    """Nombre de la lista IP para un país (slug válido: letras/números/_)."""
    return f"{LIST_NAME_PREFIX}{cc.lower()}"


def is_valid_cc(cc: str) -> bool:
    return cc.lower() in _BY_CC


def get_country(cc: str) -> Dict:
    return _BY_CC.get(cc.lower())


def catalog() -> List[Dict]:
    """Catálogo con la URL ya resuelta por país (para la UI), ordenado
    alfabéticamente por nombre (locale-aware para que Á/Ñ etc. caigan bien)."""
    import locale
    def _key(c):
        try:
            return locale.strxfrm(c["name"])
        except Exception:
            # Fallback: normalizar acentos para un orden razonable
            import unicodedata
            return unicodedata.normalize("NFKD", c["name"]).encode("ascii", "ignore").decode().lower()
    out = []
    for c in COUNTRY_CATALOG:
        out.append({**c, "url": country_url(c["cc"]), "list_name": list_name_for(c["cc"])})
    out.sort(key=_key)
    return out
