"""
Acceso por país e IP POR DOMINIO (en nginx, el front en los dos modos).

Reglas de un dominio (Domain.access_rules, JSON):
    {
      "site_mode": "off" | "allow" | "block",   # toda la web
      "site_countries": ["ES", ...],             # allow = solo estos; block = todos menos estos
      "login_countries": ["ES", ...],            # admin de WordPress: solo desde estos ([] = sin límite)
      "ip_allow": ["1.2.3.4", "10.0.0.0/8"],     # siempre entran (ganan a los países)
      "ip_block": ["5.6.7.8"]                    # nunca entran
    }

Cómo se aplica (sin módulos nuevos de nginx: `geo` + `map`, de serie):
- País de la IP: `geo $svq_cc` GLOBAL (conf.d/svqpanel-geo-global.conf) que
  incluye /var/lib/svqpanel/geo/nginx-countries.conf con los rangos SOLO de los
  países que usa algún dominio (España ≈ 18 000 rangos v4+v6). Para "solo
  España" basta con conocer los rangos de España: el resto cae en el default "".
- Por dominio, conf.d/svqpanel-access-{dominio}.conf: un `geo` con sus IPs y
  `map`s que combinan IP + país + URI en una variable $svq_deny_<dominio>; el
  vhost hace `if ($svq_deny_<dominio>) { return 403; }` en sus server{}.
- El reto ACME (/.well-known/acme-challenge/) queda SIEMPRE fuera: Let's Encrypt
  valida desde EEUU/Europa y un "solo España" rompería emisión y renovaciones.
  Va dentro del map (y no en un location) porque el `if` de la fase rewrite se
  evalúa antes que cualquier location.
- Se usa $uri (normalizado: sin %xx ni barras dobles), así `//wp-login.php` o
  `/wp-login%2Ephp` no esquivan la regla del login.
- La IP es $remote_addr, que ya es la real tras Cloudflare (real_ip global).

Fuente de los rangos: la base local DB-IP lite (la de GoAccess, se renueva cada
mes en scripts/web_stats.py). Recorrerla entera cuesta ~30 s, así que una sola
pasada deja un fichero por país en /var/lib/svqpanel/geo/cc/ (caché ligada al
mtime de la base) y montar la lista para nginx es luego instantáneo.
"""
import ipaddress
import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

GEO_DIR = "/var/lib/svqpanel/geo"
CC_DIR = os.path.join(GEO_DIR, "cc")
NAMES_FILE = os.path.join(GEO_DIR, "countries.json")
SOURCE_STAMP = os.path.join(GEO_DIR, ".source")
UNION_FILE = os.path.join(GEO_DIR, "nginx-countries.conf")
GLOBAL_CONF = "/etc/nginx/conf.d/svqpanel-geo-global.conf"

MAX_IPS = 500
SITE_MODES = ("off", "allow", "block")
_CC_RE = re.compile(r"^[A-Z]{2}$")

# Rutas de administración de WordPress que limita "login_countries". admin-ajax
# y admin-post quedan fuera: los usan formularios y plugins de la parte pública.
_LOGIN_RE = r"/(?:wp-login\.php|xmlrpc\.php|wp-admin(?:/(?!admin-ajax\.php|admin-post\.php)|$))"

_cache_lock = threading.Lock()


# ── Reglas ─────────────────────────────────────────────────────────────────
def empty_rules() -> dict:
    return {"site_mode": "off", "site_countries": [], "login_countries": [],
            "ip_allow": [], "ip_block": []}


def parse_rules(raw) -> dict:
    """De la columna (JSON o None) a un dict completo con todas las claves."""
    rules = empty_rules()
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
            for k in rules:
                if k in data and data[k] is not None:
                    rules[k] = data[k]
        except (ValueError, TypeError):
            pass
    return rules


def is_active(rules: dict) -> bool:
    """¿Bloquea algo? (las IPs permitidas solas no cambian nada)."""
    return bool((rules.get("site_mode") in ("allow", "block") and rules.get("site_countries"))
                or rules.get("login_countries") or rules.get("ip_block"))


