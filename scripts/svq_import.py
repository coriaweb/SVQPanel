"""
Migrador SVQPanel → SVQPanel · FASE 2: recrear la cuenta en el DESTINO a partir
del JSON de `export_account` (fase 1, scripts/svq_export.py).

Qué hace: usuario (Linux + panel, con sus contraseñas), dominios (estructura,
pool PHP, certificados, vhost con todos sus ajustes), alias y despliegues Git,
BDs MariaDB (mismos usuarios y hashes), correo (dominios, buzones con su hash,
reenvíos, autorespuestas, alias, DKIM, ajustes de Rspamd), zonas DNS, crons y
subcuentas SFTP.

Qué NO hace (fases siguientes): copiar archivos, correo y datos de las BDs
(fase 3: rsync + volcado en streaming) ni publicar el DNS (fase 4, corte).

Decisiones de seguridad:
  - Las zonas DNS se crean INACTIVAS y no se publican: si origen y destino
    comparten cluster DNS, publicarlas ahora movería las visitas a un servidor
    aún sin datos. El chequeo de salud del cluster solo toca zonas activas.
  - plan_import() no toca nada: es el "Analizar" de la UI (conflictos, PHP que
    falta, espacio, avisos). apply_import() se niega si hay conflictos.
  - Todo lo que toca el sistema pasa por `Ops`: los tests la sustituyen y
    verifican la lógica sobre una BD de prueba.
  - Un fallo en un recurso se anota en el informe y se sigue con el resto.
"""

import base64
import datetime as _dt
import json
import logging
import os
import secrets
import shutil
import subprocess
from typing import Dict, List, Optional

from scripts.svq_export import FORMAT, FORMAT_VERSION, NATURAL_KEYS, _fernet

logger = logging.getLogger(__name__)


