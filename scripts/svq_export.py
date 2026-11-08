"""
Migrador SVQPanel → SVQPanel · FASE 1: export de una cuenta en el ORIGEN.

`python -m api.cli export_account <usuario>` (como root, en el servidor de
origen) escribe en stdout un JSON con todo lo que el panel sabe del cliente. El
destino lo ejecuta por SSH y recrea la cuenta (fase 2); los datos pesados (web,
correo = /home/U, BDs) viajan aparte por rsync / mysqldump en streaming.

Decisiones:
  - GENÉRICO por tablas: cada fila se vuelca con TODAS sus columnas (salvo la
    clave primaria). Un campo nuevo en un modelo viaja sin tocar este fichero.
  - Sin ids: los ids internos cambian de servidor a servidor. Cada clave ajena
    se sustituye por la clave natural de la fila a la que apunta
    ({"$ref": "domains", "key": "ejemplo.es"}); el destino la traduce a su id.
  - Secretos: los valores cifrados con Fernet (PANEL_ENCRYPTION_KEY, distinta en
    cada servidor) se DESCIFRAN aquí ({"$enc": "texto"}) para que el destino los
    vuelva a cifrar con la suya. Por eso la salida es secreta: solo stdout por el
    túnel SSH, nunca a un fichero.
  - Fechas: {"$dt": "ISO"}; binarios: {"$b64": "..."}.
  - Fuera de la BD del panel: usuarios MariaDB (SHOW CREATE USER + GRANTS, con
    su hash), claves DKIM y certificados SSL, y tamaños para el análisis previo.
"""

import base64
import datetime as _dt
import decimal
import logging
import os
import socket
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FORMAT = "svqpanel-account"
FORMAT_VERSION = 1

# Clave natural de cada tabla referenciable (lo que sustituye al id).
NATURAL_KEYS = {
    "users": "username",
    "domains": "domain_name",
    "mail_domains": "domain_name",
    "client_databases": "db_name",
    "dns_zones": "domain_name",
    "plans": "name",
    "web_templates": "slug",
}

# Qué se exporta y cómo se llega desde el usuario. (tabla, columna, origen):
# las filas de `tabla` cuya `columna` está en los ids de `origen`.
EXPORT_PLAN = [
    ("users",            "id",             "users"),
    ("domains",          "user_id",        "users"),
    ("domain_aliases",   "domain_id",      "domains"),
    ("git_deployments",  "domain_id",      "domains"),
    ("mail_domains",     "user_id",        "users"),
    ("mailboxes",        "mail_domain_id", "mail_domains"),
    ("mail_aliases",     "mail_domain_id", "mail_domains"),
    ("client_databases", "user_id",        "users"),
    ("database_users",   "database_id",    "client_databases"),
    ("db_remote_hosts",  "database_id",    "client_databases"),
    ("cron_jobs",        "user_id",        "users"),
    ("sftp_accounts",    "owner_id",       "users"),
    # dns_zones no tiene FK al usuario: se eligen por nombre (ver _zone_ids)
    ("dns_records",      "zone_id",        "dns_zones"),
]

# Nunca viajan: históricos, métricas, sesiones, auditoría, backups (el repo
# restic vive en el destino de backup del origen), tokens.
NOT_EXPORTED = ("api_tokens", "notifications", "security_audit_log", "cron_runs",
                "backup_jobs", "backup_records", "domain_resource_samples",
                "malware_findings", "malware_scan_runs", "wp_update_runs",
                "webmail_tokens", "migration_jobs")


class ExportError(RuntimeError):
    pass


# ── valores ──────────────────────────────────────────────────────────────────
def _fernet():
    """Cifradores del panel, por nombre. Hay DOS esquemas:
      - "panel":  PANEL_ENCRYPTION_KEY (BDs, 2FA, backups, relay, orígenes…)
      - "secret": derivado de SECRET_KEY (autologin del webmail,
                  Mailbox.encrypted_password; ver api/routes/mail.py)
    El valor exportado lleva el nombre para que el destino lo recifre igual."""
    out = []
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return out
    key = os.getenv("PANEL_ENCRYPTION_KEY", "")
    if key:
        try:
            out.append(("panel", Fernet(key.encode())))
        except Exception:
            pass
    try:
        import base64 as _b64, hashlib
        from api.utils.secret import get_secret_key
        secret = get_secret_key()
        if secret:
            out.append(("secret", Fernet(_b64.urlsafe_b64encode(
                hashlib.sha256(secret.encode()).digest()))))
    except Exception:
        pass
    return out