def _norm_net(value: str) -> str:
    net = ipaddress.ip_network(value.strip(), strict=False)
    return str(net.network_address) if net.num_addresses == 1 else str(net)


def validate_rules(data: dict, known_countries=None) -> tuple:
    """Normaliza y valida. Devuelve (rules, errores)."""
    errors = []
    rules = empty_rules()
    mode = (data.get("site_mode") or "off").strip().lower()
    if mode not in SITE_MODES:
        errors.append("Modo de acceso por país no válido")
        mode = "off"
    rules["site_mode"] = mode

    for key, label in (("site_countries", "países de la web"),
                       ("login_countries", "países del acceso de administración")):
        out = []
        for cc in data.get(key) or []:
            cc = str(cc).strip().upper()
            if not _CC_RE.match(cc) or (known_countries and cc not in known_countries):
                errors.append(f"Código de país no válido en {label}: {cc}")
                continue
            if cc not in out:
                out.append(cc)
        rules[key] = sorted(out)
    if mode != "off" and not rules["site_countries"]:
        errors.append("Elige al menos un país (o desactiva el filtro por país)")

    for key, label in (("ip_allow", "IPs permitidas"), ("ip_block", "IPs bloqueadas")):
        out = []
        for ip in data.get(key) or []:
            ip = str(ip).strip()
            if not ip:
                continue
            try:
                n = _norm_net(ip)
            except ValueError:
                errors.append(f"IP o rango no válido en {label}: {ip}")
                continue
            if n not in out:
                out.append(n)
        if len(out) > MAX_IPS:
            errors.append(f"Máximo {MAX_IPS} entradas en {label}")
        rules[key] = out
    both = set(rules["ip_allow"]) & set(rules["ip_block"])
    if both:
        errors.append("Estas IPs están a la vez en permitidas y bloqueadas: " + ", ".join(sorted(both)))
    return rules, errors