class SvqImportError(RuntimeError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Valores: JSON del export → columnas del destino
# ─────────────────────────────────────────────────────────────────────────────
def _model_for(table):
    from api.models.database import Base
    for m in Base.registry.mappers:
        if m.local_table is table:
            return m.class_
    raise SvqImportError(f"sin modelo para la tabla {table.name}")


def resolve_ref(db, ref) -> Optional[int]:
    """{"$ref": tabla, "key": clave natural} → id en el destino (o None)."""
    if not isinstance(ref, dict) or "$ref" not in ref:
        return None
    from sqlalchemy import select
    from api.models.database import Base
    t = Base.metadata.tables.get(ref["$ref"])
    col = NATURAL_KEYS.get(ref["$ref"])
    if t is None or not col or ref.get("key") is None:
        return None
    return db.execute(select(t.c.id).where(t.c[col] == ref["key"])).scalar()


def decode_value(column, v, fernets: Dict):
    if isinstance(v, dict):
        if "$dt" in v:
            s = v["$dt"]
            try:
                pt = column.type.python_type
            except NotImplementedError:
                pt = _dt.datetime
            return _dt.date.fromisoformat(s[:10]) if pt is _dt.date else _dt.datetime.fromisoformat(s)
        if "$b64" in v:
            return base64.b64decode(v["$b64"])
        if "$enc" in v:
            f = fernets.get(v.get("key") or "panel")
            return f.encrypt(v["$enc"].encode()).decode() if f else None
    return v


def build_row(db, tname: str, row: Dict, fernets: Dict, overrides: Dict = None,
              unknown: Optional[set] = None):
    """Objeto ORM nuevo de `tname` con los valores del export. Las FK se
    traducen por clave natural; columnas que el destino no tiene se ignoran
    (origen más nuevo) y las que el export no trae quedan con su default."""
    from api.models.database import Base
    table = Base.metadata.tables[tname]
    model = _model_for(table)
    values = {}
    for col in table.columns:
        if col.primary_key or col.name not in row:
            continue
        v = row[col.name]
        values[col.name] = resolve_ref(db, v) if col.foreign_keys else decode_value(col, v, fernets)
    if unknown is not None:
        unknown.update(f"{tname}.{k}" for k in row if k not in table.columns)
    values.update(overrides or {})
    obj = model(**values)
    db.add(obj)
    db.flush()
    return obj


def _dest_fernets() -> Dict:
    return dict(_fernet())


# ─────────────────────────────────────────────────────────────────────────────
# Efectos sobre el sistema (los tests la sustituyen)
# ─────────────────────────────────────────────────────────────────────────────
class Ops:
    def linux_user_exists(self, name: str) -> bool:
        return subprocess.run(["id", name], capture_output=True).returncode == 0

    def installed_php(self) -> List[str]:
        from scripts.hestia_import import installed_php_versions
        return installed_php_versions()

    def resolve_php(self, wanted: Optional[str]) -> str:
        from scripts.hestia_import import resolve_php_version
        return resolve_php_version(wanted)

    def free_bytes(self, path: str = "/home") -> Optional[int]:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def server_ips(self, db) -> Dict:
        from scripts.svq_export import _server_ips
        return _server_ips()

    def mariadb(self, sql: str) -> str:
        from api.routes.databases import _run_mariadb
        return _run_mariadb(sql)

    def mariadb_exists(self, kind: str, name: str) -> bool:
        from scripts.svq_export import _sql, _q
        q = (f"SELECT 1 FROM information_schema.schemata WHERE schema_name={_q(name)}"
             if kind == "db" else f"SELECT 1 FROM mysql.user WHERE User={_q(name)}")
        try:
            return bool(_sql(q))
        except Exception:
            return False

    # usuario
    def create_linux_user(self, username: str, email: str, password: str):
        from scripts.user_manager import UserManager
        UserManager().create_user(username, email, password)

    def set_shadow_hash(self, username: str, hashed: str):
        subprocess.run(["usermod", "-p", hashed, username], check=True, capture_output=True)

    def set_shell(self, username: str, shell: str):
        subprocess.run(["usermod", "-s", shell, username], check=True, capture_output=True)

    def set_quota(self, username: str, mb: int):
        from scripts.quota_manager import QuotaManager
        QuotaManager().set_quota(username, mb)

    # web
    def create_domain_structure(self, username: str, domain: str, php: str):
        from scripts.domain_manager import DomainManager
        DomainManager().create_domain(username, domain, php)

    def write_pool(self, domain, owner: str):
        import json as _j
        from scripts import php_ini_manager as phpini
        from api.routes.domains import _fpm_tuning_of
        try:
            overrides = _j.loads(domain.php_ini_overrides) if domain.php_ini_overrides else {}
        except (ValueError, TypeError):
            overrides = {}
        ok, msg = phpini.write_pool(domain.domain_name, domain.php_version, owner, overrides,
                                    relax_hardening=domain.php_hardening_relaxed or False,
                                    fpm_tuning=_fpm_tuning_of(domain))
        if not ok:
            raise RuntimeError(msg)

    def install_cert(self, name: str, fullchain: str, privkey: str):
        from scripts import custom_ssl
        custom_ssl.install(name, {"fullchain": fullchain, "key": privkey})

    def regenerate_vhost(self, domain, db):
        from api.routes.domains import _regenerate_from_domain
        _regenerate_from_domain(domain, db)

    # correo
    def create_mail_domain(self, domain: str, username: str):
        from scripts.mail_manager import MailManager
        MailManager().create_mail_domain(domain, username)

    def create_mailbox(self, username, domain, user, password_hash, quota_mb):
        from scripts.mail_manager import MailManager
        mm = MailManager()
        mm.create_mailbox(username, domain, user, secrets.token_urlsafe(24), quota_mb=quota_mb)
        mm._dovecot_set(f"{user}@{domain}", password_hash, username, domain, user, quota_mb)
        mm._reload_dovecot()

    def set_forward(self, domain, user, dests: List[str], keep_copy: bool):
        from scripts.mail_manager import MailManager
        MailManager().set_forward(domain, user, dests, keep_copy=keep_copy)

    def set_autoreply(self, username, domain, mb):
        from scripts.mail_manager import MailManager
        MailManager().set_autoreply(
            username, domain, mb.username, mb.autoreply_subject or "", mb.autoreply_body or "",
            is_html=bool(mb.autoreply_is_html), body_text=mb.autoreply_body_text,
            days=mb.autoreply_days or 1,
            start_date=mb.autoreply_start_date.isoformat() if mb.autoreply_start_date else None,
            end_date=mb.autoreply_end_date.isoformat() if mb.autoreply_end_date else None)

    def mail_alias(self, domain, source, dest):
        from scripts.mail_manager import MailManager
        mm = MailManager()
        if source == "@":
            mm.set_catch_all(domain, dest)
        else:
            mm.create_alias(domain, source, dest)

    def set_mail_routing(self, domain, mode):
        from scripts.mail_manager import MailManager
        MailManager().set_mail_routing(domain, mode)

    def install_dkim(self, domain, selector, key_pem):
        from scripts.dkim_manager import DkimManager
        dm = DkimManager()
        path = dm._key_path(domain, selector)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key_pem)
        dm._chown_rspamd(path)
        dm._update_selector_map(domain, selector)

    def enable_webmail(self, domain):
        from scripts.webmail_manager import WebmailManager
        WebmailManager().enable(domain)

    def rebuild_mail(self, db):
        from api.routes.mail import _rebuild_rspamd, _rebuild_mail_tls, _apply_domain_sender_ip
        from api.models.models_mail import MailDomain
        _rebuild_rspamd(db)
        _rebuild_mail_tls(db)
        for md in db.query(MailDomain).all():
            _apply_domain_sender_ip(md, db)
        try:
            from scripts.dkim_manager import DkimManager
            DkimManager()._reload_rspamd()
        except Exception:
            pass

    # crons / sftp / mysql remoto
    def add_cron(self, username, cj):
        from scripts.cron_manager import CronManager
        CronManager().add_cron(username, cj.id, cj.minute, cj.hour, cj.day, cj.month,
                               cj.weekday, cj.command, comment=cj.comment or "")

    def create_sftp(self, owner, row) -> Dict:
        from scripts import sftp_account_manager as S
        target = row["target_path"]
        os.makedirs(target, exist_ok=True)
        subprocess.run(["chown", f"{owner}:{owner}", target], capture_output=True)
        home = f"/home/{owner}/"
        sub = target[len(home):] if target.startswith(home) else target
        ok, msg, info = S.create_account(owner, row["label"], sub, password=secrets.token_urlsafe(18))
        if not ok:
            raise RuntimeError(msg)
        return info

    def mysql_remote_allow(self, ip: str):
        from api.utils import nftables_helper as nft
        nft.ensure_mysql_remote_setup()
        nft.mysql_remote_add_ip(ip)
        nft.persist_mysql_remote()


