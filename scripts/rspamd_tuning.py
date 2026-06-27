"""
Ajuste fino del antispam (Rspamd) por el administrador.

Permite al admin, desde el panel y sin tocar ficheros:
  - Subir/bajar el PESO de símbolos concretos de Rspamd (p. ej. dar más castigo
    a PHISHING o a HELO falso).
  - Ajustar los UMBRALES de acción (marcar como spam / rechazar / greylist).

Filosofía (igual que mysql_tuner): el panel SOLO escribe drop-ins propios y
reversibles; no toca la config base de Rspamd.
  - Pesos     → /etc/rspamd/local.d/groups.conf      (symbols { SYM { weight } })
  - Umbrales  → /etc/rspamd/local.d/actions.conf     (add header / reject / greylist)
Borrando esos ficheros se vuelve a los valores por defecto.

Los valores elegidos por el admin se guardan en BD (Settings.rspamd_overrides,
JSON) para sobrevivir a reinstalaciones y poder regenerar los drop-ins en
install/update.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import logging

logger = logging.getLogger(__name__)

GROUPS_FILE  = "/etc/rspamd/local.d/groups.conf"   # overrides de peso de símbolos
ACTIONS_FILE = "/etc/rspamd/local.d/actions.conf"  # umbrales de acción

# Reglas de contenido del admin (globales, todo el servidor). Rspamd SOLO lee
# reglas de multimap desde local.d/multimap.conf (un .conf aparte se ignora), así
# que NO escribimos fichero propio: persistimos las reglas como JSON y el
# RspamdManager las inyecta en multimap.conf al regenerar (build_admin_rules_blocks).
RULES_JSON   = "/etc/rspamd/svqpanel_admin_rules.json"   # solo persistencia
RULES_MAPDIR = "/etc/rspamd/maps/svqpanel_admin"

# Tipos de regla soportados → (selector multimap, descripción).
RULE_TYPES = {
    "from":    "Remitente (dirección o @dominio)",
    "subject": "Asunto contiene",
    "word":    "Palabra/frase en el cuerpo",
}
# Acciones de una regla.
RULE_ACTIONS = {
    "reject":  "Rechazar",
    "spam":    "Marcar como spam (+peso)",
    "allow":   "Permitir (lista blanca)",
}
# Modo de coincidencia (para subject/word).
RULE_MATCHES = {
    "contains": "contiene",
    "exact":    "es exactamente",
}

# Umbrales por defecto de Rspamd (para mostrar en la UI y como base).
DEFAULT_ACTIONS = {
    "greylist": 4.0,
    "add header": 6.0,      # = "marcar como spam" (X-Spam: Yes)
    "reject": 15.0,
}
# Límites de cordura para los umbrales (evitar que el admin se dispare en el pie).
ACTION_BOUNDS = {
    "greylist":   (1.0, 30.0),
    "add header": (2.0, 40.0),
    "reject":     (5.0, 100.0),
}


def list_symbols() -> list[dict]:
    """Lista los símbolos de Rspamd con su peso ACTUAL y frecuencia, vía
    `rspamc counters`. Devuelve [{name, weight, frequency, hits}]. Best-effort."""
    out: list[dict] = []
    try:
        res = subprocess.run(["rspamc", "counters"], capture_output=True,
                             text=True, timeout=20)
        for line in res.stdout.splitlines():
            # | 369  | PHISHING            |   7.0   | 0.000 (0.012) |    3    |
            cols = [c.strip() for c in line.split("|")]
            if len(cols) < 6:
                continue
            name = cols[2]
            if not re.match(r"^[A-Z0-9_]+$", name):
                continue
            try:
                weight = float(cols[3])
            except ValueError:
                continue
            freq_m = re.search(r"\(([\d.]+)\)", cols[4])
            out.append({
                "name": name,
                "weight": weight,
                "frequency": float(freq_m.group(1)) if freq_m else 0.0,
                "hits": _safe_int(cols[5]),
            })
    except Exception as e:
        logger.warning(f"rspamd_tuning.list_symbols: {e}")
    out.sort(key=lambda s: s["name"])
    return out


def _safe_int(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


def get_actions() -> dict:
    """Umbrales actuales (lee actions.conf si existe; si no, defaults)."""
    vals = dict(DEFAULT_ACTIONS)
    if os.path.exists(ACTIONS_FILE):
        try:
            with open(ACTIONS_FILE) as f:
                txt = f.read()
            for key in vals:
                m = re.search(rf'"{re.escape(key)}"\s*=\s*([\-\d.]+)', txt)
                if m:
                    vals[key] = float(m.group(1))
        except Exception as e:
            logger.warning(f"rspamd_tuning.get_actions: {e}")
    return vals


def get_weight_overrides() -> dict:
    """Overrides de peso actuales (lee groups.conf propio)."""
    overrides: dict[str, float] = {}
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE) as f:
                txt = f.read()
            for m in re.finditer(r'"([A-Z0-9_]+)"\s*\{\s*weight\s*=\s*([\-\d.]+)', txt):
                overrides[m.group(1)] = float(m.group(2))
        except Exception as e:
            logger.warning(f"rspamd_tuning.get_weight_overrides: {e}")
    return overrides


def _write_atomic(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _build_groups(weight_overrides: dict) -> str:
    lines = ["# SVQPanel — overrides de peso de símbolos (admin). NO editar a mano.",
             "symbols {"]
    for name, w in sorted(weight_overrides.items()):
        if not re.match(r"^[A-Z0-9_]+$", name):
            continue
        lines.append(f'  "{name}" {{ weight = {float(w):.2f}; }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _build_actions(actions: dict) -> str:
    # En local.d/actions.conf el contenido va DIRECTO (Rspamd ya lo envuelve en
    # actions{}). NO añadir 'actions {' aquí o da "nested section actions".
    lines = ["# SVQPanel — umbrales de acción antispam (admin). NO editar a mano."]
    for key in ("greylist", "add header", "reject"):
        if key in actions:
            lines.append(f'"{key}" = {float(actions[key]):.2f};')
    return "\n".join(lines) + "\n"


def apply(weight_overrides: dict | None, actions: dict | None) -> dict:
    """Escribe los drop-ins y recarga Rspamd. Valida con configtest antes de
    aplicar; si falla, restaura y reporta el error (no deja Rspamd roto).

    weight_overrides: {SYMBOL: peso}. {} o None → elimina overrides de peso.
    actions: {greylist, add header, reject}. None → no toca umbrales.
    """
    # Guardar estado previo para rollback.
    prev_groups = _read(GROUPS_FILE)
    prev_actions = _read(ACTIONS_FILE)

    if weight_overrides is not None:
        if weight_overrides:
            _write_atomic(GROUPS_FILE, _build_groups(weight_overrides))
        elif os.path.exists(GROUPS_FILE):
            os.remove(GROUPS_FILE)

    if actions is not None:
        # Validar contra límites de cordura.
        for k, v in actions.items():
            lo, hi = ACTION_BOUNDS.get(k, (0.0, 100.0))
            if not (lo <= float(v) <= hi):
                return {"success": False,
                        "error": f"Umbral '{k}'={v} fuera de rango [{lo},{hi}]"}
        _write_atomic(ACTIONS_FILE, _build_actions(actions))

    # Validar configuración antes de recargar.
    ok, err = _configtest()
    if not ok:
        # Rollback.
        _restore(GROUPS_FILE, prev_groups)
        _restore(ACTIONS_FILE, prev_actions)
        return {"success": False, "error": f"Config inválida, revertido: {err}"}

    _reload()
    return {"success": True,
            "weight_overrides": get_weight_overrides(),
            "actions": get_actions()}


def _read(path: str):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _restore(path: str, content):
    try:
        if content is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            _write_atomic(path, content)
    except Exception as e:
        logger.error(f"rspamd_tuning rollback {path}: {e}")


def _configtest() -> tuple[bool, str]:
    try:
        r = subprocess.run(["rspamadm", "configtest"], capture_output=True,
                           text=True, timeout=30)
        # configtest devuelve 0 y "syntax OK" si todo bien (los warnings no fallan).
        ok = r.returncode == 0 and "syntax OK" in (r.stdout + r.stderr)
        return ok, (r.stdout + r.stderr).strip()[-300:]
    except Exception as e:
        return False, str(e)


def _reload():
    try:
        subprocess.run(["systemctl", "reload", "rspamd"],
                       check=False, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"No se pudo recargar rspamd: {e}")


def status() -> dict:
    """Estado completo para la UI: umbrales actuales, overrides y catálogo de
    símbolos con sus pesos efectivos."""
    return {
        "actions": get_actions(),
        "default_actions": DEFAULT_ACTIONS,
        "action_bounds": ACTION_BOUNDS,
        "weight_overrides": get_weight_overrides(),
        "symbols": list_symbols(),
        "rules": get_rules(),
        "rule_types": RULE_TYPES,
        "rule_actions": RULE_ACTIONS,
        "rule_matches": RULE_MATCHES,
    }


# ── Persistencia en BD + regeneración (para install/update) ──────────────────

def save_to_db_json(weight_overrides: dict, actions: dict) -> str:
    """Serializa la config para guardar en Settings.rspamd_overrides."""
    return json.dumps({"weights": weight_overrides, "actions": actions})


def apply_from_db_json(raw: str | None) -> dict:
    """Regenera los drop-ins desde el JSON guardado (idempotente)."""
    if not raw:
        return {"success": True, "note": "sin overrides guardados"}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"success": False, "error": "JSON inválido en Settings"}
    res = apply(data.get("weights") or {}, data.get("actions") or None)
    if data.get("rules") is not None:
        apply_rules(data.get("rules") or [])
    return res


# ── Reglas de contenido del admin (globales) ────────────────────────────────
# Cada regla: {type: from|subject|word, pattern: str, action: reject|spam|allow,
#              weight: float (solo para 'spam')}.

def _rule_symbol(idx: int, action: str) -> str:
    return f"SVQ_ADMIN_{action.upper()}_{idx}"


def get_rules() -> list[dict]:
    """Lee las reglas guardadas (JSON propio)."""
    if not os.path.exists(RULES_JSON):
        return []
    try:
        with open(RULES_JSON) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"rspamd_tuning.get_rules: {e}")
    return []


def _regex_escape(pat: str) -> str:
    """Escapa para un regex de Rspamd con delimitador '/'. re.escape NO escapa
    la barra '/', que rompería el delimitador (bug: 'design/redesign')."""
    return re.escape(pat).replace("/", r"\/")


def _write_rule_map(idx: int, rule: dict) -> str:
    """Escribe el mapa de una regla y devuelve su ruta.

    match: 'exact' = el campo es EXACTAMENTE el patrón (anclado ^...$);
           'contains' (por defecto) = el patrón aparece como subcadena.
    """
    os.makedirs(RULES_MAPDIR, exist_ok=True)
    path = os.path.join(RULES_MAPDIR, f"rule_{idx}.map")
    pat = rule["pattern"].strip()
    match = rule.get("match", "contains")
    if rule["type"] == "from" and pat.startswith("@"):
        # @dominio.com → casa cualquier dirección de ese dominio.
        line = f'/.*@{_regex_escape(pat[1:])}$/i'
    elif rule["type"] in ("subject", "word"):
        esc = _regex_escape(pat)
        # 'exact' ancla inicio/fin; 'contains' busca la subcadena.
        line = f'/^{esc}$/i' if match == "exact" else f'/{esc}/i'
    else:
        # from con dirección exacta (no @dominio): comparación literal.
        line = pat
    _write_atomic(path, line + "\n")
    return path


def build_admin_rules_blocks() -> str:
    """Devuelve los bloques de multimap de las reglas del admin (para que el
    RspamdManager los inyecte en multimap.conf, que es el ÚNICO sitio que Rspamd
    lee para reglas multimap). Escribe también los mapas. Sin reglas → "".
    """
    rules = get_rules()
    sel = {"from": 'type = "from";',
           "subject": 'type = "header";\n  header = "Subject";',
           "word": 'type = "content";\n  filter = "body";'}
    out = []
    for i, r in enumerate(rules):
        if r.get("type") not in RULE_TYPES or not r.get("pattern", "").strip():
            continue
        action = r.get("action", "spam")
        sym = _rule_symbol(i, action)
        mp = _write_rule_map(i, r)
        literal_from = r["type"] == "from" and not r["pattern"].strip().startswith("@")
        regexp = "" if literal_from else "  regexp = true;\n"
        if action == "reject":
            extra = '  prefilter = true;\n  action = "reject";\n  message = "Bloqueado por regla del administrador";\n'
        elif action == "allow":
            extra = '  prefilter = true;\n  action = "accept";\n'
        else:  # spam → suma peso
            extra = f'  score = {float(r.get("weight", 6.0)):.1f};\n'
        out.append(f"""\
