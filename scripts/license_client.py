"""
Cliente de licencias de SVQPanel.

El panel valida su licencia contra el servidor de SVQHost (Laravel). El servidor
responde con un `payload` JSON y una `signature` Ed25519. El panel verifica la
firma con la clave PÚBLICA embebida aquí (no secreta: solo sirve para verificar,
no para firmar). Sin firma válida → licencia no válida.

Flujo:
  validate() → si hay caché válida (<ttl) la usa; si no, llama al servidor,
  verifica la firma, cachea el payload+signature y devuelve el estado.

Garantía: nadie puede falsificar un "valid:true" sin la clave PRIVADA (que solo
está en el Laravel de SVQHost). Editar este archivo para saltarse la comprobación
es posible (Python en máquina del cliente), pero implica perder updates/soporte;
en fase 2 se compilará a binario (Cython) para subir el listón.

Reutiliza: `requests` y `cryptography` (Ed25519), ya en requirements.txt.
"""
import os
import json
import time
import base64
import socket
import hashlib
import logging

logger = logging.getLogger(__name__)

# ── Configuración ────────────────────────────────────────────────────────────
# Clave pública Ed25519 del servidor de licencias de SVQHost (base64, 32 bytes).
# NO es secreta: solo permite VERIFICAR firmas, no crearlas.
LICENSE_PUBLIC_KEY_B64 = "FZoE85QLONFkpo2kztDIKYjBtXQn00OMcLo7lHYYiiQ="

# URL del servidor de licencias. Override por entorno para dev/prod.
LICENSE_SERVER_URL = os.getenv(
    "SVQ_LICENSE_SERVER", "https://www.svqhost.com"
).rstrip("/")

LICENSE_FILE  = "/etc/svqpanel/license"        # la key, una línea
LICENSE_CACHE = "/etc/svqpanel/license.cache"  # respuesta firmada cacheada (JSON)

DEFAULT_TTL_HOURS = 72       # máximo que se confía la caché sin revalidar
HTTP_TIMEOUT = 10            # segundos para la llamada al servidor


# ── Fingerprint del servidor ─────────────────────────────────────────────────
def _fingerprint() -> str:
    """Huella estable de esta máquina: machine-id + hostname → sha256.
    Ata la licencia a un servidor concreto (anti-compartir)."""
    parts = []
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as f:
                parts.append(f.read().strip())
                break
        except OSError:
            continue
    try:
        parts.append(socket.gethostname())
    except Exception:
        pass
    raw = "|".join(parts) or "unknown"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Lectura de la key ────────────────────────────────────────────────────────
