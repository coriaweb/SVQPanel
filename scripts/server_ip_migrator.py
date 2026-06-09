"""
Migrador de la IP principal del servidor.

Cambia la IPv4 principal del servidor y la propaga en cascada: BD del panel
(settings/domains/dns_records), zonas BIND, vhosts nginx y, opcionalmente, la
config de red del SO (Netplan).

OPERACIÓN PELIGROSA. Reconfigurar la red del SO puede dejar el servidor
incomunicado si la IP nueva no está enrutada por el proveedor. Por eso:
  - Solo se ejecuta por CLI (root), nunca desde la web.
  - Hace BACKUP de todo antes de tocar nada.
  - Patrón commit/confirm: tras aplicar la red, programa una AUTO-REVERSIÓN; si
    el admin no ejecuta `--confirm` en N minutos, vuelve sola a la IP vieja.
  - `--no-os-network` propaga todo MENOS la red del SO (caso: el proveedor ya
    cambió la IP, solo hay que propagar) — sin riesgo de incomunicar.

Reutiliza: api.routes.dns._sync_zone_to_bind (regenera zona desde BD),
api.cli.cmd_migrate_php_pools (regenera vhosts).
"""
import os
import re
import json
import time
import shutil
import logging
import subprocess
import ipaddress
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_DIR = "/var/lib/svqpanel/ip-migration"
CONFIRM_FLAG = os.path.join(STATE_DIR, "pending-confirm.json")
NETPLAN_DIR = "/etc/netplan"
# netplan propio con prioridad alta (gana a cloud-init); evita que cloud-init
# revierta la IP en reboot.
NETPLAN_SVQ = os.path.join(NETPLAN_DIR, "99-svqpanel-ip.yaml")


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Detección de la red actual del SO
# ─────────────────────────────────────────────────────────────────────────────
def detect_primary() -> dict:
    """Devuelve {ip, prefix, iface, gateway} de la ruta por defecto IPv4."""
    out = {"ip": None, "prefix": 24, "iface": None, "gateway": None}
    try:
        r = subprocess.run(["ip", "-j", "route", "get", "8.8.8.8"],
                           capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout)
        if data:
            out["iface"] = data[0].get("dev")
            out["ip"] = data[0].get("prefsrc")
            out["gateway"] = data[0].get("gateway")
    except Exception:
        pass
    # prefix de la IP en esa interfaz
    if out["iface"] and out["ip"]:
        try:
            r = subprocess.run(["ip", "-j", "addr", "show", out["iface"]],
                               capture_output=True, text=True, timeout=10)
            for a in json.loads(r.stdout)[0].get("addr_info", []):
                if a.get("local") == out["ip"] and a.get("family") == "inet":
                    out["prefix"] = a.get("prefixlen", 24)
                    break
        except Exception:
            pass
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Preview / plan del cambio (para el aviso de riesgos)
# ─────────────────────────────────────────────────────────────────────────────
def plan_change(old_ip: str, new_ip: str) -> dict:
    """Cuenta qué se va a tocar. No cambia nada."""
    from api.models.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        def _count(q, p):
            return db.execute(text(q), p).scalar() or 0
        return {
            "settings":    _count("SELECT count(*) FROM settings WHERE server_ipv4=:ip", {"ip": old_ip}),
            "domains":     _count("SELECT count(*) FROM domains WHERE ipv4=:ip", {"ip": old_ip}),
            "dns_records": _count("SELECT count(*) FROM dns_records WHERE content=:ip AND record_type IN ('A')", {"ip": old_ip}),
            "os_detected": detect_primary(),
        }
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Backup del estado antes de tocar
# ─────────────────────────────────────────────────────────────────────────────
def backup_state(old_ip: str, new_ip: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = os.path.join(STATE_DIR, ts)
    os.makedirs(d, exist_ok=True)
    # 1) Config de red del SO (todos los netplan)
    if os.path.isdir(NETPLAN_DIR):
        shutil.copytree(NETPLAN_DIR, os.path.join(d, "netplan"), dirs_exist_ok=True)
    # 2) Dump de las tablas afectadas
    try:
        env = dict(os.environ)
        pw = os.getenv("PGPASSWORD") or _pg_password()
        if pw:
            env["PGPASSWORD"] = pw
        subprocess.run(
            ["pg_dump", "-h", "localhost", "-U", _pg_user(), "-d", _pg_db(),
             "-t", "settings", "-t", "domains", "-t", "dns_records",
             "-f", os.path.join(d, "tables.sql")],
            env=env, capture_output=True, timeout=120)
    except Exception as e:
        logger.warning("pg_dump del backup falló: %s", e)
    # 3) Zonas BIND
    if os.path.isdir("/etc/bind/zones"):
        shutil.copytree("/etc/bind/zones", os.path.join(d, "zones"), dirs_exist_ok=True)
    # 4) Metadatos
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump({"old_ip": old_ip, "new_ip": new_ip, "ts": ts,
                   "os": detect_primary()}, f)
    logger.info("Backup del estado en %s", d)
    return d


def _pg_user():  return os.getenv("PGUSER", "panel_user")
def _pg_db():    return os.getenv("PGDATABASE", "panel_db")
def _pg_password():
    # Intentar leer de DATABASE_URL del .env del panel
    try:
        url = os.getenv("DATABASE_URL", "")
        m = re.search(r"://[^:]+:([^@]+)@", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return os.getenv("PGPASSWORD")


# ─────────────────────────────────────────────────────────────────────────────
# Propagación en BD
# ─────────────────────────────────────────────────────────────────────────────
def apply_db(old_ip: str, new_ip: str) -> dict:
    """Reemplaza la IP vieja por la nueva en settings/domains/dns_records."""
    from api.models.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        r1 = db.execute(text("UPDATE settings SET server_ipv4=:n WHERE server_ipv4=:o"),
                        {"n": new_ip, "o": old_ip}).rowcount
        # settings: si estaba vacío, fijarlo igualmente a la nueva
        db.execute(text("UPDATE settings SET server_ipv4=:n WHERE id=1 AND (server_ipv4 IS NULL OR server_ipv4='')"),
                   {"n": new_ip})
        r2 = db.execute(text("UPDATE domains SET ipv4=:n WHERE ipv4=:o"),
                        {"n": new_ip, "o": old_ip}).rowcount
        r3 = db.execute(text("UPDATE dns_records SET content=:n WHERE content=:o AND record_type='A'"),
                        {"n": new_ip, "o": old_ip}).rowcount
        db.commit()
        logger.info("BD: settings=%s domains=%s dns_records=%s actualizados", r1, r2, r3)
        return {"settings": r1, "domains": r2, "dns_records": r3}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Regenerar zonas DNS y vhosts (reutiliza el código del panel)
# ─────────────────────────────────────────────────────────────────────────────
def regen_dns() -> int:
    """Regenera TODAS las zonas activas desde la BD (reusa _sync_zone_to_bind).
    También sube el serial de cada zona para que el cambio propague."""
    from api.models.database import SessionLocal
    from api.models.models_dns import DnsZone
    from api.routes.dns import _sync_zone_to_bind
    from scripts.dns_manager import DNSManager
    db = SessionLocal()
    n = 0
    try:
        mgr = DNSManager()
        zones = db.query(DnsZone).all()
        for z in zones:
            try:
                z.serial = mgr._next_serial(z.serial)   # bump serial
                db.commit()
                _sync_zone_to_bind(z, db)
                n += 1
            except Exception as e:
                logger.error("regen zona %s falló: %s", z.domain_name, e)
        return n
    finally:
        db.close()


def regen_vhosts() -> bool:
    """Regenera todos los vhosts nginx (reusa migrate_php_pools --force)."""
    try:
        from api.cli import cmd_migrate_php_pools
        cmd_migrate_php_pools(force=True)
        subprocess.run(["nginx", "-t"], check=True, capture_output=True)
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True)
        return True
    except Exception as e:
        logger.error("regen vhosts falló: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Red del SO (Netplan) — LA PARTE PELIGROSA
# ─────────────────────────────────────────────────────────────────────────────
def apply_os_network(new_ip: str, prefix: int = None, iface: str = None,
                     gateway: str = None) -> bool:
    """Escribe un netplan propio (99-svqpanel-ip.yaml, prioridad alta sobre
    cloud-init) con la IP nueva y aplica. Devuelve True si netplan apply OK."""
    cur = detect_primary()
    iface = iface or cur["iface"]
    prefix = prefix or cur["prefix"] or 24
    gateway = gateway or cur["gateway"]
    if not iface:
        logger.error("No se detectó la interfaz de red; abortando cambio de red")
        return False
    content = f"""# SVQPanel — IP principal del servidor (gestionado por change_server_ip)
# Prioridad alta para ganar a cloud-init. NO editar a mano.
network:
  version: 2
  ethernets:
    {iface}:
      addresses:
        - {new_ip}/{prefix}
      routes:
        - to: default
          via: {gateway}
"""
    with open(NETPLAN_SVQ, "w") as f:
        f.write(content)
    os.chmod(NETPLAN_SVQ, 0o600)
    try:
        subprocess.run(["netplan", "apply"], check=True, capture_output=True, timeout=30)
        logger.info("netplan apply OK con IP %s/%s en %s", new_ip, prefix, iface)
        return True
    except Exception as e:
        logger.error("netplan apply falló: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Auto-reversión (commit/confirm)
# ─────────────────────────────────────────────────────────────────────────────
def schedule_autorevert(backup_dir: str, timeout_min: int) -> None:
    """Programa una reversión de la RED del SO en timeout_min minutos, salvo que
    se haya confirmado. Usa systemd-run (transitorio, sobrevive a la sesión SSH)."""
    with open(CONFIRM_FLAG, "w") as f:
        json.dump({"backup_dir": backup_dir, "scheduled_at": time.time(),
                   "timeout_min": timeout_min}, f)
    # systemd-run lanza el rollback de red a los N min; si confirman, se cancela
    # borrando el flag (el job comprueba el flag antes de revertir).
    subprocess.run(
        ["systemd-run", f"--on-active={timeout_min}min",
         "--unit=svqpanel-ip-autorevert",
         "/opt/svqpanel/venv/bin/python", "-m", "api.cli",
         "change_server_ip", "--autorevert-check"],
        capture_output=True)
    logger.warning("Auto-reversión de red programada para %s min. Ejecuta "
                   "`change_server_ip --confirm` para hacerlo firme.", timeout_min)


def autorevert_check() -> int:
    """Lo ejecuta el timer: si el flag de confirmación SIGUE pendiente (no se
    confirmó), revierte la red del SO desde el backup. Si se confirmó (flag
    borrado), no hace nada."""
    if not os.path.exists(CONFIRM_FLAG):
        logger.info("Cambio de IP confirmado; auto-reversión no necesaria.")
        return 0
    try:
        with open(CONFIRM_FLAG) as f:
            info = json.load(f)
    except Exception:
        return 0
    logger.warning("NO se confirmó el cambio de IP en plazo → revirtiendo la red del SO")
    _restore_network(info.get("backup_dir"))
    os.remove(CONFIRM_FLAG)
    return 0


def confirm() -> int:
    """Marca el cambio como firme: cancela la auto-reversión."""
    subprocess.run(["systemctl", "stop", "svqpanel-ip-autorevert.timer"],
                   capture_output=True)
    if os.path.exists(CONFIRM_FLAG):
        os.remove(CONFIRM_FLAG)
    logger.info("Cambio de IP CONFIRMADO. Auto-reversión cancelada.")
    return 0


def _restore_network(backup_dir: str) -> None:
    """Restaura la config de red del SO desde un backup y reaplica."""
    if not backup_dir:
        return
    src = os.path.join(backup_dir, "netplan")
    if os.path.isdir(src):
        # Quitar nuestro netplan propio y restaurar los originales
        try:
            if os.path.exists(NETPLAN_SVQ):
                os.remove(NETPLAN_SVQ)
        except OSError:
            pass
        shutil.copytree(src, NETPLAN_DIR, dirs_exist_ok=True)
        subprocess.run(["netplan", "apply"], capture_output=True, timeout=30)
        logger.info("Red del SO restaurada desde %s", backup_dir)


def rollback(backup_dir: str = None) -> int:
    """Rollback COMPLETO manual: red del SO + BD + zonas, desde el backup más
    reciente (o el indicado)."""
    if not backup_dir:
        # el más reciente
        try:
            subs = sorted(os.listdir(STATE_DIR))
            backup_dir = os.path.join(STATE_DIR, subs[-1]) if subs else None
        except OSError:
            backup_dir = None
    if not backup_dir or not os.path.isdir(backup_dir):
        logger.error("No hay backup para revertir.")
        return 1
    meta = {}
    try:
        with open(os.path.join(backup_dir, "meta.json")) as f:
            meta = json.load(f)
    except Exception:
        pass
    # 1) Red del SO
    _restore_network(backup_dir)
    # 2) BD: invertir (new→old)
    old_ip, new_ip = meta.get("old_ip"), meta.get("new_ip")
    if old_ip and new_ip:
        apply_db(new_ip, old_ip)
        regen_dns()
        regen_vhosts()
    if os.path.exists(CONFIRM_FLAG):
        os.remove(CONFIRM_FLAG)
    logger.info("Rollback completo desde %s", backup_dir)
    return 0
