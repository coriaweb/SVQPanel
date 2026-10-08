"""
Validación DNS-01 de Let's Encrypt con las zonas del panel (certificados wildcard).

certbot se lanza con:
    --manual --preferred-challenges dns
    --manual-auth-hook    "bash /opt/svqpanel/scripts/certbot-dns-hook.sh auth"
    --manual-cleanup-hook "bash /opt/svqpanel/scripts/certbot-dns-hook.sh cleanup"
y guarda esos hooks en /etc/letsencrypt/renewal/<dominio>.conf, así que las
RENOVACIONES automáticas (timer de certbot, sin el panel delante) hacen lo mismo.
El hook llama a `python -m api.cli acme_dns_hook auth|cleanup`, que usa esto.

auth:    añade TXT _acme-challenge.<nombre> = CERTBOT_VALIDATION en la zona del
         panel, la publica (cluster ns1/ns2 o BIND local) y ESPERA a que la sirvan
         todos los nodos: Let's Encrypt pregunta a los NS autoritativos y si uno
         aún no la tiene, la validación falla.
cleanup: borra ese TXT (por nombre Y valor: para dominio y *.dominio certbot
         pone dos valores distintos en el mismo nombre a la vez).

Solo vale para dominios cuya zona DNS está en el panel (sus NS son los nuestros).
"""
import logging
import shlex
import subprocess
import time

logger = logging.getLogger(__name__)

HOOK_SCRIPT = "/opt/svqpanel/scripts/certbot-dns-hook.sh"
CHALLENGE_TTL = 60
WAIT_SECONDS = 180


def hook_args() -> list:
    return ["--manual", "--preferred-challenges", "dns",
            "--manual-auth-hook", f"bash {HOOK_SCRIPT} auth",
            "--manual-cleanup-hook", f"bash {HOOK_SCRIPT} cleanup"]


def _base(name: str) -> str:
    name = (name or "").strip().lower().rstrip(".")
    return name[2:] if name.startswith("*.") else name


def challenge_name(name: str) -> str:
    return f"_acme-challenge.{_base(name)}"


def zone_for(db, name: str):
    """DnsZone del panel que contiene el reto de `name`, o None (DNS externo)."""
    from api.routes.dns import find_parent_zone
    return find_parent_zone(db, challenge_name(name))


def can_validate(db, name: str) -> bool:
    return zone_for(db, name) is not None


def is_dns_lineage(domain: str) -> bool:
    """¿El certificado de certbot de `domain` se valida por DNS con nuestro hook?"""
    try:
        with open(f"/etc/letsencrypt/renewal/{domain}.conf") as f:
            conf = f.read()
        return "authenticator = manual" in conf and "certbot-dns-hook.sh" in conf
    except OSError:
        return False


def _publish(db, zone) -> None:
    from api.routes.dns import _sync_zone_to_bind, _bump_serial
    zone.serial = _bump_serial(zone.serial or 0)
    db.commit()
    _sync_zone_to_bind(zone, db)


def _served_by_all(db, fqdn: str, value: str) -> bool:
    """¿Todos los NS autoritativos sirven el TXT? (cada nodo, preguntado en local)."""
    cmd = f"dig +short +time=3 +tries=1 @127.0.0.1 {shlex.quote(fqdn)} TXT"
    from scripts.dns_cluster import load_cluster, DNSCluster
    cluster = load_cluster(db)
    if not cluster:
        out = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=15).stdout
        return value in out
    cl = DNSCluster(panel_id=cluster["panel_id"])
    for node in (cluster["master"], cluster.get("slave")):
        if not node:
            continue
        rc, out, _ = cl._run_remote(node, cmd, timeout=25)
        if rc != 0 or value not in out:
            return False
    return True


def add_challenge(name: str, value: str, wait: bool = True) -> None:
    from api.models.database import SessionLocal, load_all_models
    from api.models.models_dns import DnsRecord
    from api.routes.dns import subdomain_label
    load_all_models()
    db = SessionLocal()
    try:
        zone = zone_for(db, name)
        if not zone:
            raise RuntimeError(f"La zona DNS de {_base(name)} no está en este panel: "
                               "no se puede validar por DNS (sus NS deben ser los del panel)")
        fqdn = challenge_name(name)
        rel = subdomain_label(fqdn, zone.domain_name)
        exists = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id, DnsRecord.record_type == "TXT",
                                            DnsRecord.name == rel, DnsRecord.content == value).first()
        if not exists:
            db.add(DnsRecord(zone_id=zone.id, record_type="TXT", name=rel, content=value,
                             ttl=CHALLENGE_TTL))
        _publish(db, zone)
        if not wait:
            return
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            if _served_by_all(db, fqdn, value):
                logger.info("acme-dns: %s publicado en todos los NS", fqdn)
                time.sleep(5)   # margen para las réplicas/anycast del resolvedor de LE
                return
            time.sleep(5)
        raise RuntimeError(f"{fqdn} no apareció en todos los servidores DNS en {WAIT_SECONDS}s")
    finally:
        db.close()


def remove_challenge(name: str, value: str = None) -> int:
    """Borra el TXT del reto (solo ese valor si se indica). Devuelve cuántos."""
    from api.models.database import SessionLocal, load_all_models
    from api.models.models_dns import DnsRecord
    from api.routes.dns import subdomain_label
    load_all_models()
    db = SessionLocal()
    try:
        zone = zone_for(db, name)
        if not zone:
            return 0
        rel = subdomain_label(challenge_name(name), zone.domain_name)
        q = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id, DnsRecord.record_type == "TXT",
                                       DnsRecord.name == rel)
        if value:
            q = q.filter(DnsRecord.content == value)
        n = 0
        for r in q.all():
            db.delete(r)
            n += 1
        if n:
            _publish(db, zone)
        return n
    finally:
        db.close()