# ─────────────────────────────────────────────────────────────────────────────
# Traer el export del origen por SSH (solo lectura en el origen)
# ─────────────────────────────────────────────────────────────────────────────
MIN_SOURCE_VERSION = (0, 279, 0)


def _ver(s: str):
    try:
        return tuple(int(x) for x in (s or "").strip().split(".")[:3])
    except ValueError:
        return (0, 0, 0)


def fetch_export(cfg: Dict, username: str, timeout: int = 900) -> Dict:
    """Ejecuta `export_account` en el SVQPanel de origen por SSH y devuelve el
    JSON. cfg = {host, port?, user?, password?|key?}. El JSON lleva secretos:
    vive solo en memoria (nunca se escribe a disco)."""
    import re
    import shlex
    from api.routes.migrations import _SshSession
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username or ""):
        raise SvqImportError(f"Nombre de usuario no válido: {username!r}")
    s = _SshSession({**cfg, "hestia_user": username})
    try:
        cmd, env = s.ssh("cat /opt/svqpanel/VERSION 2>/dev/null || echo NOSVQ")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        ver = (r.stdout or "").strip()
        if r.returncode != 0 or not ver or ver == "NOSVQ":
            raise SvqImportError("El servidor de origen no responde por SSH o no tiene SVQPanel "
                                 f"en /opt/svqpanel: {(r.stderr or '').strip()[-200:]}")
        if _ver(ver) < MIN_SOURCE_VERSION:
            raise SvqImportError(f"El origen tiene SVQPanel {ver}; hace falta "
                                 f"{'.'.join(map(str, MIN_SOURCE_VERSION))} o superior "
                                 "(Sistema → Actualizaciones en el origen).")
        cmd, env = s.ssh("cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli "
                         f"export_account {shlex.quote(username)}")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            msg = next((l for l in reversed(err) if l.startswith("ERROR:")), err[-1] if err else "")
            raise SvqImportError(f"El origen no pudo exportar «{username}»: {msg[:300]}")
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise SvqImportError("Respuesta no válida del origen (no es JSON).")
    except subprocess.TimeoutExpired:
        raise SvqImportError("El origen tardó demasiado en exportar la cuenta.")
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────────────────────
# Análisis (no toca nada)
# ─────────────────────────────────────────────────────────────────────────────
def _rows(data, t) -> List[Dict]:
    return (data.get("tables") or {}).get(t) or []