def _looks_fernet(v: str) -> bool:
    return isinstance(v, str) and v.startswith("gAAAAA") and len(v) >= 100


def encode_value(v, fernet=None, warnings: Optional[list] = None, where: str = ""):
    """Valor de una columna → JSON (fechas, binarios y secretos marcados)."""
    if isinstance(v, (_dt.datetime, _dt.date)):
        return {"$dt": v.isoformat()}
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode()}
    if _looks_fernet(v):
        for name, f in (fernet or []):
            try:
                return {"$enc": f.decrypt(v.encode()).decode(), "key": name}
            except Exception:
                continue
        if warnings is not None:
            warnings.append(f"{where}: valor cifrado que no se pudo descifrar con "
                            "ninguna clave del panel; se omite")
        return None
    return v


# ── BD del panel ─────────────────────────────────────────────────────────────
class _Refs:
    """id → clave natural, con caché, para las FK."""

    def __init__(self, db, tables):
        self.db, self.tables, self.cache = db, tables, {}

    def key(self, table: str, ident):
        if ident is None:
            return None
        ck = (table, ident)
        if ck not in self.cache:
            col = NATURAL_KEYS.get(table)
            t = self.tables.get(table)
            val = None
            if col and t is not None:
                from sqlalchemy import select
                val = self.db.execute(select(t.c[col]).where(t.c.id == ident)).scalar()
            self.cache[ck] = val
        return self.cache[ck]


def _row_to_json(row, table, refs: _Refs, fernet, warnings) -> Dict:
    out = {}
    for col in table.columns:
        if col.primary_key:
            continue
        v = row[col.name]
        if col.foreign_keys:
            target = list(col.foreign_keys)[0].column.table.name
            k = refs.key(target, v)
            out[col.name] = {"$ref": target, "key": k} if k is not None else None
            continue
        out[col.name] = encode_value(v, fernet, warnings, f"{table.name}.{col.name}")
    return out


def _zone_ids(db, tables, names) -> List[int]:
    from sqlalchemy import select
    t = tables["dns_zones"]
    if not names:
        return []
    return [r[0] for r in db.execute(select(t.c.id).where(t.c.domain_name.in_(sorted(names))))]


def export_panel_rows(db, username: str, warnings: list) -> Dict:
    """Filas de la BD del panel del cliente, sin ids y con FKs por nombre."""
    from sqlalchemy import select
    from api.models.database import Base, load_all_models
    load_all_models()
    tables = Base.metadata.tables
    users = tables["users"]
    user = db.execute(select(users).where(users.c.username == username)).mappings().first()
    if not user:
        raise ExportError(f"No existe el usuario «{username}» en este panel.")
    if user["is_admin"] or user["role"] == "admin":
        raise ExportError("No se exporta una cuenta de administrador.")
    if user["role"] == "reseller":
        n = db.execute(select(users.c.id).where(users.c.parent_id == user["id"])).first()
        if n:
            warnings.append("Es un revendedor con clientes propios: solo se exporta "
                            "su cuenta, no la de sus clientes (expórtalos uno a uno).")

    fernet = _fernet()
    refs = _Refs(db, tables)
    ids = {"users": [user["id"]]}
    out: Dict[str, List[Dict]] = {}

    for tname, col, origin in EXPORT_PLAN:
        if tname == "dns_records":
            names = {r["domain_name"] for r in out.get("domains", [])}
            names |= {r["domain_name"] for r in out.get("mail_domains", [])}
            # Subdominios: su DNS vive en la zona padre (que es del propio cliente)
            ids["dns_zones"] = _zone_ids(db, tables, names)
            zt = tables["dns_zones"]
            out["dns_zones"] = [
                _row_to_json(r, zt, refs, fernet, warnings)
                for r in db.execute(select(zt).where(zt.c.id.in_(ids["dns_zones"]))
                                    .order_by(zt.c.id)).mappings()] if ids["dns_zones"] else []
        t = tables.get(tname)
        src_ids = ids.get(origin) or []
        if t is None or not src_ids:
            out.setdefault(tname, [])
            continue
        rows = list(db.execute(select(t).where(t.c[col].in_(src_ids)).order_by(t.c.id)).mappings())
        ids[tname] = [r["id"] for r in rows]
        out[tname] = [_row_to_json(r, t, refs, fernet, warnings) for r in rows]

    # Plan y plantilla web: se exportan enteros por si el destino no los tiene.
    extra = {}
    if user["plan_id"]:
        pt = tables["plans"]
        p = db.execute(select(pt).where(pt.c.id == user["plan_id"])).mappings().first()
        if p:
            extra["plan"] = _row_to_json(p, pt, refs, fernet, warnings)
    tpl_ids = {r for r in db.execute(select(tables["domains"].c.applied_template_id)
                                     .where(tables["domains"].c.user_id == user["id"])).scalars() if r}
    if tpl_ids:
        tt = tables["web_templates"]
        extra["web_templates"] = [_row_to_json(r, tt, refs, fernet, warnings) for r in
                                  db.execute(select(tt).where(tt.c.id.in_(sorted(tpl_ids)))).mappings()]
    # Avisos repetidos (uno por fila) → uno solo con el recuento
    counts: Dict[str, int] = {}
    for w in warnings:
        counts[w] = counts.get(w, 0) + 1
    warnings[:] = [w if n == 1 else f"{w} (×{n})" for w, n in counts.items()]
    return {"tables": out, **extra}