# ── regla admin: {r['type']} {r.get('match','contains')} «{r['pattern'][:40]}» → {action} ──
{sym} {{
  {sel[r["type"]]}
{regexp}  map = "{mp}";
  symbol = "{sym}";
{extra}}}""")
    return ("\n".join(out) + "\n") if out else ""


def apply_rules(rules: list[dict]) -> dict:
    """Persiste las reglas (JSON) y regenera multimap.conf vía RspamdManager
    (con validación+rollback). Las reglas viven en multimap.conf junto a las
    blacklists por dominio; rspamd_manager las inyecta llamando a
    build_admin_rules_blocks()."""
    prev = _read(RULES_JSON)
    # Validar entrada mínima.
    clean = [r for r in (rules or []) if r.get("pattern", "").strip()
             and r.get("type") in RULE_TYPES]
    _write_atomic(RULES_JSON, json.dumps(clean))

    try:
        from scripts.rspamd_manager import RspamdManager
        from api.models.database import SessionLocal, load_all_models
        load_all_models()
        from api.models.models_mail import MailDomain
        db = SessionLocal()
        RspamdManager().rebuild_from_db(db.query(MailDomain).all())
        db.close()
    except Exception as e:
        _restore(RULES_JSON, prev)
        return {"success": False, "error": f"No se pudo regenerar: {e}"}

    ok, err = _configtest()
    if not ok:
        _restore(RULES_JSON, prev)
        try:
            from scripts.rspamd_manager import RspamdManager
            from api.models.database import SessionLocal, load_all_models
            load_all_models()
            from api.models.models_mail import MailDomain
            db = SessionLocal()
            RspamdManager().rebuild_from_db(db.query(MailDomain).all())
            db.close()
        except Exception:
            pass
        return {"success": False, "error": f"Config inválida, revertido: {err}"}
    return {"success": True, "rules": get_rules()}
