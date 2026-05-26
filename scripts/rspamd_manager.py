"""
Gestión de configuración antispam por dominio (Rspamd)
- Umbrales de spam (tag / reject) por dominio
- Whitelist y blacklist de remitentes por dominio
- Estadísticas globales vía rspamc
"""

import os
import re
import json
import shutil
import subprocess
from urllib.request import urlopen, Request
from urllib.error import URLError


class RspamdManager:
    SETTINGS_FILE = "/etc/rspamd/local.d/settings.conf"
    MAPS_DIR      = "/etc/rspamd/maps/domains"
    RSPAMD_API    = "http://127.0.0.1:11334"

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _safe_name(self, domain):
        """dominio → identificador válido para Rspamd (ej: example.com → example_com)"""
        return re.sub(r'[^a-z0-9]', '_', domain.lower())

    def _map_dir(self, domain):
        return os.path.join(self.MAPS_DIR, self._safe_name(domain))

    def _write_map_file(self, domain, filename, entries):
        """Escribe un fichero de mapa de Rspamd (atómico)"""
        d = self._map_dir(domain)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        content = "\n".join(e.strip().lower() for e in entries if e.strip()) + "\n"
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, path)
        return path

    def _map_has_entries(self, domain, filename):
        """Devuelve True si el fichero de mapa existe y tiene contenido"""
        path = os.path.join(self._map_dir(domain), filename)
        if not os.path.exists(path):
            return False
        with open(path) as f:
            return bool(f.read().strip())

    # ─── Generación de settings.conf ──────────────────────────────────────

    def _build_settings_conf(self, domain_configs):
        """
        Genera el contenido de settings.conf desde una lista de configuraciones.
        domain_configs: lista de dicts con claves:
          domain, tag_threshold, reject_threshold, has_whitelist, has_blacklist
        """
        lines = ["# SVQPanel — Generado automáticamente. NO editar manualmente.\nsettings {\n"]

        for cfg in domain_configs:
            domain = cfg["domain"]
            safe   = self._safe_name(domain)
            tag    = float(cfg.get("tag_threshold", 6.0))
            reject = float(cfg.get("reject_threshold", 15.0))

            lines.append(f"""\
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
            if cfg.get("has_whitelist"):
                wl = os.path.join(self.MAPS_DIR, safe, "whitelist.map")
                lines.append(f"""\
  {safe}_whitelist {{
    rcpt_domain = ["{domain}"];
    from = ["{wl}"];
    priority = 10;
    action = "accept";
  }}
""")
            if cfg.get("has_blacklist"):
                bl = os.path.join(self.MAPS_DIR, safe, "blacklist.map")
                lines.append(f"""\
  {safe}_blacklist {{
    rcpt_domain = ["{domain}"];
    from = ["{bl}"];
    priority = 10;
    action = "reject";
  }}
""")

        lines.append("}\n")
        return "\n".join(lines)

    def _write_settings_conf(self, content):
        """Escribe settings.conf de forma atómica"""
        tmp = self.SETTINGS_FILE + ".tmp"
        os.makedirs(os.path.dirname(self.SETTINGS_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, self.SETTINGS_FILE)

    # ─── API pública ──────────────────────────────────────────────────────

    def rebuild_from_db(self, mail_domains):
        """
        Regenera settings.conf y todos los ficheros de mapa
        desde la lista completa de MailDomain de la BD.
        Llamar siempre que cambie cualquier dominio.
        """
        configs = []
        for md in mail_domains:
            domain = md.domain_name
            safe   = self._safe_name(domain)

            # Sincronizar ficheros de mapa con lo que hay en BD
            wl_entries = [e for e in (md.whitelist_senders or "").splitlines() if e.strip()]
            bl_entries = [e for e in (md.blacklist_senders or "").splitlines() if e.strip()]

            if wl_entries:
                self._write_map_file(domain, "whitelist.map", wl_entries)
            elif os.path.exists(os.path.join(self._map_dir(domain), "whitelist.map")):
                os.remove(os.path.join(self._map_dir(domain), "whitelist.map"))

            if bl_entries:
                self._write_map_file(domain, "blacklist.map", bl_entries)
            elif os.path.exists(os.path.join(self._map_dir(domain), "blacklist.map")):
                os.remove(os.path.join(self._map_dir(domain), "blacklist.map"))

            configs.append({
                "domain":        domain,
                "tag_threshold":    md.spam_tag_threshold    or 6.0,
                "reject_threshold": md.spam_reject_threshold or 15.0,
                "has_whitelist": bool(wl_entries),
                "has_blacklist": bool(bl_entries),
            })

        content = self._build_settings_conf(configs)
        self._write_settings_conf(content)
        self._reload_rspamd()

    def remove_domain(self, domain):
        """Elimina los ficheros de mapa de un dominio"""
        d = self._map_dir(domain)
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
                "scanned":    0,
                "rejected":   0,
                "tagged":     0,
                "greylisted": 0,
                "clean":      0,
                "learned":    0,
            }
            for line in result.stdout.splitlines():
                def _num(l):
                    m = re.search(r'(\d+)', l)
                    return int(m.group(1)) if m else 0
                if "Messages scanned"         in line: stats["scanned"]    = _num(line)
                elif "action reject"          in line: stats["rejected"]   = _num(line)
                elif "action add header"      in line: stats["tagged"]     = _num(line)
                elif "action greylist"        in line: stats["greylisted"] = _num(line)
                elif "action no action"       in line: stats["clean"]      = _num(line)
                elif "Messages learned"       in line: stats["learned"]    = _num(line)
            return stats
        except Exception as e:
            return {
                "scanned": 0, "rejected": 0, "tagged": 0,
                "greylisted": 0, "clean": 0, "learned": 0,
                "error": str(e)
            }

    def get_history(self, limit=200):
        """
        Historial reciente de Rspamd vía HTTP API.
        Funciona si secure_ip incluye 127.0.0.1 en worker-controller.inc.
        """
        try:
            url = f"{self.RSPAMD_API}/history?limit={limit}"
            with urlopen(Request(url), timeout=5) as resp:
                return json.loads(resp.read())
        except Exception:
            return []

    def get_domain_stats(self, domain, limit=500):
        """Estadísticas filtradas por dominio destinatario"""
        history = self.get_history(limit=limit)
        filtered = [
            msg for msg in history
            if any(r.lower().endswith(f"@{domain.lower()}")
                   for r in msg.get("rcpts", []))
        ]
        stats = {"scanned": len(filtered), "rejected": 0, "tagged": 0,
                 "greylisted": 0, "clean": 0}
        for msg in filtered:
            action = msg.get("action", "")
            if action == "reject":              stats["rejected"]   += 1
            elif action == "add header":        stats["tagged"]     += 1
            elif action == "greylist":          stats["greylisted"] += 1
            else:                               stats["clean"]      += 1
        return stats

    # ─── Utilidades ───────────────────────────────────────────────────────

    def _reload_rspamd(self):
        """Recarga la configuración de Rspamd"""
        try:
            subprocess.run(["systemctl", "reload", "rspamd"],
                           timeout=10, capture_output=True)
        except Exception:
            pass

    def rspamd_available(self):
        return os.path.exists("/etc/rspamd")
