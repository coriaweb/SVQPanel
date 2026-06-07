"""
Helper de CrowdSec — wrapper sobre `cscli`.

CrowdSec es un IPS colaborativo: detecta comportamientos sospechosos a partir
de logs (sshd, nginx, postfix...) y mantiene una blocklist local + una
blocklist comunitaria opcional. Las decisiones (bans) son aplicadas por
bouncers externos (firewall, nginx, etc.).

Este módulo encapsula `cscli` con timeouts y parseo de JSON estructurado.
"""

import json
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CSCLI_BIN = "/usr/bin/cscli"
CROWDSEC_BIN = "/usr/bin/crowdsec"


# ─────────────────────────────────────────────────────────────────────────────
# Estado básico
# ─────────────────────────────────────────────────────────────────────────────
def is_installed() -> bool:
    """¿Está cscli en el sistema?"""
    return shutil.which("cscli") is not None or _exists(CSCLI_BIN)


def is_running() -> bool:
    """¿Está el servicio crowdsec activo?"""
    # Ruta absoluta: el servicio systemd del panel arranca con PATH=venv/bin,
    # así que 'systemctl' a secas no se resuelve.
    systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
    try:
        r = subprocess.run(
            [systemctl, "is-active", "--quiet", "crowdsec"],
            timeout=4,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def version() -> Optional[str]:
    """Versión de cscli (corta), o None si no está instalado."""
    rc, out, _ = _run(["version"])
    if rc != 0:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return out.splitlines()[0].strip() if out else None


def _exists(path: str) -> bool:
    import os
    return os.path.exists(path)


def _run(args: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Ejecuta `cscli <args>` con timeout."""
    bin_path = CSCLI_BIN if _exists(CSCLI_BIN) else "cscli"
    try:
        r = subprocess.run(
            [bin_path] + args, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "cscli no encontrado"
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout esperando a cscli"


def _run_json(args: List[str], timeout: int = 10) -> Tuple[int, Any, str]:
    """Ejecuta cscli con `-o json` y parsea el output."""
    rc, out, err = _run(args + ["-o", "json"], timeout=timeout)
    if rc != 0:
        return rc, None, err.strip() or out.strip()
    out = out.strip()
    if not out or out == "null":
        return 0, [], ""
    try:
        return 0, json.loads(out), ""
    except json.JSONDecodeError as e:
        return 2, None, f"output no es JSON válido: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Decisiones (bans activos)
# ─────────────────────────────────────────────────────────────────────────────
def list_decisions() -> List[Dict[str, Any]]:
    """
    Lista las decisiones activas (bans). Cada decisión incluye:
      id, ip, scenario, type (ban|captcha|...), duration, origin, scope, value
    """
    rc, data, err = _run_json(["decisions", "list"])
    if rc != 0 or data is None:
        return []
    out: List[Dict[str, Any]] = []
    # cscli decisions list devuelve dos formas:
    #   - Anidada: [{ "scenario":..., "decisions":[ {...}, ... ], "events":[...] }, ...]
    #     donde la fuente (alerta) lleva los datos completos en cada item de
    #     'decisions'. OJO: 'decisions' puede ser [] (alerta SIN decisión activa:
    #     el ban ya expiró). Esas hay que IGNORARLAS, no convertir la alerta en
    #     una fila (que saldría con value/type/duration en blanco = guiones).
    #   - Plana: [ {value, type, duration, ...}, ... ] sin clave 'decisions'.
    for src in data:
        if not isinstance(src, dict):
            continue
        if "decisions" in src:
            # Forma anidada: solo procesamos las decisiones reales; [] se ignora.
            for d in src.get("decisions") or []:
                if isinstance(d, dict) and d.get("value"):
                    out.append(_decision_row(d))
        elif src.get("value"):
            # Forma plana: la propia fuente es una decisión.
            out.append(_decision_row(src))
    return out


def _decision_row(d: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza una decisión de cscli a la fila que consume el frontend."""
    simulated = d.get("simulated", False)
    return {
        "id":         d.get("id"),
        "value":      d.get("value"),
        "scope":      d.get("scope"),
        "type":       d.get("type"),
        "scenario":   d.get("scenario"),
        "origin":     d.get("origin"),
        "duration":   d.get("duration"),
        "country":    "SIMULATED" if simulated else (d.get("country") or ""),
        "created_at": d.get("created_at") or d.get("until"),
        "until":      d.get("until"),
    }


def add_decision(
    ip: str,
    duration: str = "4h",
    reason: Optional[str] = None,
    decision_type: str = "ban",
) -> Tuple[bool, str]:
    """
    Añade una decisión manual. duration en formato cscli: '4h', '1d', '15m'…
    reason aparece como 'scenario' en la lista.
    """
    args = ["decisions", "add", "--ip", ip, "--duration", duration, "--type", decision_type]
    if reason:
        args += ["--reason", reason]
    rc, out, err = _run(args, timeout=8)
    if rc != 0:
        return False, (err or out).strip()
    return True, "added"


def delete_decision_by_id(decision_id: int) -> Tuple[bool, str]:
    rc, out, err = _run(["decisions", "delete", "--id", str(decision_id)], timeout=8)
    if rc != 0:
        return False, (err or out).strip()
    return True, "deleted"


def delete_decision_by_ip(ip: str) -> Tuple[bool, str]:
    rc, out, err = _run(["decisions", "delete", "--ip", ip], timeout=8)
    if rc != 0:
        return False, (err or out).strip()
    return True, "deleted"


# ─────────────────────────────────────────────────────────────────────────────
# Alertas
# ─────────────────────────────────────────────────────────────────────────────
def list_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Lista las alertas recientes generadas por escenarios.
    """
    rc, data, _ = _run_json(["alerts", "list", "--limit", str(limit)])
    if rc != 0 or data is None:
        return []
    out: List[Dict[str, Any]] = []
    for a in data:
        if not isinstance(a, dict):
            continue
        src = a.get("source") or {}
        out.append({
            "id":            a.get("id"),
            "machine_id":    a.get("machine_id"),
            "scenario":      a.get("scenario"),
            "message":       a.get("message"),
            "events_count":  a.get("events_count"),
            "start_at":      a.get("start_at"),
            "stop_at":       a.get("stop_at"),
            "created_at":    a.get("created_at"),
            "source_ip":     src.get("ip") or src.get("value"),
            "source_scope":  src.get("scope"),
            "source_country": src.get("cn") or src.get("country"),
            "source_as":     src.get("as_name") or src.get("as_number"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Bouncers
# ─────────────────────────────────────────────────────────────────────────────
def list_bouncers() -> List[Dict[str, Any]]:
    rc, data, _ = _run_json(["bouncers", "list"])
    if rc != 0 or data is None:
        return []
    out: List[Dict[str, Any]] = []
    for b in data:
        if not isinstance(b, dict):
            continue
        out.append({
            "name":       b.get("name"),
            "revoked":    b.get("revoked", False),
            "ip_address": b.get("ip_address"),
            "type":       b.get("type"),
            "version":    b.get("version"),
            "last_pull":  b.get("last_pull"),
            "created_at": b.get("created_at"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Colecciones / hub
# ─────────────────────────────────────────────────────────────────────────────
def list_collections() -> List[Dict[str, Any]]:
    """
    Lista las colecciones instaladas (paquetes de escenarios/parsers).
    """
    rc, data, _ = _run_json(["collections", "list"])
    if rc != 0 or data is None:
        return []
    # Estructura: {"collections":[...]}
    items = data.get("collections", []) if isinstance(data, dict) else data
    out: List[Dict[str, Any]] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        out.append({
            "name":      c.get("name"),
            "status":    c.get("status"),
            "version":   c.get("local_version") or c.get("version"),
            "description": c.get("description"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Métricas y estado del CAPI (community blocklist)
# ─────────────────────────────────────────────────────────────────────────────
def metrics_summary() -> Dict[str, Any]:
    """
    Devuelve un resumen de métricas (acquisitions, parsers, buckets).
    cscli metrics no acepta -o json en versiones antiguas → fallback a texto.
    """
    rc, data, _ = _run_json(["metrics"])
    if rc == 0 and data is not None:
        return data if isinstance(data, dict) else {"raw": data}
    # Fallback: parseo de texto resumido
    rc2, out, _ = _run(["metrics"], timeout=8)
    return {"text": out} if rc2 == 0 else {}


def capi_status() -> Dict[str, Any]:
    """
    Estado del CAPI (Central API): si estamos enrolados y recibiendo blocklist
    comunitaria.
    """
    rc, out, err = _run(["capi", "status"], timeout=8)
    info: Dict[str, Any] = {
        "enrolled":  False,
        "logged_in": False,
        "raw":       (out or err or "").strip(),
    }
    text = (out + err).lower()
    if "you can successfully interact" in text or "ok" in text:
        info["logged_in"] = True
    if "enrolled" in text:
        info["enrolled"] = True
    return info


# ─────────────────────────────────────────────────────────────────────────────
# Resumen para el dashboard
# ─────────────────────────────────────────────────────────────────────────────
def overview() -> Dict[str, Any]:
    """
    Snapshot ligero para la UI: si está instalado, si está corriendo,
    versión, número de decisiones, bouncers, colecciones.
    """
    installed = is_installed()
    if not installed:
        return {
            "installed": False,
            "running":   False,
            "version":   None,
            "decisions": 0,
            "bouncers":  0,
            "collections": 0,
        }
    running = is_running()
    decisions = list_decisions() if running else []
    bouncers = list_bouncers() if running else []
    collections = list_collections() if running else []
    return {
        "installed":   True,
        "running":     running,
        "version":     version(),
        "decisions":   len(decisions),
        "bouncers":    len(bouncers),
        "collections": len(collections),
    }