# ── fuera de la BD del panel ─────────────────────────────────────────────────
def _run(cmd: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _sql(query: str) -> List[List[str]]:
    """Consulta MariaDB como root (socket unix). Filas como listas de columnas."""
    from api.routes.databases import _mariadb_binary
    r = _run([_mariadb_binary(), "-N", "-B", "-r", "-e", query])
    if r.returncode != 0:
        raise ExportError(f"MariaDB: {(r.stderr or '').strip()[:300]}")
    return [line.split("\t") for line in r.stdout.splitlines() if line]


def _q(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def export_mariadb(tables_out: Dict, warnings: list) -> Dict:
    """Usuarios MariaDB del cliente (con su hash) + permisos + tamaño de cada BD."""
    dbs = [r["db_name"] for r in tables_out.get("client_databases", [])]
    users = {r.get("db_user") for r in tables_out.get("client_databases", []) if r.get("db_user")}
    users |= {r.get("username") for r in tables_out.get("database_users", []) if r.get("username")}
    out = {"users": [], "databases": []}
    if not dbs and not users:
        return out
    try:
        for u in sorted(users):
            hosts = [r[0] for r in _sql(f"SELECT Host FROM mysql.user WHERE User={_q(u)}")]
            for h in hosts:
                ident = f"{_q(u)}@{_q(h)}"
                create = (_sql(f"SHOW CREATE USER {ident}") or [[""]])[0][0]
                grants = [r[0] for r in _sql(f"SHOW GRANTS FOR {ident}")]
                out["users"].append({"user": u, "host": h, "create": create, "grants": grants})
        for d in dbs:
            row = _sql("SELECT COALESCE(SUM(data_length+index_length),0), COUNT(*) "
                       f"FROM information_schema.tables WHERE table_schema={_q(d)}")
            size, ntables = (row[0] if row else ["0", "0"])
            out["databases"].append({"name": d, "bytes": int(float(size or 0)),
                                     "tables": int(ntables or 0)})
    except ExportError as e:
        warnings.append(f"No se pudieron leer los usuarios de MariaDB: {e}")
    except FileNotFoundError:
        warnings.append("Este servidor no tiene cliente de MariaDB: las BDs no se exportan.")
    except Exception as e:      # el export de la BD del panel sigue valiendo
        warnings.append(f"MariaDB: {e}")
    return out


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def export_dkim(tables_out: Dict, warnings: list) -> List[Dict]:
    """Clave privada DKIM de cada dominio de correo: así el TXT publicado sigue
    valiendo y no hay que tocar el DNS por el DKIM."""
    from scripts.dkim_manager import DkimManager
    try:
        selectors = DkimManager()._read_selector_map()     # exige root
    except Exception:
        selectors = {}
    out = []
    for md in tables_out.get("mail_domains", []):
        dom = md["domain_name"]
        sel = selectors.get(dom) or md.get("dkim_selector") or "mail"
        key = _read(os.path.join(DkimManager.DKIM_DIR, f"{dom}.{sel}.key"))
        if key:
            out.append({"domain": dom, "selector": sel, "key": key})
        elif md.get("dkim_enabled", True):
            warnings.append(f"{dom}: sin clave DKIM en el origen; el destino generará una nueva.")
    return out


def export_ssl(tables_out: Dict) -> List[Dict]:
    """Certificados en uso (propios y Let's Encrypt) de cada dominio y alias,
    para que no haya corte mientras el DNS cambia. Los heredados (wildcard del
    principal) no se repiten: viajan con el principal."""
    from scripts import ssl_paths
    names = [r["domain_name"] for r in tables_out.get("domains", [])]
    names += [r["alias_name"] for r in tables_out.get("domain_aliases", [])]
    for md in tables_out.get("mail_domains", []):
        names += [f"mail.{md['domain_name']}", f"webmail.{md['domain_name']}"]
    out, seen = [], set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        src = ssl_paths.source(n)
        if src not in ("custom", "letsencrypt"):
            continue
        fc, pk = ssl_paths.cert_paths(n)
        fullchain, privkey = _read(os.path.realpath(fc)), _read(os.path.realpath(pk))
        if not fullchain or not privkey:
            continue
        item = {"name": n, "source": src, "fullchain": fullchain, "privkey": privkey}
        if src == "letsencrypt":
            item["renewal_conf"] = _read(f"/etc/letsencrypt/renewal/{n}.conf")
        out.append(item)
    return out


def _du_bytes(path: str) -> Optional[int]:
    try:
        r = _run(["du", "-sb", "--", path], timeout=600)
        return int(r.stdout.split()[0]) if r.returncode == 0 and r.stdout else None
    except Exception:
        return None


def _server_ips() -> Dict:
    ips = {"ipv4": None, "ipv6": None}
    try:
        from api.models.database import SessionLocal
        from api.routes.dns import _get_server_ipv4
        from api.models.models_settings import Settings
        db = SessionLocal()
        try:
            ips["ipv4"] = _get_server_ipv4(db) or None
            s = db.query(Settings).filter(Settings.id == 1).first()
            ips["ipv6"] = getattr(s, "server_ipv6", None) if s else None
        finally:
            db.close()
    except Exception:
        pass
    return ips


# ── export completo ──────────────────────────────────────────────────────────
def export_account(db, username: str, with_sizes: bool = True) -> Dict:
    from config.config import PANEL_VERSION
    warnings: List[str] = []
    panel = export_panel_rows(db, username, warnings)
    tables_out = panel["tables"]
    home = f"/home/{username}"
    data = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "panel_version": PANEL_VERSION,
        "exported_at": _dt.datetime.utcnow().isoformat() + "Z",
        "hostname": socket.getfqdn(),
        "server_ips": _server_ips(),
        "username": username,
        "home": home,
        **panel,
        "mariadb": export_mariadb(tables_out, warnings),
        "dkim": export_dkim(tables_out, warnings),
        "ssl": export_ssl(tables_out),
        "sizes": {"home_bytes": _du_bytes(home) if with_sizes else None},
        "warnings": warnings,
    }
    return data


def summary(data: Dict) -> Dict:
    """Resumen legible (para el análisis previo y para --summary del CLI)."""
    t = data.get("tables", {})
    return {
        "username": data.get("username"),
        "panel_version": data.get("panel_version"),
        "domains": [d["domain_name"] for d in t.get("domains", [])],
        "mail_domains": len(t.get("mail_domains", [])),
        "mailboxes": len(t.get("mailboxes", [])),
        "databases": [d["name"] for d in data.get("mariadb", {}).get("databases", [])],
        "dns_zones": len(t.get("dns_zones", [])),
        "crons": len(t.get("cron_jobs", [])),
        "sftp_accounts": len(t.get("sftp_accounts", [])),
        "ssl_certs": len(data.get("ssl", [])),
        "dkim_keys": len(data.get("dkim", [])),
        "home_bytes": (data.get("sizes") or {}).get("home_bytes"),
        "warnings": data.get("warnings", []),
    }