def plan_import(data: Dict, db, ops: Ops = None) -> Dict:
    """Conflictos (bloquean), avisos y resumen. Es el «Analizar» de la UI."""
    from scripts.svq_export import summary
    from api.models.models_user import User
    from api.models.models_domain import Domain
    from api.models.models_domain_alias import DomainAlias
    from api.models.models_mail import MailDomain
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone
    ops = ops or Ops()
    conflicts, warnings = [], list(data.get("warnings") or [])

    if data.get("format") != FORMAT:
        raise SvqImportError("No es un export de cuenta de SVQPanel.")
    if int(data.get("format_version") or 0) > FORMAT_VERSION:
        raise SvqImportError("El export es de un SVQPanel más nuevo que este: actualiza el destino.")

    username = data.get("username") or ""
    if db.query(User).filter(User.username == username).first():
        conflicts.append(f"Ya existe el usuario «{username}» en este panel.")
    elif ops.linux_user_exists(username):
        conflicts.append(f"Ya existe el usuario de sistema «{username}» en este servidor.")

    def _taken(model, col, names, label):
        for n in names:
            if db.query(model).filter(getattr(model, col) == n).first():
                conflicts.append(f"{label} «{n}» ya existe en este panel.")

    _taken(Domain, "domain_name", [d["domain_name"] for d in _rows(data, "domains")], "El dominio")
    _taken(DomainAlias, "alias_name", [a["alias_name"] for a in _rows(data, "domain_aliases")], "El alias")
    _taken(MailDomain, "domain_name", [m["domain_name"] for m in _rows(data, "mail_domains")],
           "El dominio de correo")
    _taken(DnsZone, "domain_name", [z["domain_name"] for z in _rows(data, "dns_zones")], "La zona DNS")
    _taken(ClientDatabase, "db_name", [c["db_name"] for c in _rows(data, "client_databases")], "La BD")
    _taken(ClientDatabase, "db_user", [c["db_user"] for c in _rows(data, "client_databases")],
           "El usuario de BD")
    for c in _rows(data, "client_databases"):
        if ops.mariadb_exists("db", c["db_name"]):
            conflicts.append(f"La BD «{c['db_name']}» ya existe en MariaDB de este servidor.")
    for u in {u["user"] for u in (data.get("mariadb") or {}).get("users", [])}:
        if ops.mariadb_exists("user", u):
            conflicts.append(f"El usuario «{u}» ya existe en MariaDB de este servidor.")
    for s in _rows(data, "sftp_accounts"):
        if ops.linux_user_exists(s["username"]):
            conflicts.append(f"Ya existe el usuario de sistema «{s['username']}» (subcuenta SFTP).")

    # PHP que falta → se usará otra (aviso, no bloquea)
    php_changes = {}
    installed = ops.installed_php()
    for d in _rows(data, "domains"):
        want = d.get("php_version")
        if want and want not in installed and not d.get("mail_dns_only"):
            php_changes[d["domain_name"]] = (want, ops.resolve_php(want))
    for dom, (a, b) in php_changes.items():
        warnings.append(f"{dom}: PHP {a} no está instalado aquí → se usará {b} "
                        "(o instálalo antes de migrar).")

    # Cosas que no se pueden trasladar tal cual
    for d in _rows(data, "domains"):
        if d.get("ipv6"):
            warnings.append(f"{d['domain_name']}: tenía la IPv6 dedicada {d['ipv6']}; "
                            "aquí queda sin IPv6 propia (asígnala tras migrar).")
    for m in _rows(data, "mail_domains"):
        if m.get("relay_enabled"):
            warnings.append(f"{m['domain_name']}: usaba un SMTP relay propio; su contraseña no "
                            "viaja, así que llega DESACTIVADO (vuelve a configurarlo).")
    for z in _rows(data, "dns_zones"):
        if z.get("dnssec_enabled"):
            warnings.append(f"{z['domain_name']}: tenía DNSSEC; llega sin él. Quita el DS del "
                            "registrador ANTES del corte o el dominio dejará de resolver.")
    if _rows(data, "git_deployments"):
        warnings.append("Hay despliegues Git: la URL del webhook cambia con el servidor; "
                        "actualízala en GitHub/GitLab tras migrar.")

    # Espacio
    need = (data.get("sizes") or {}).get("home_bytes") or 0
    need += sum(d.get("bytes", 0) for d in (data.get("mariadb") or {}).get("databases", []))
    free = ops.free_bytes("/home")
    if need and free is not None and free < need * 1.1:
        warnings.append(f"Espacio: la cuenta ocupa ~{need // 2**30} GB y aquí quedan "
                        f"{free // 2**30} GB libres en /home.")

    return {"conflicts": conflicts, "warnings": warnings, "summary": summary(data),
            "php_changes": {k: list(v) for k, v in php_changes.items()},
            "importable": not conflicts}