def would_block(rules: dict, ip: str, country: str, uri: str = "/") -> bool:
    """Misma lógica que el map de nginx, para avisar al usuario antes de guardar
    (p. ej. "tu IP quedaría bloqueada")."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if uri.startswith("/.well-known/acme-challenge/"):
        return False
    nets = lambda key: [ipaddress.ip_network(n, strict=False) for n in rules.get(key) or []]
    if any(addr in n for n in nets("ip_allow")):
        return False
    if any(addr in n for n in nets("ip_block")):
        return True
    cc = (country or "").upper()
    mode, sc = rules.get("site_mode"), set(rules.get("site_countries") or [])
    if mode == "allow" and sc and cc not in sc:
        return True
    if mode == "block" and cc in sc:
        return True
    lc = set(rules.get("login_countries") or [])
    return bool(lc and cc not in lc and re.match(_LOGIN_RE, uri))


# ── Config de nginx ────────────────────────────────────────────────────────
def var_key(domain: str) -> str:
    return domain.replace(".", "_").replace("-", "_")


def deny_var(domain: str) -> str:
    return f"$svq_deny_{var_key(domain)}"


def domain_conf_path(domain: str) -> str:
    return f"/etc/nginx/conf.d/svqpanel-access-{domain}.conf"


def _country_map(var: str, mode: str, countries) -> str:
    ccs = [c.lower() for c in countries or []]
    if mode == "allow" and ccs:      # solo estos: el resto (y lo desconocido) = 1
        lines = ["    default 1;"] + [f"    {c} 0;" for c in ccs]
    elif mode == "block" and ccs:    # estos fuera: el resto = 0
        lines = ["    default 0;"] + [f"    {c} 1;" for c in ccs]
    else:
        lines = ["    default 0;"]
    return f"map $svq_cc {var} {{\n" + "\n".join(lines) + "\n}\n"


def render_domain_conf(domain: str, rules: dict) -> str:
    k = var_key(domain)
    geo = [f"geo $svq_ip_{k} {{", '    default "-";']
    geo += [f"    {n} a;" for n in rules.get("ip_allow") or []]
    geo += [f"    {n} b;" for n in rules.get("ip_block") or []]
    geo.append("}")
    # Clave "IP:país-web:país-admin:URI". Primera regex que casa gana (orden).
    final = [
        f'map "$svq_ip_{k}:$svq_cs_{k}:$svq_cl_{k}:$uri" $svq_deny_{k} {{',
        "    default 0;",
        '    "~^.:.:.:/\\.well-known/acme-challenge/" 0;   # Let\'s Encrypt siempre',
        '    "~^a:" 0;                                     # IP permitida',
        '    "~^b:" 1;                                     # IP bloqueada',
        '    "~^-:1:" 1;                                   # país sin acceso a la web',
        f'    "~^-:0:1:{_LOGIN_RE}" 1;   # admin de WordPress desde otro país',
        "}",
    ]
    return (f"# SVQPanel — acceso por país/IP de {domain} (lo genera el panel)\n"
            + "\n".join(geo) + "\n"
            + _country_map(f"$svq_cs_{k}", rules.get("site_mode"), rules.get("site_countries"))
            + _country_map(f"$svq_cl_{k}", "allow", rules.get("login_countries"))
            + "\n".join(final) + "\n")


def render_global_conf() -> str:
    return ("# SVQPanel — país de la IP del visitante (nivel http). Solo trae los\n"
            "# rangos de los países que usa algún dominio; el resto queda en \"\".\n"
            "geo $svq_cc {\n"
            '    default "";\n'
            f"    include {UNION_FILE};\n"
            "}\n")


def ensure_global() -> None:
    """El geo global debe existir mientras algún vhost use $svq_cc (si no,
    nginx no arranca: "unknown variable"), así que se asegura en cada regeneración."""
    os.makedirs(GEO_DIR, exist_ok=True)
    if not os.path.isfile(UNION_FILE):
        with open(UNION_FILE, "w") as f:
            f.write("# vacío: ningún dominio filtra por país\n")
    if not os.path.isfile(GLOBAL_CONF):
        with open(GLOBAL_CONF, "w", encoding="utf-8") as f:
            f.write(render_global_conf())


def remove_domain_conf(domain: str) -> None:
    try:
        os.remove(domain_conf_path(domain))
    except FileNotFoundError:
        pass


# ── Caché de rangos por país (desde la base DB-IP local) ───────────────────
def _source_id():
    from scripts.web_stats import geoip_db_path
    path = geoip_db_path()
    if not path or not os.path.isfile(path):
        return None, None
    st = os.stat(path)
    return path, f"{int(st.st_mtime)}:{st.st_size}"


def cache_ready() -> bool:
    _, sid = _source_id()
    try:
        with open(SOURCE_STAMP) as f:
            return bool(sid) and f.read().strip() == sid and os.path.isfile(NAMES_FILE)
    except OSError:
        return False


def build_country_cache(force: bool = False) -> bool:
    """Una pasada por la base → cc/<CC>.txt (un rango por línea) + countries.json.
    ~30 s; en streaming (no guarda 1,4M redes en memoria). Idempotente."""
    with _cache_lock:
        if not force and cache_ready():
            return True
        path, sid = _source_id()
        if not path:
            try:
                from scripts.web_stats import update_geoip_db
                update_geoip_db()
            except Exception as e:
                logger.warning("geo: no se pudo descargar la base de países: %s", e)
            path, sid = _source_id()
            if not path:
                return False
        import maxminddb
        tmp = CC_DIR + ".tmp"
        os.makedirs(tmp, exist_ok=True)
        for f in os.listdir(tmp):
            os.remove(os.path.join(tmp, f))
        files, names = {}, {}
        try:
            with maxminddb.open_database(path) as reader:
                for net, rec in reader:
                    country = (rec or {}).get("country") or {}
                    cc = country.get("iso_code")
                    if not cc or not _CC_RE.match(cc):
                        continue
                    fh = files.get(cc)
                    if fh is None:
                        fh = files[cc] = open(os.path.join(tmp, cc + ".txt"), "w")
                        n = country.get("names") or {}
                        names[cc] = n.get("es") or n.get("en") or cc
                    fh.write(f"{net}\n")
        finally:
            for fh in files.values():
                fh.close()
        old = CC_DIR + ".old"
        if os.path.isdir(CC_DIR):
            os.replace(CC_DIR, old)
        os.replace(tmp, CC_DIR)
        if os.path.isdir(old):
            for f in os.listdir(old):
                os.remove(os.path.join(old, f))
            os.rmdir(old)
        with open(NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, sort_keys=True)
        with open(SOURCE_STAMP, "w") as f:
            f.write(sid)
        logger.info("geo: caché de rangos por país regenerada (%d países)", len(names))
        return True


def country_names() -> dict:
    """{"ES": "España", ...} de la base local ({} si la caché aún no está)."""
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def lookup_country(ip: str) -> str:
    """Código de país de una IP con la base local ("" si no se sabe)."""
    path, _ = _source_id()
    if not path or not ip:
        return ""
    try:
        import maxminddb
        with maxminddb.open_database(path) as r:
            rec = r.get(ip) or {}
        return ((rec.get("country") or {}).get("iso_code") or "").upper()
    except Exception:
        return ""


def countries_in_use(db) -> set:
    from api.models.models_domain import Domain
    used = set()
    for (raw,) in db.query(Domain.access_rules).filter(Domain.access_rules.isnot(None)).all():
        r = parse_rules(raw)
        if not is_active(r):
            continue
        if r["site_mode"] in ("allow", "block"):
            used.update(r["site_countries"])
        used.update(r["login_countries"])
    return used


def rebuild_union(db) -> int:
    """Reescribe la lista global con los países que usa algún dominio.
    Devuelve el nº de rangos. Si cambia, hace falta recargar nginx."""
    used = countries_in_use(db)
    if used and not cache_ready():
        build_country_cache()
    os.makedirs(GEO_DIR, exist_ok=True)
    lines = 0
    tmp = UNION_FILE + ".tmp"
    with open(tmp, "w") as out:
        out.write("# SVQPanel — rangos de: " + (", ".join(sorted(used)) or "ninguno") + "\n")
        for cc in sorted(used):
            try:
                with open(os.path.join(CC_DIR, cc + ".txt")) as f:
                    for net in f:
                        net = net.strip()
                        if net:
                            out.write(f"{net} {cc.lower()};\n")
                            lines += 1
            except FileNotFoundError:
                logger.warning("geo: sin rangos para %s en la base", cc)
    os.replace(tmp, UNION_FILE)
    return lines


def apply_domain(domain: str, raw_rules, db=None):
    """Lo llama regenerate_vhost ANTES de escribir el vhost. Escribe (o borra) el
    conf del dominio y deja al día la lista global. Devuelve la variable que el
    vhost debe comprobar, o None si el dominio no filtra nada."""
    rules = parse_rules(raw_rules)
    if not is_active(rules):
        remove_domain_conf(domain)
        return None
    ensure_global()
    with open(domain_conf_path(domain), "w", encoding="utf-8") as f:
        f.write(render_domain_conf(domain, rules))
    own_db = db is None
    if own_db:
        from api.models.database import SessionLocal
        db = SessionLocal()
    try:
        rebuild_union(db)
    finally:
        if own_db:
            db.close()
    return deny_var(domain)


def refresh_after_db_update() -> None:
    """Tras renovar la base de países (mensual): rehace la caché y la lista
    global y recarga nginx, si algún dominio filtra por país."""
    from api.models.database import SessionLocal
    db = SessionLocal()
    try:
        if not countries_in_use(db):
            return
        build_country_cache(force=True)
        rebuild_union(db)
    finally:
        db.close()
    from scripts.utils import reload_nginx
    reload_nginx()


def warm_cache_async() -> None:
    """Prepara la caché en segundo plano (para que el selector tenga los nombres
    y el primer guardado no espere 30 s). No hace nada si ya está al día."""
    def _run():
        try:
            build_country_cache()
        except Exception:
            logger.exception("geo: error preparando la caché de países")
    if not cache_ready():
        threading.Thread(target=_run, daemon=True, name="geo-cache").start()
