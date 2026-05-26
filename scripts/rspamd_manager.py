"""
Gestión de configuración antispam por dominio (Rspamd)
- Umbrales de spam (tag / reject) por dominio
- Whitelist y blacklist de remitentes por dominio (inlineadas en settings.conf)
- Estadísticas globales vía rspamc
"""

import os
import re
import json
import subprocess
from urllib.request import urlopen, Request


class RspamdManager:
    SETTINGS_FILE = "/etc/rspamd/local.d/settings.conf"
    RSPAMD_API    = "http://127.0.0.1:11334"

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

    # ─── Generación de settings.conf ──────────────────────────────────────

    def _build_settings_conf(self, domain_configs):
        """
        Genera el contenido de settings.conf.
        domain_configs: lista de dicts con claves:
          domain, tag_threshold, reject_threshold,
          whitelist_entries (list), blacklist_entries (list)
        """
        # NOTA: local.d/settings.conf se inyecta DENTRO del bloque settings{}
        # de Rspamd automáticamente — NO añadir wrapper "settings { }" exterior.
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
            # ── Whitelist (aceptar sin analizar) ─────────────────────────
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
            # ── Blacklist (rechazar inmediatamente) ───────────────────────
            bl = cfg.get("blacklist_entries", [])
            if bl:
                bl_list = ", ".join(f'"{self._to_rspamd_pattern(e)}"' for e in bl)
                out.append(f"""\
{safe}_blacklist {{
  rcpt_domain = ["{domain}"];
  from = [{bl_list}];
  priority = 20;
  apply {{
    actions {{
      "add header" = 0.1;
      greylist = 0.1;
      reject = 0.1;
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

    # ─── API pública ──────────────────────────────────────────────────────

    def rebuild_from_db(self, mail_domains):
        """
        Regenera settings.conf desde la lista completa de MailDomain de la BD.
        Llamar siempre que cambie cualquier dominio de correo.
        """
        configs = []
        for md in mail_domains:
            configs.append({
                "domain":            md.domain_name,
                "tag_threshold":     md.spam_tag_threshold    or 6.0,
                "reject_threshold":  md.spam_reject_threshold or 15.0,
                "whitelist_entries": self._parse_entries(md.whitelist_senders),
                "blacklist_entries": self._parse_entries(md.blacklist_senders),
            })

        content = self._build_settings_conf(configs)
        self._write_settings_conf(content)
        self._reload_rspamd()

    def remove_domain(self, domain):
        """Elimina el bloque de settings de un dominio (rebuild_from_db lo hace automáticamente)"""
        # Al llamar rebuild_from_db sin ese dominio, ya no aparecerá en settings.conf
        pass

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

    def get_history(self, limit=200):
        """
        Historial reciente de Rspamd vía HTTP API.
        Requiere: echo 'secure_ip = ["127.0.0.1", "::1"];'
                  >> /etc/rspamd/local.d/worker-controller.inc
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
            if action == "reject":         stats["rejected"]   += 1
            elif action == "add header":   stats["tagged"]     += 1
            elif action == "greylist":     stats["greylisted"] += 1
            else:                          stats["clean"]      += 1
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