# ─────────────────────────────────────────────────────────────────────────────
# Importación
# ─────────────────────────────────────────────────────────────────────────────
def _alias_dests(text: str) -> List[str]:
    return [d.strip() for d in (text or "").split(",") if d.strip()]


def _rewrite_records(records: List[Dict], src: Dict, dst: Dict) -> List[Dict]:
    """Registros exportados → formato de build_dns_proposal (el de Hestia),
    con los AAAA de la IPv6 del origen pasados a la del destino (o quitados)."""
    out = []
    for r in records:
        rtype = (r.get("record_type") or "").upper()
        val = r.get("content") or ""
        if rtype == "AAAA" and src.get("ipv6") and val.strip() == src["ipv6"]:
            if not dst.get("ipv6"):
                continue
            val = dst["ipv6"]
        out.append({"RECORD": r.get("name") or "@", "TYPE": rtype, "VALUE": val,
                    "TTL": str(r.get("ttl") or ""), "PRIORITY": str(r.get("priority") or "")})
    return out


def apply_import(data: Dict, db, report=None, progress=None, ops: Ops = None) -> Dict:
    """Recrea la cuenta. Devuelve el informe (dict)."""
    from scripts.hestia_import import ImportReport, NullProgress, build_dns_proposal, \
        _adapt_cron_command, _DNS_DISCARD_TYPES
    from api.models.models_user import User
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain, Mailbox
    from api.models.models_dns import DnsZone, DnsRecord
    from api.models.models_cron import CronJob
    from api.models.models_plan import Plan

    ops = ops or Ops()
    report = report or ImportReport()
    progress = progress or NullProgress()
    plan = plan_import(data, db, ops)
    if plan["conflicts"]:
        raise SvqImportError("Hay conflictos: " + "; ".join(plan["conflicts"]))

    fernets = _dest_fernets()
    unknown: set = set()
    username = data["username"]
    src_ips = data.get("server_ips") or {}
    dst_ips = ops.server_ips(db)

    # ── 1. Usuario ────────────────────────────────────────────────────────────
    progress.set_phase(f"Creando el cliente {username}…")
    urow = _rows(data, "users")[0]
    ops.create_linux_user(username, urow.get("email") or f"{username}@local.invalid",
                          secrets.token_urlsafe(24))
    shadow = (data.get("shadow") or {}).get(username)
    if shadow:
        ops.set_shadow_hash(username, shadow)
    plan_id = None
    prow = data.get("plan")
    if prow:
        existing = db.query(Plan).filter(Plan.name == prow["name"]).first()
        plan_id = existing.id if existing else build_row(db, "plans", prow, fernets).id
    parent_id = resolve_ref(db, urow.get("parent_id"))
    if urow.get("parent_id") and not parent_id:
        report.fail("user", username, f"su revendedor «{urow['parent_id'].get('key')}» no existe "
                                      "aquí: queda sin revendedor")
    user = build_row(db, "users", urow, fernets, {"plan_id": plan_id, "parent_id": parent_id},
                     unknown)
    db.commit()
    if user.shell_path and "nologin" not in user.shell_path:
        try:
            ops.set_shell(username, user.shell_path)
        except Exception as e:
            report.fail("user-shell", username, e)
    try:
        if user.disk_quota_mb:
            ops.set_quota(username, user.disk_quota_mb)
    except Exception as e:
        report.fail("user-quota", username, e)
    report.ok("user", username, "contraseñas del panel y de sistema conservadas"
              if shadow else "contraseña del panel conservada")

    # Plantillas web referenciadas (si el destino no las tiene, se crean)
    for trow in data.get("web_templates") or []:
        from api.models.models_template import WebTemplate
        if not db.query(WebTemplate).filter(WebTemplate.slug == trow.get("slug")).first():
            build_row(db, "web_templates", trow, fernets)
    db.commit()

    # ── 2. Dominios ───────────────────────────────────────────────────────────
    domains = sorted(_rows(data, "domains"),
                     key=lambda d: (bool(d.get("staging_of_domain_id")), bool(d.get("is_subdomain"))))
    certs = {c["name"]: c for c in data.get("ssl") or []}
    for d in domains:
        name = d["domain_name"]
        progress.set_phase(f"Creando {name}…")
        try:
            php = d.get("php_version") or "8.2"
            if not d.get("mail_dns_only"):
                php = ops.resolve_php(php)
                ops.create_domain_structure(username, name, php)
            dom = build_row(db, "domains", d, fernets, {
                "user_id": user.id, "php_version": php,
                "ipv4": dst_ips.get("ipv4") if d.get("ipv4") else None,
                "ipv6": None,
            }, unknown)
            db.commit()
            note = f"PHP {php}" + (f" (era {d.get('php_version')})" if php != d.get("php_version") else "")
            if not d.get("mail_dns_only"):
                ops.write_pool(dom, username)
            report.ok("web", name, note)
        except Exception as e:
            db.rollback()
            report.fail("web", name, e)

    for a in _rows(data, "domain_aliases"):
        try:
            build_row(db, "domain_aliases", a, fernets, unknown=unknown)
            db.commit()
        except Exception as e:
            db.rollback()
            report.fail("web-alias", a.get("alias_name"), e)
    for g in _rows(data, "git_deployments"):
        try:
            build_row(db, "git_deployments", g, fernets, unknown=unknown)
            db.commit()
        except Exception as e:
            db.rollback()
            report.fail("git", str(g.get("domain_id", {}).get("key")), e)

    # Certificados en uso (como «propios»: sin corte mientras cambia el DNS; tras
    # el corte se pasan a Let's Encrypt) y vhost con TODO el estado de la BD.
    for name, c in certs.items():
        try:
            ops.install_cert(name, c["fullchain"], c["privkey"])
        except Exception as e:
            report.fail("ssl", name, e)
    for d in domains:
        if d.get("mail_dns_only"):
            continue
        dom = db.query(Domain).filter(Domain.domain_name == d["domain_name"]).first()
        if not dom:
            continue
        try:
            ops.regenerate_vhost(dom, db)
        except Exception as e:
            report.fail("web-vhost", dom.domain_name, e)

    # ── 3. Bases de datos ─────────────────────────────────────────────────────
    from scripts.hestia_import import _ident
    mdb = data.get("mariadb") or {}
    for c in _rows(data, "client_databases"):
        name = c["db_name"]
        try:
            safe = _ident(name)
            charset = _ident(c.get("db_charset") or "utf8mb4")
            coll = _ident(c.get("db_collation") or "utf8mb4_unicode_ci")
            ops.mariadb(f"CREATE DATABASE IF NOT EXISTS `{safe}` CHARACTER SET {charset} COLLATE {coll};")
            build_row(db, "client_databases", c, fernets, {"user_id": user.id}, unknown)
            db.commit()
            report.ok("db", name, "creada (los datos llegan en la copia)")
        except Exception as e:
            db.rollback()
            report.fail("db", name, e)
    for u in mdb.get("users", []):
        who = f"{u['user']}@{u['host']}"
        try:
            ident = f"'{_ident(u['user'], 80)}'@'{u['host'].replace(chr(39), '')}'"
            ops.mariadb(f"DROP USER IF EXISTS {ident};")
            ops.mariadb(u["create"].rstrip(";") + ";")
            for g in u.get("grants", []):
                if g.upper().startswith("GRANT USAGE ON *.*"):
                    continue            # ya lo da el CREATE USER
                ops.mariadb(g.rstrip(";") + ";")
            report.ok("db-user", who, "misma contraseña y permisos")
        except Exception as e:
            report.fail("db-user", who, e)
    if mdb.get("users"):
        try:
            ops.mariadb("FLUSH PRIVILEGES;")
        except Exception:
            pass
    for t in ("database_users", "db_remote_hosts"):
        for r in _rows(data, t):
            try:
                build_row(db, t, r, fernets, unknown=unknown)
                db.commit()
            except Exception as e:
                db.rollback()
                report.fail(t, str(r.get("username") or r.get("host")), e)
    for ip in sorted({r.get("host") for r in _rows(data, "db_remote_hosts") if r.get("host")}):
        try:
            ops.mysql_remote_allow(ip)
        except Exception as e:
            report.fail("mysql-remote", ip, e)

    # ── 4. Correo ─────────────────────────────────────────────────────────────
    dkim = {k["domain"]: k for k in data.get("dkim") or []}
    mail_enabled = os.getenv("MAIL_ENABLED", "false").lower() == "true"
    for m in _rows(data, "mail_domains"):
        name = m["domain_name"]
        if not mail_enabled:
            report.fail("mail", name, "el correo no está activo en este servidor")
            continue
        progress.set_phase(f"Creando el correo de {name}…")
        try:
            ops.create_mail_domain(name, username)
            md = build_row(db, "mail_domains", m, fernets, {
                "user_id": user.id, "relay_enabled": False}, unknown)
            db.commit()
            k = dkim.get(name)
            if k:
                ops.install_dkim(name, k["selector"], k["key"])
            ops.enable_webmail(name)
            if (m.get("mail_routing") or "local") != "local":
                ops.set_mail_routing(name, m["mail_routing"])
            if m.get("catch_all"):
                ops.mail_alias(name, "@", m["catch_all"])
            report.ok("mail", name, "DKIM conservado" if k else "sin DKIM en el origen")
        except Exception as e:
            db.rollback()
            report.fail("mail", name, e)
            continue
    for mb in _rows(data, "mailboxes"):
        dom_name = (mb.get("mail_domain_id") or {}).get("key")
        email = f"{mb.get('username')}@{dom_name}"
        md = db.query(MailDomain).filter(MailDomain.domain_name == dom_name).first()
        if not md:
            continue
        try:
            obj = build_row(db, "mailboxes", mb, fernets, unknown=unknown)
            ops.create_mailbox(username, dom_name, obj.username, obj.password_hash, obj.quota_mb or 0)
            db.commit()
            dests = _alias_dests(obj.forward_to)
            if dests:
                ops.set_forward(dom_name, obj.username, dests, bool(obj.forward_keep_copy))
            if obj.autoreply_enabled:
                ops.set_autoreply(username, dom_name, obj)
            report.ok("mailbox", email, "misma contraseña")
        except Exception as e:
            db.rollback()
            report.fail("mailbox", email, e)
    for al in _rows(data, "mail_aliases"):
        dom_name = (al.get("mail_domain_id") or {}).get("key")
        try:
            obj = build_row(db, "mail_aliases", al, fernets, unknown=unknown)
            if obj.is_active is not False:
                ops.mail_alias(dom_name, obj.source, obj.destination)
            db.commit()
        except Exception as e:
            db.rollback()
            report.fail("mail-alias", f"{al.get('source')}@{dom_name}", e)
    if mail_enabled and _rows(data, "mail_domains"):
        try:
            ops.rebuild_mail(db)
        except Exception as e:
            report.fail("mail-config", username, e)

    # ── 5. DNS (inactivo hasta el corte) ──────────────────────────────────────
    from scripts.dns_manager import get_panel_nameservers
    try:
        ns1, ns2 = get_panel_nameservers(db)
    except Exception:
        ns1 = ns2 = None
    records_by_zone: Dict[str, List[Dict]] = {}
    for r in _rows(data, "dns_records"):
        records_by_zone.setdefault((r.get("zone_id") or {}).get("key"), []).append(r)
    for z in _rows(data, "dns_zones"):
        name = z["domain_name"]
        try:
            zoneinfo = {"domain": name, "ip": src_ips.get("ipv4") or z.get("ip_address"),
                        "ttl": z.get("ttl") or 14400,
                        "_records": _rewrite_records(records_by_zone.get(name, []), src_ips, dst_ips)}
            proposal = build_dns_proposal(zoneinfo, dst_ips.get("ipv4"), dst_ips.get("ipv6"),
                                          zoneinfo["ip"], panel_ns=[n for n in (ns1, ns2) if n])
            zone = build_row(db, "dns_zones", z, fernets, {
                "is_active": False, "ip_address": dst_ips.get("ipv4") or z.get("ip_address"),
                "soa_ns": ns1 or z.get("soa_ns"), "dnssec_enabled": False}, unknown)
            n = 0
            for rec in proposal:
                rtype = (rec.get("type") or "").upper()
                if not rec.get("include", True) or not rtype:
                    continue
                if rtype in _DNS_DISCARD_TYPES and rec.get("action") != "add":
                    continue
                content = (rec.get("new_content") if rec.get("action") == "rewrite" else None) \
                    or rec.get("content") or ""
                if not content:
                    continue
                db.add(DnsRecord(zone_id=zone.id, record_type=rtype, name=rec.get("name") or "@",
                                 content=content, ttl=int(rec.get("ttl") or z.get("ttl") or 14400),
                                 priority=int(rec.get("priority") or 0)))
                n += 1
            db.commit()
            report.ok("dns", name, f"{n} registro(s), INACTIVA hasta el corte (no publicada)")
        except Exception as e:
            db.rollback()
            report.fail("dns", name, e)

    # ── 6. Crons ──────────────────────────────────────────────────────────────
    installed = ops.installed_php()
    domain_php = {d.domain_name: d.php_version for d in
                  db.query(Domain).filter(Domain.user_id == user.id).all()}
    for c in _rows(data, "cron_jobs"):
        try:
            cmd = _adapt_cron_command(c.get("command") or "", username, installed, domain_php)
            cj = build_row(db, "cron_jobs", c, fernets, {"user_id": user.id, "command": cmd}, unknown)
            if cj.is_active:
                ops.add_cron(username, cj)
            db.commit()
            report.ok("cron", cmd[:50], "activo" if cj.is_active else "pausado")
        except Exception as e:
            db.rollback()
            report.fail("cron", (c.get("command") or "")[:40], e)

    # ── 7. Subcuentas SFTP ────────────────────────────────────────────────────
    for s in _rows(data, "sftp_accounts"):
        try:
            info = ops.create_sftp(username, s)
            sftp_user = info.get("username") or s["username"]
            build_row(db, "sftp_accounts", s, fernets, {
                "owner_id": user.id, "username": sftp_user,
                "jail_path": info.get("jail_path", s.get("jail_path")),
                "mount_name": info.get("mount_name", s.get("mount_name"))}, unknown)
            db.commit()
            h = (data.get("shadow") or {}).get(s["username"])
            if h:
                ops.set_shadow_hash(sftp_user, h)
            report.ok("sftp", sftp_user, "misma contraseña" if h else
                      "contraseña NUEVA: cámbiala desde el panel")
        except Exception as e:
            db.rollback()
            report.fail("sftp", s.get("username"), e)

    out = report.to_dict()
    out["warnings"] = plan["warnings"]
    if unknown:
        out["warnings"].append("Campos del origen que este panel no tiene (origen más nuevo; "
                               "actualiza el destino si te importan): " + ", ".join(sorted(unknown)))
    out["next_steps"] = [
        "Copiar los datos (web, correo y BDs): fase 3.",
        "Revisar la web en el servidor nuevo (hosts local) antes del corte.",
        "Corte: activar las zonas DNS / cambiar los NS y emitir Let's Encrypt.",
    ]
    return out
