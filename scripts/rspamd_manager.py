"""
Gestión de configuración antispam por dominio (Rspamd)

Estrategia:
  · settings.conf  → umbrales personalizados + whitelist por dominio
  · multimap.conf  → blacklist por dominio (prefilter → reject inmediato)

Los ficheros de mapa de blacklist se guardan en:
  /etc/rspamd/maps/domains/{safe_domain}/blacklist.map
"""

import os
import re
import json
import shutil
import subprocess
from urllib.request import urlopen, Request


class RspamdManager:
    SETTINGS_FILE   = "/etc/rspamd/local.d/settings.conf"
    MULTIMAP_FILE   = "/etc/rspamd/local.d/multimap.conf"
    CONTROLLER_FILE = "/etc/rspamd/local.d/worker-controller.inc"
    MAPS_DIR        = "/etc/rspamd/maps/domains"
    RSPAMD_API      = "http://127.0.0.1:11334"

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _safe_name(self, domain):
        """dominio → identificador válido para Rspamd (ej: example.com → example_com)"""
        return re.sub(r'[^a-z0-9]', '_', domain.lower())

    def _parse_entries(self, raw: str) -> list:
        """Divide un bloque de texto (una entrada por línea) en lista limpia"""
        return [e.strip().lower() for e in (raw or "").splitlines() if e.strip()]

    def _to_rspamd_pattern(self, entry: str) -> str:
        """
        Convierte una entrada a patrón válido para Rspamd settings.
        @domain.com  →  @domain.com  (Rspamd lo reconoce como wildcard de dominio)
        user@domain  →  user@domain  (dirección exacta)
        """
        return entry

    # ─── settings.conf (umbrales + whitelist) ─────────────────────────────

    def _build_settings_conf(self, domain_configs):
        """
        Genera settings.conf con umbrales personalizados y whitelist.
        NOTA: local.d/settings.conf se inyecta dentro de settings{} automáticamente.
        """
        out = ["# SVQPanel — Generado automáticamente. NO editar manualmente.\n"]

        for cfg in domain_configs:
            domain = cfg["domain"]
            safe   = self._safe_name(domain)
            tag    = float(cfg.get("tag_threshold", 6.0))
            reject = float(cfg.get("reject_threshold", 15.0))

            # ── Umbrales de spam ──────────────────────────────────────────
            out.append(f"""\
# ── {domain} ──
{safe}_thresholds {{
  rcpt_domain = ["{domain}"];
  priority = 5;
  apply {{
    actions {{
      "add header" = {tag:.1f};
      reject = {reject:.1f};
      greylist = 4.0;
    }}
  }}
}}
""")
            # ── Whitelist: subir umbrales a valores inalcanzables ─────────
            wl = cfg.get("whitelist_entries", [])
            if wl:
                wl_list = ", ".join(f'"{self._to_rspamd_pattern(e)}"' for e in wl)
                out.append(f"""\
{safe}_whitelist {{
  rcpt_domain = ["{domain}"];
  from = [{wl_list}];
  priority = 10;
  apply {{
    actions {{
      "add header" = 999.0;
      greylist = 999.0;
      reject = 9999.0;
    }}
  }}
}}
""")

        return "\n".join(out)

    def _write_settings_conf(self, content):
        """Escribe settings.conf de forma atómica"""
        tmp = self.SETTINGS_FILE + ".tmp"
        os.makedirs(os.path.dirname(self.SETTINGS_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, self.SETTINGS_FILE)

    # ─── multimap.conf (blacklist prefilter) ──────────────────────────────

    def _entry_to_map_line(self, entry: str) -> str:
        """
        Convierte una entrada de blacklist al formato correcto para el mapa regexp.
        @domain.com   →  /.*@domain\.com$/   (bloquea todo el dominio)
        user@domain   →  user@domain         (dirección exacta, sin cambios)
        """
        if entry.startswith('@'):
            escaped = re.escape(entry[1:])   # escapa puntos del dominio
            return f'/.*@{escaped}$/'
        return entry

    def _write_blacklist_map(self, domain, entries):
        """Escribe el fichero de mapa de blacklist para un dominio"""
        safe = self._safe_name(domain)
        d    = os.path.join(self.MAPS_DIR, safe)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "blacklist.map")
        lines = [self._entry_to_map_line(e) for e in entries if e.strip()]
        content = "\n".join(lines) + "\n"
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, path)
        return path

    def _build_multimap_conf(self, domain_configs):
        """
        Genera multimap.conf con una regla prefilter por dominio.
        Usa type="from" + regexp=true para soportar dominios completos (@domain)
        y direcciones exactas en el mismo fichero de mapa.
        El prefilter rechaza ANTES de cualquier scoring.
        """
        out = ["# SVQPanel — Generado automáticamente. NO editar manualmente.\n"]

        for cfg in domain_configs:
            domain = cfg["domain"]
            safe   = self._safe_name(domain)
            bl     = cfg.get("blacklist_entries", [])

            if not bl:
                continue

            map_path = os.path.join(self.MAPS_DIR, safe, "blacklist.map")
            symbol   = f"SVQ_BL_{safe.upper()}"

            out.append(f"""\
# ── blacklist {domain} ──
{symbol} {{
  type = "from";
  regexp = true;
  map = "{map_path}";
  symbol = "{symbol}";
  prefilter = true;
  action = "reject";
  message = "Remitente bloqueado";
}}
""")

        return "\n".join(out)

    def _write_multimap_conf(self, content):
        """Escribe multimap.conf de forma atómica"""
        tmp = self.MULTIMAP_FILE + ".tmp"
        os.makedirs(os.path.dirname(self.MULTIMAP_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, self.MULTIMAP_FILE)

    # ─── API pública ──────────────────────────────────────────────────────

    def rebuild_from_db(self, mail_domains):
        """
        Regenera settings.conf y multimap.conf desde la BD.
        Llamar siempre que cambie cualquier dominio de correo.
        """
        configs = []
        for md in mail_domains:
            bl_entries = self._parse_entries(md.blacklist_senders)
            wl_entries = self._parse_entries(md.whitelist_senders)

            # Escribir/limpiar fichero de mapa de blacklist
            safe     = self._safe_name(md.domain_name)
            map_path = os.path.join(self.MAPS_DIR, safe, "blacklist.map")
            if bl_entries:
                self._write_blacklist_map(md.domain_name, bl_entries)
            elif os.path.exists(map_path):
                os.remove(map_path)

            configs.append({
                "domain":            md.domain_name,
                "tag_threshold":     md.spam_tag_threshold    or 6.0,
                "reject_threshold":  md.spam_reject_threshold or 15.0,
                "whitelist_entries": wl_entries,
                "blacklist_entries": bl_entries,
            })

        self._write_settings_conf(self._build_settings_conf(configs))
        self._write_multimap_conf(self._build_multimap_conf(configs))
        self._reload_rspamd()

    def remove_domain(self, domain):
        """Elimina los ficheros de mapa de un dominio"""
        d = os.path.join(self.MAPS_DIR, self._safe_name(domain))
        if os.path.exists(d):
            shutil.rmtree(d)

    # ─── Estadísticas ─────────────────────────────────────────────────────

    def get_global_stats(self):
        """Estadísticas globales vía rspamc stat"""
        try:
            result = subprocess.run(
                ["rspamc", "stat"],
                capture_output=True, text=True, timeout=5
            )
            stats = {
                "scanned": 0, "rejected": 0, "tagged": 0,
                "greylisted": 0, "clean": 0, "learned": 0,
            }
            for line in result.stdout.splitlines():
                def _num(l):
                    m = re.search(r'(\d+)', l)
                    return int(m.group(1)) if m else 0
                if "Messages scanned"    in line: stats["scanned"]    = _num(line)
                elif "action reject"     in line: stats["rejected"]   = _num(line)
                elif "action add header" in line: stats["tagged"]     = _num(line)
                elif "action greylist"   in line: stats["greylisted"] = _num(line)
                elif "action no action"  in line: stats["clean"]      = _num(line)
                elif "Messages learned"  in line: stats["learned"]    = _num(line)
            return stats
        except Exception as e:
            return {
                "scanned": 0, "rejected": 0, "tagged": 0,
                "greylisted": 0, "clean": 0, "learned": 0,
                "error": str(e)
            }

    def _ensure_controller_secure_ip(self):
        """
        Añade secure_ip para localhost en worker-controller.inc si no existe.
        Necesario para que la API HTTP funcione sin contraseña desde localhost.
        Solo escribe/recarga una vez; las siguientes llamadas son un simple read.
        """
        try:
            content = ""
            if os.path.exists(self.CONTROLLER_FILE):
                with open(self.CONTROLLER_FILE) as f:
                    content = f.read()
            if "secure_ip" not in content:
                os.makedirs(os.path.dirname(self.CONTROLLER_FILE), exist_ok=True)
                with open(self.CONTROLLER_FILE, "a") as f:
                    f.write('\n# SVQPanel: acceso local sin contraseña\n'
                            'secure_ip = ["127.0.0.1", "::1"];\n')
                subprocess.run(["systemctl", "reload", "rspamd"],
                               timeout=10, capture_output=True)
                import time; time.sleep(1.5)   # esperar recarga
        except Exception:
            pass

    def get_history(self, limit=200):
        """
        Historial reciente vía HTTP API.
        Configura secure_ip automáticamente en el primer uso si falta.
        Soporta respuesta como array (Rspamd 3.x) u objeto con 'rows' (4.x).
        """
        url = f"{self.RSPAMD_API}/history?rows={limit}"

        def _fetch():
            with urlopen(Request(url), timeout=5) as resp:
                data = json.loads(resp.read())
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("rows", [])
            return []

        # Intento directo
        try:
            return _fetch()
        except Exception:
            pass

        # Fallo → configurar secure_ip + reintentar
        self._ensure_controller_secure_ip()
        try:
            return _fetch()
        except Exception:
            return []

    def _msg_rcpts(self, msg: dict) -> list:
        """
        Devuelve la lista de destinatarios de un mensaje del historial.
        Rspamd 4.x usa rcpt_smtp / rcpt_mime; versiones anteriores usaban rcpts.
        """
        return (msg.get("rcpt_smtp")
                or msg.get("rcpt_mime")
                or msg.get("rcpts")
                or [])

    def _msg_from(self, msg: dict) -> str:
        """Remitente del mensaje (sender_smtp en 4.x, from en versiones anteriores)"""
        return (msg.get("sender_smtp")
                or msg.get("sender_mime")
                or msg.get("from")
                or "")

    def _msg_time(self, msg: dict) -> float:
        """Timestamp Unix del mensaje (unix_time en 4.x, time en versiones anteriores)"""
        return float(msg.get("unix_time") or msg.get("time") or 0)

    def get_domain_stats(self, domain, limit=500):
        """Estadísticas y mensajes recientes filtrados por dominio destinatario"""
        from datetime import datetime, timezone

        history  = self.get_history(limit=limit)
        domain_l = domain.lower()
        filtered = [
            msg for msg in history
            if any(r.lower().endswith(f"@{domain_l}")
                   for r in self._msg_rcpts(msg))
        ]

        stats = {
            "scanned": len(filtered), "rejected": 0, "tagged": 0,
            "greylisted": 0, "clean": 0, "history": [],
        }
        for msg in filtered:
            action = msg.get("action", "")
            if action == "reject":       stats["rejected"]   += 1
            elif action == "add header": stats["tagged"]     += 1
            elif action == "greylist":   stats["greylisted"] += 1
            else:                        stats["clean"]      += 1

        # Últimos 25 mensajes, más recientes primero
        recent = sorted(filtered, key=self._msg_time, reverse=True)[:25]
        for msg in recent:
            ts = self._msg_time(msg)
            if ts:
                try:
                    ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    ts = str(ts)
            else:
                ts = ""
            stats["history"].append({
                "id":             str(msg.get("message-id") or msg.get("id") or ""),
                "from_addr":      str(self._msg_from(msg)),
                "subject":        str(msg.get("subject") or "(sin asunto)"),
                "action":         str(msg.get("action") or ""),
                "score":          float(msg.get("score") or 0),
                "required_score": float(msg.get("required_score") or 0),
                "timestamp":      str(ts),
                "size":           int(msg.get("size") or 0),
                "ip":             str(msg.get("ip") or ""),
            })
        return stats

    # ─── Utilidades ───────────────────────────────────────────────────────

    def _reload_rspamd(self):
        """Recarga la configuración de Rspamd sin downtime"""
        try:
            subprocess.run(["systemctl", "reload", "rspamd"],
                           timeout=10, capture_output=True)
        except Exception:
            pass

    def rspamd_available(self):
        return os.path.exists("/etc/rspamd")
