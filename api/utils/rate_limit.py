"""
Rate-limiting en memoria para el login del panel (anti fuerza bruta).

Primera línea de defensa, inmediata y sin dependencias externas: cuenta los
intentos fallidos por IP en una ventana deslizante y bloquea temporalmente
cuando se supera el umbral. Complementa a fail2ban (que actúa a nivel de
sistema con algo de latencia); este actúa en el mismo proceso al instante.

- Ventana y umbral configurables vía entorno:
    LOGIN_MAX_ATTEMPTS  (default 8)
    LOGIN_WINDOW_SEC    (default 900  = 15 min)
    LOGIN_BLOCK_SEC     (default 900  = 15 min de bloqueo al superar el umbral)

- Estado en memoria del proceso: si el panel se reinicia, se limpia. Es
  aceptable porque fail2ban cubre el caso de ataques sostenidos.

- Un login correcto limpia el contador de esa IP (record_success).
"""

import os
import time
import threading

_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "8"))
_WINDOW_SEC   = int(os.getenv("LOGIN_WINDOW_SEC", "900"))
_BLOCK_SEC    = int(os.getenv("LOGIN_BLOCK_SEC", "900"))

# ip -> {"fails": [timestamps], "blocked_until": float|None}
_state: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _prune(entry: dict, now: float) -> None:
    """Descarta intentos fuera de la ventana."""
    entry["fails"] = [t for t in entry["fails"] if now - t < _WINDOW_SEC]


def check_blocked(ip: str | None) -> int:
    """
    Devuelve los segundos restantes de bloqueo para la IP, o 0 si no está
    bloqueada. No modifica el estado salvo limpiar bloqueos expirados.
    """
    if not ip:
        return 0
    now = _now()
    with _lock:
        entry = _state.get(ip)
        if not entry:
            return 0
        blocked_until = entry.get("blocked_until")
        if blocked_until and blocked_until > now:
            return int(blocked_until - now) + 1
        if blocked_until and blocked_until <= now:
            # Bloqueo expirado: reiniciar el contador
            entry["blocked_until"] = None
            entry["fails"] = []
        return 0


def record_failure(ip: str | None) -> int:
    """
    Registra un intento fallido. Si con este intento se supera el umbral,
    activa el bloqueo. Devuelve los segundos de bloqueo (0 si aún no bloquea).
    """
    if not ip:
        return 0
    now = _now()
    with _lock:
        entry = _state.setdefault(ip, {"fails": [], "blocked_until": None})
        _prune(entry, now)
        entry["fails"].append(now)
        if len(entry["fails"]) >= _MAX_ATTEMPTS:
            entry["blocked_until"] = now + _BLOCK_SEC
            return _BLOCK_SEC
        return 0


def record_success(ip: str | None) -> None:
    """Login correcto: limpia el historial de esa IP."""
    if not ip:
        return
    with _lock:
        _state.pop(ip, None)


def remaining_attempts(ip: str | None) -> int:
    """Intentos que quedan antes de bloquear (informativo)."""
    if not ip:
        return _MAX_ATTEMPTS
    now = _now()
    with _lock:
        entry = _state.get(ip)
        if not entry:
            return _MAX_ATTEMPTS
        _prune(entry, now)
        return max(0, _MAX_ATTEMPTS - len(entry["fails"]))