def _read_license_key() -> str:
    try:
        with open(LICENSE_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def write_license_key(key: str) -> None:
    """Guarda la key en /etc/svqpanel/license (la usa /license/activate)."""
    os.makedirs(os.path.dirname(LICENSE_FILE), exist_ok=True)
    with open(LICENSE_FILE, "w") as f:
        f.write((key or "").strip() + "\n")
    try:
        os.chmod(LICENSE_FILE, 0o600)
    except OSError:
        pass


# ── Verificación de firma ────────────────────────────────────────────────────
def _canonical_message(payload: dict) -> bytes:
    """Serializa el payload EXACTAMENTE como lo firma el Laravel:
    json_encode(JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE) ==
    json.dumps(separators=(',',':'), ensure_ascii=False)."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_signature(payload: dict, signature_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(LICENSE_PUBLIC_KEY_B64))
        pub.verify(base64.b64decode(signature_b64), _canonical_message(payload))
        return True
    except Exception as e:
        logger.warning("license: firma inválida (%s)", e)
        return False


# ── Caché ────────────────────────────────────────────────────────────────────
def _read_cache() -> dict:
    try:
        with open(LICENSE_CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_cache(payload: dict, signature: str) -> None:
    try:
        os.makedirs(os.path.dirname(LICENSE_CACHE), exist_ok=True)
        with open(LICENSE_CACHE, "w") as f:
            json.dump({"payload": payload, "signature": signature,
                       "cached_at": int(time.time())}, f)
        os.chmod(LICENSE_CACHE, 0o600)
    except OSError:
        pass


def _cache_age_hours(cache: dict) -> float:
    return (time.time() - cache.get("cached_at", 0)) / 3600.0


# ── API pública ──────────────────────────────────────────────────────────────
def _result(valid: bool, reason: str, payload: dict = None) -> dict:
    payload = payload or {}
    return {
        "valid":   bool(valid),
        "reason":  reason,
        "plan":    payload.get("plan"),
        "expires": payload.get("expires"),
        "fingerprint": _fingerprint(),
    }


def validate(force: bool = False) -> dict:
    """Valida la licencia. Devuelve {valid, reason, plan, expires, fingerprint}.

    - Sin key → reason='no_key'.
    - Usa caché si es válida y reciente (<ttl) salvo force=True.
    - Si el servidor no responde pero la caché aún es válida → sigue valid.
    - Si la caché caducó y no hay red → valid=False, reason='offline'.
    """
    key = _read_license_key()
    if not key:
        return _result(False, "no_key")

    cache = _read_cache()
    cached_payload = cache.get("payload") or {}
    cached_sig = cache.get("signature")
    ttl = cached_payload.get("ttl_hours", DEFAULT_TTL_HOURS)

    # 1) Caché fresca y válida → úsala (salvo force)
    if not force and cached_payload and cached_sig:
        if cached_payload.get("key") == key and _cache_age_hours(cache) < ttl:
            if _verify_signature(cached_payload, cached_sig) and cached_payload.get("valid"):
                return _result(True, "ok", cached_payload)

    # 2) Llamar al servidor
    try:
        import requests
        resp = requests.post(
            f"{LICENSE_SERVER_URL}/api/license/validate",
            json={"key": key, "fingerprint": _fingerprint(),
                  "version": _panel_version()},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": f"SVQPanel/{_panel_version()}"},
        )
        data = resp.json()
        payload = data.get("payload") or {}
        signature = data.get("signature") or ""

        # La firma DEBE validar y atar a esta key+fingerprint
        if not _verify_signature(payload, signature):
            return _result(False, "bad_signature")
        if payload.get("key") != key:
            return _result(False, "key_mismatch")
        if payload.get("fingerprint") not in (None, _fingerprint()):
            return _result(False, "fingerprint_mismatch", payload)

        # Cachear siempre la respuesta firmada (válida o no) para no machacar al server
        _write_cache(payload, signature)
        return _result(bool(payload.get("valid")), payload.get("reason", "ok"), payload)

    except Exception as e:
        logger.warning("license: no se pudo contactar el servidor (%s)", e)
        # 3) Sin red: si la caché aún no caducó y es válida, seguimos
        if cached_payload and cached_sig and cached_payload.get("key") == key:
            if _cache_age_hours(cache) < ttl and _verify_signature(cached_payload, cached_sig):
                if cached_payload.get("valid"):
                    return _result(True, "ok_cached", cached_payload)
        return _result(False, "offline")


def status() -> dict:
    """Estado SIN forzar llamada de red (lee caché). Para la UI."""
    key = _read_license_key()
    if not key:
        return _result(False, "no_key")
    cache = _read_cache()
    payload = cache.get("payload") or {}
    sig = cache.get("signature")
    if payload and sig and payload.get("key") == key:
        ttl = payload.get("ttl_hours", DEFAULT_TTL_HOURS)
        fresh = _cache_age_hours(cache) < ttl
        ok = fresh and _verify_signature(payload, sig) and payload.get("valid")
        return _result(bool(ok), "ok" if ok else ("stale" if not fresh else "invalid"), payload)
    return _result(False, "unknown")


def _panel_version() -> str:
    try:
        from config.config import PANEL_VERSION
        return PANEL_VERSION
    except Exception:
        return "0.0.0"
