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
    GREYLIST_FILE   = "/etc/rspamd/local.d/greylist.conf"
    MULTIMAP_FILE   = "/etc/rspamd/local.d/multimap.conf"
    CONTROLLER_FILE = "/etc/rspamd/local.d/worker-controller.inc"
    RATELIMIT_FILE  = "/etc/rspamd/local.d/ratelimit.conf"
    RATELIMIT_LUA   = "/etc/rspamd/svqpanel_ratelimit.lua"
    MAPS_DIR        = "/etc/rspamd/maps/domains"
    # Mapas (formato hash) de límite de envío leídos por el Lua de ratelimit:
    #   user_ratelimit.map    → "info@dominio.com 200 / 1h"  (por buzón autenticado)
    #   domain_ratelimit.map  → "dominio.com 1000 / 1h"      (por dominio remitente)
    RATELIMIT_USER_MAP   = "/etc/rspamd/maps/user_ratelimit.map"
    RATELIMIT_DOMAIN_MAP = "/etc/rspamd/maps/domain_ratelimit.map"
    # Límite para el correo NO autenticado (PHP/localhost, p.ej. formularios web).
    # Clave = usuario del SISTEMA que inyecta el correo (envelope sender local
    # part). Cierra el agujero por el que un sitio hackeado enviaba sin límite.
    #   sysuser_ratelimit.map → "weblab94 200 / 1h"
    RATELIMIT_SYSUSER_MAP = "/etc/rspamd/maps/sysuser_ratelimit.map"
    # Límite por defecto del correo NO autenticado (PHP mail()/sendmail por
    # localhost). MUY bajo a propósito: mail() es solo un puente de cortesía, no
    # la vía recomendada. El cliente que necesite enviar correo de su web debe
    # configurar SMTP autenticado (mejor entregabilidad + sin este tope). Al
    # llegar al límite, el correo se rechaza → empuja al cliente a usar SMTP, y
    # de paso frena en seco a un sitio hackeado.
    DEFAULT_UNAUTH_LIMIT_HOUR = 10
    RSPAMD_API      = "http://127.0.0.1:11334"

    # Antivirus por dominio: ClamAV escanea todo (símbolo CLAM_VIRUS); el Lua
    # rechaza solo si el dominio del destinatario está en el mapa.
    ANTIVIRUS_LUA        = "/etc/rspamd/lua.local.d/svqpanel_antivirus.lua"
    ANTIVIRUS_DOMAIN_MAP = "/etc/rspamd/maps/antivirus_domains.map"
    CLAMD_SOCKET         = "/var/run/clamav/clamd.ctl"

    # Protección anti zip-bomb (Rspamd 4.1.1+): un adjunto comprimido con un
    # ratio de descompresión enorme (p.ej. 10 KB → varios GB) puede saturar el
    # escaneo. Subimos el peso de los símbolos del módulo `archives` (ratio bomba
    # y ejecutable dentro de archivo) para que se marquen con fuerza. Vía un .lua
    # en lua.local.d (rspamd lo carga solo), igual que el antivirus.
    ARCHIVE_LUA = "/etc/rspamd/lua.local.d/svqpanel_archive.lua"

    # Penaliza correo con cuerpo en alfabeto cirílico (spam de formularios web y
    # spam directo en ruso/ucraniano a negocios españoles, que nunca reciben
    # correo legítimo así). Va a Junk (peso 6), no rechazo (recuperable).
    CYRILLIC_LUA = "/etc/rspamd/lua.local.d/svqpanel_cyrillic.lua"

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

    def _global_actions(self):
        """Lee los umbrales GLOBALES del admin (actions.conf) o devuelve los
        defaults de Rspamd. Sirven de BASE: un dominio solo escribe su propio
        bloque de umbrales si DIFIERE de estos (así el ajuste global del admin
        aplica salvo donde el cliente personalice)."""
        base = {"add header": 6.0, "reject": 15.0, "greylist": 4.0}
        path = "/etc/rspamd/local.d/actions.conf"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    txt = f.read()
                for key in base:
                    m = re.search(rf'"{re.escape(key)}"\s*=\s*([\-\d.]+)', txt)
                    if m:
                        base[key] = float(m.group(1))
            except Exception as e:
                logger.warning(f"_global_actions: {e}")
        return base

    def _build_settings_conf(self, domain_configs):
        """
        Genera settings.conf con umbrales personalizados y whitelist.
        NOTA: local.d/settings.conf se inyecta dentro de settings{} automáticamente.

        Importante: el bloque de umbrales por dominio SOLO se escribe si difiere
        del global del admin (o si greylist/spam_to_junk están desactivados, que
        necesitan el override). Si coincide con el global, NO se escribe → el
        dominio hereda el actions.conf del admin (evita que el por-dominio pise
        el ajuste global cuando el cliente no ha personalizado nada).
        """
        out = ["# SVQPanel — Generado automáticamente. NO editar manualmente.\n"]
        g = self._global_actions()

        for cfg in domain_configs:
            domain = cfg["domain"]
            safe   = self._safe_name(domain)
            # None = sin personalizar → usar el global del admin (no diferirá →
            # no se escribe bloque, hereda actions.conf).
            tag    = float(cfg["tag_threshold"]) if cfg.get("tag_threshold") is not None else g["add header"]
            reject = float(cfg["reject_threshold"]) if cfg.get("reject_threshold") is not None else g["reject"]
            # greylist_enabled=False → umbral inalcanzable (999): ese dominio NO
            # hace greylisting (entrega inmediata). Los demás umbrales (marcar/
            # rechazar spam) NO cambian: el filtrado anti-spam sigue igual.
            greylist_off = not cfg.get("greylist_enabled", True)
            greylist = g["greylist"] if not greylist_off else 999.0
            # spam_to_junk desactivado → subir "add header" a 999: ese dominio NO
            # marca correos como spam (no añade X-Spam: Yes), así el Sieve global
            # no los mueve a Junk. El rechazo de spam claro (reject) se mantiene.
            junk_off = not cfg.get("spam_to_junk_enabled", True)
            if junk_off:
                tag = 999.0

            # ¿El dominio difiere del global del admin? Solo entonces escribimos
            # su bloque (si no, hereda el global y respeta el ajuste del admin).
            differs = (
                abs(tag - g["add header"]) > 0.01 or
                abs(reject - g["reject"]) > 0.01 or
                greylist_off or junk_off
            )
            if differs:
                out.append(f"""\
# ── {domain} ──
{safe}_thresholds {{
  rcpt_domain = ["{domain}"];
  priority = 5;
  apply {{
    actions {{
      "add header" = {tag:.1f};
      reject = {reject:.1f};
      greylist = {greylist:.1f};
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

    # ─── Greylisting global (servidor completo) ───────────────────────────────

    def set_global_greylisting(self, enabled: bool) -> dict:
        """Activa/desactiva el greylisting para TODO el servidor.

        enabled=True  → greylist.conf con 'enabled = true' (cada dominio puede
                        excluirse vía settings.conf greylist=999).
        enabled=False → 'enabled = false': nadie hace greylisting.
        """
        content = (
            "# SVQPanel — greylisting global. NO editar manualmente.\n"
            f"enabled = {'true' if enabled else 'false'};\n"
        )
        tmp = self.GREYLIST_FILE + ".tmp"
        os.makedirs(os.path.dirname(self.GREYLIST_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, self.GREYLIST_FILE)
        self._reload_rspamd()
        return {"success": True, "greylisting_enabled": enabled}

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

        # Reglas de contenido del admin (globales). Rspamd solo lee reglas de
        # multimap desde multimap.conf, por eso se inyectan aquí (no en un .conf
        # aparte, que se ignoraría).
        try:
            from scripts import rspamd_tuning
            admin_blocks = rspamd_tuning.build_admin_rules_blocks()
            if admin_blocks.strip():
                out.append("# ── Reglas globales del administrador ──\n")
                out.append(admin_blocks)
        except Exception as e:
            logger.warning(f"No se pudieron inyectar reglas del admin: {e}")

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
                # None = sin personalizar → hereda el umbral global del admin.
                "tag_threshold":     md.spam_tag_threshold,
                "reject_threshold":  md.spam_reject_threshold,
                "domain":            md.domain_name,
                "greylist_enabled":  bool(getattr(md, "greylist_enabled", True)),
                "spam_to_junk_enabled": bool(getattr(md, "spam_to_junk_enabled", True)),
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

    # ─── Rate-limit de envío (ratelimit module) ───────────────────────────────

    def _write_map(self, path: str, lines: list):
        """Escribe un fichero de mapa de Rspamd de forma atómica."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = "# SVQPanel — generado automáticamente. NO editar.\n" + \
                  "\n".join(lines) + ("\n" if lines else "")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, path)

    def _build_ratelimit_lua(self) -> str:
        """
        Script Lua (custom_keywords) que aplica el límite de envío leyendo el
        valor por clave de dos mapas hash: por buzón (usuario SASL) y por dominio
        del remitente autenticado. Solo actúa sobre correo autenticado (saliente).
        Cada función devuelve (clave_de_bucket, "N / 1h") o nil (sin límite).
        """
        return f"""-- SVQPanel — rate-limit de envío. Generado automáticamente. NO editar.
local custom_keywords = {{}}

local user_map = rspamd_config:add_map({{
  url = '{self.RATELIMIT_USER_MAP}',
  type = 'map',
  description = 'SVQPanel: límite de envío por buzón',
}})
local domain_map = rspamd_config:add_map({{
  url = '{self.RATELIMIT_DOMAIN_MAP}',
  type = 'map',
  description = 'SVQPanel: límite de envío por dominio',
}})
local sysuser_map = rspamd_config:add_map({{
  url = '{self.RATELIMIT_SYSUSER_MAP}',
  type = 'map',
  description = 'SVQPanel: límite de envío NO autenticado (PHP/localhost) por usuario de sistema',
}})

-- Convierte el valor del mapa ("N / 1h") en el bucket estructurado que espera
-- el módulo ratelimit moderno (Rspamd 3.x/4.x). Evita el warning "old style
-- rate bucket config" y es la forma soportada a futuro.
--   "50 / 1h" → {{ burst = 50, rate = '50 / 1h' }}
local function svq_bucket(limstr)
  if not limstr then return nil end
  local burst = tonumber(limstr:match('^%s*(%d+)'))
  if not burst then return nil end
  return {{ burst = burst, rate = limstr }}
end

-- Por buzón autenticado (login SASL == email completo)
custom_keywords.svq_user_send = function(task)
  local user = task:get_user()
  if not user then return end           -- sin auth → no es saliente de cliente
  local lim = user_map and user_map:get_key(user:lower())
  if lim then
    return 'svq_user_' .. user:lower(), svq_bucket(lim)
  end
end

-- Por dominio del remitente autenticado
custom_keywords.svq_domain_send = function(task)
  local user = task:get_user()
  if not user then return end
  local dom = user:match('@(.+)$')
  if not dom then return end
  local lim = domain_map and domain_map:get_key(dom:lower())
  if lim then
    return 'svq_domain_' .. dom:lower(), svq_bucket(lim)
  end
end

-- Correo NO autenticado inyectado en localhost (PHP mail(), sendmail): es el
-- que enviaría un sitio web hackeado. Lo identificamos por el USUARIO DEL
-- SISTEMA del envelope sender (p.ej. "weblab94@hostname" → "weblab94"), que
-- mapea 1:1 con la cuenta del cliente. Así el spam de un sitio comprometido
-- choca con el límite/hora del dueño en vez de salir sin tope.
custom_keywords.svq_sysuser_send = function(task)
  if task:get_user() then return end    -- autenticado → ya cubierto arriba
  local from = task:get_from('smtp')    -- envelope sender (MAIL FROM)
  if not from or not from[1] or not from[1].user then return end
  local sysuser = from[1].user:lower()  -- parte local antes de @
  local lim = sysuser_map and sysuser_map:get_key(sysuser)
  if lim then
    return 'svq_sysuser_' .. sysuser, svq_bucket(lim)
  end
end

return custom_keywords
"""

    def _build_ratelimit_conf(self) -> str:
        return f"""# SVQPanel — Rate-limit de envío saliente. NO editar manualmente.
# Los límites por clave los aporta el Lua (lee los mapas por buzón/dominio).
custom_keywords = "{self.RATELIMIT_LUA}";
"""

    @classmethod
    def _compute_ratelimit_lines(cls, mail_domains, domain_sysuser=None,
                                 unauth_sysusers=None):
        """Calcula las líneas de los 3 mapas de rate-limit. Función PURA (sin I/O,
        testeable). Devuelve (user_lines, domain_lines, sysuser_lines).

        - user_lines:    "buzon@dominio  N / 1h"  (por buzón autenticado)
        - domain_lines:  "dominio  N / 1h"        (por dominio autenticado)
        - sysuser_lines: "usuario_sistema N / 1h" (correo NO autenticado de PHP)
        """
        user_lines = []
        domain_lines = []
        sysuser_limit = {}
        # Base: todos los usuarios con web reciben el tope por defecto. Luego un
        # dominio de correo con send_limit menor puede bajarlo (nos quedamos con
        # el menor), nunca subirlo por encima del default.
        if unauth_sysusers:
            for su, lim in unauth_sysusers.items():
                sysuser_limit[su.lower()] = int(lim)
        for md in mail_domains:
            dlimit = int(getattr(md, "send_limit_hour", 0) or 0)
            if dlimit > 0:
                domain_lines.append(f"{md.domain_name.lower()} {dlimit} / 1h")
            for mb in getattr(md, "mailboxes", []) or []:
                mlimit = int(getattr(mb, "send_limit_hour", 0) or 0)
                if mlimit > 0:
                    addr = f"{mb.username}@{md.domain_name}".lower()
                    user_lines.append(f"{addr} {mlimit} / 1h")
            su = (domain_sysuser or {}).get(md.domain_name)
            if su:
                # Cap al DEFAULT: el correo de scripts web debe ser bajo aunque el
                # dominio tenga un límite autenticado alto. Menor de varios dominios.
                lim = min(dlimit, cls.DEFAULT_UNAUTH_LIMIT_HOUR) if dlimit > 0 \
                    else cls.DEFAULT_UNAUTH_LIMIT_HOUR
                prev = sysuser_limit.get(su.lower())
                sysuser_limit[su.lower()] = min(prev, lim) if prev else lim

        sysuser_lines = [f"{su} {lim} / 1h" for su, lim in sorted(sysuser_limit.items())]
        return user_lines, domain_lines, sysuser_lines

    def rebuild_ratelimit_from_db(self, mail_domains, reload=True,
                                  domain_sysuser=None, unauth_sysusers=None):
        """
        Regenera los mapas de rate-limit (por buzón, por dominio y por usuario de
        sistema para el correo no autenticado), el Lua y la config del módulo.

        mail_domains: MailDomain con sus mailboxes cargados.
        domain_sysuser: dict {dominio: usuario_sistema} para mapear el límite del
          dominio al correo no autenticado (PHP) que inyecta ese usuario.
        unauth_sysusers: dict {usuario_sistema: limite/h} explícito; si se pasa,
          tiene prioridad. Si no, se deriva de domain_sysuser + send_limit_hour
          del dominio (o el DEFAULT_UNAUTH_LIMIT_HOUR conservador).
        Formato de mapa hash: "clave  N / 1h".
        """
        user_lines, domain_lines, sysuser_lines = self._compute_ratelimit_lines(
            mail_domains, domain_sysuser=domain_sysuser, unauth_sysusers=unauth_sysusers)

        self._write_map(self.RATELIMIT_USER_MAP, user_lines)
        self._write_map(self.RATELIMIT_DOMAIN_MAP, domain_lines)
        self._write_map(self.RATELIMIT_SYSUSER_MAP, sysuser_lines)

        # Lua + conf (idempotentes)
        for path, content in (
            (self.RATELIMIT_LUA, self._build_ratelimit_lua()),
            (self.RATELIMIT_FILE, self._build_ratelimit_conf()),
        ):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                f.write(content)
            os.replace(tmp, path)

        if reload:
            self._reload_rspamd()

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

    # ─── Antivirus ClamAV por dominio ─────────────────────────────────────────
    def clamav_available(self) -> bool:
        """True si clamd está disponible (socket presente o servicio activo)."""
        if os.path.exists(self.CLAMD_SOCKET):
            return True
        try:
            r = subprocess.run(["systemctl", "is-active", "clamav-daemon"],
                               capture_output=True, text=True, timeout=4)
            return r.stdout.strip() == "active"
        except Exception:
            return False

    def _build_antivirus_lua(self) -> str:
        """Lua (postfilter) que rechaza el correo con virus SOLO si el dominio del
        destinatario está en el mapa. ClamAV ya añadió el símbolo CLAM_VIRUS.

        Carga automática: Rspamd hace dofile de /etc/rspamd/lua.local.d/*.lua.
        """
        return f"""-- SVQPanel — antivirus por dominio. Generado automáticamente. NO editar.
local av_map = rspamd_config:add_map({{
  url = '{self.ANTIVIRUS_DOMAIN_MAP}',
  type = 'set',
  description = 'SVQPanel: dominios con antivirus (rechazo) activado',
}})

rspamd_config:register_symbol({{
  name = 'SVQ_ANTIVIRUS_REJECT',
  type = 'postfilter',
  priority = 10,
  callback = function(task)
    if not av_map then return end
    -- Solo actúa si ClamAV marcó virus
    local sym = task:get_symbol('CLAM_VIRUS')
    if not sym then return end
    -- ¿Algún destinatario pertenece a un dominio con antivirus activado?
    local rcpts = task:get_recipients('smtp') or task:get_recipients('mime') or {{}}
    for _, r in ipairs(rcpts) do
      local dom = (r['domain'] or ''):lower()
      if dom ~= '' and av_map:get_key(dom) then
        local vname = 'desconocido'
        if sym[1] and sym[1]['options'] and sym[1]['options'][1] then
          vname = sym[1]['options'][1]
        end
        task:set_pre_result('reject', 'Mensaje rechazado: virus detectado (' .. vname .. ')')
        return
      end
    end
  end,
}})
"""

    def rebuild_antivirus_from_db(self, mail_domains, reload=True):
        """Reescribe el mapa de dominios con antivirus activado + el Lua, y recarga.

        mail_domains: lista de MailDomain. Escribe un dominio por línea (set map).
        """
        lines = []
        for md in mail_domains:
            if getattr(md, "antivirus_enabled", False):
                lines.append(md.domain_name.lower())
        self._write_map(self.ANTIVIRUS_DOMAIN_MAP, lines)

        # El Lua es idempotente; lo (re)escribimos siempre por si cambió.
        os.makedirs(os.path.dirname(self.ANTIVIRUS_LUA), exist_ok=True)
        tmp = self.ANTIVIRUS_LUA + ".tmp"
        with open(tmp, "w") as f:
            f.write(self._build_antivirus_lua())
        os.replace(tmp, self.ANTIVIRUS_LUA)

        if reload:
            self._reload_rspamd()

    # ─── Protección anti zip-bomb (Rspamd 4.1.1+) ─────────────────────────────
    def setup_archive_protection(self, reload: bool = True) -> dict:
        """Sube el peso de los símbolos del módulo `archives` para que un
        adjunto comprimido tipo zip-bomb (ratio de descompresión enorme) o con
        un ejecutable dentro se marque con fuerza. Idempotente.

        Símbolos de Rspamd ajustados:
          - UDF_COMPRESSION_500PLUS: ratio >= 500x (clásico zip-bomb).
          - SINGLE_FILE_ARCHIVE_WITH_EXE / EXE_IN_ARCHIVE: ejecutable empaquetado.
        """
        os.makedirs(os.path.dirname(self.ARCHIVE_LUA), exist_ok=True)
        tmp = self.ARCHIVE_LUA + ".tmp"
        with open(tmp, "w") as f:
            f.write(_ARCHIVE_LUA_CONTENT)
        os.replace(tmp, self.ARCHIVE_LUA)
        if reload:
            self._reload_rspamd()
        return {"success": True}

    def setup_cyrillic_protection(self, reload: bool = True) -> dict:
        """Marca como spam (→ Junk) el correo cuyo cuerpo está en cirílico. Pensado
        para el spam de formularios de contacto de webs españolas (y spam directo
        ruso). Peso 6 = va a Junk, no rechazo: si llegara algo legítimo en ruso,
        queda recuperable. Idempotente."""
        os.makedirs(os.path.dirname(self.CYRILLIC_LUA), exist_ok=True)
        tmp = self.CYRILLIC_LUA + ".tmp"
        with open(tmp, "w") as f:
            f.write(_CYRILLIC_LUA_CONTENT)
        os.replace(tmp, self.CYRILLIC_LUA)
        if reload:
            self._reload_rspamd()
        return {"success": True}


# Lua que reajusta el score de los símbolos de archivo. set_metric_symbol
# sobreescribe el peso por defecto sin tocar la lógica del módulo `archives`.
_ARCHIVE_LUA_CONTENT = """-- SVQPanel — protección anti zip-bomb (NO editar a mano).
-- Sube el peso de los símbolos del módulo `archives` para frenar adjuntos
-- comprimidos maliciosos (ratio de descompresión enorme o ejecutable dentro).
if rspamd_config.set_metric_symbol then
  -- Ratio de descompresión >= 500x: zip-bomb casi seguro.
  rspamd_config:set_metric_symbol({
    name = 'UDF_COMPRESSION_500PLUS', score = 6.0,
    description = 'Archivo con ratio de descompresión de bomba (>=500x)',
    group = 'svqpanel',
  })
  -- Ejecutable dentro de un archivo (vector típico de malware).
  rspamd_config:set_metric_symbol({
    name = 'SINGLE_FILE_ARCHIVE_WITH_EXE', score = 4.0,
    description = 'Archivo de un solo ejecutable (sospechoso)',
    group = 'svqpanel',
  })
  rspamd_config:set_metric_symbol({
    name = 'EXE_IN_ARCHIVE', score = 2.0,
    description = 'Ejecutable empaquetado dentro de un archivo',
    group = 'svqpanel',
  })
end
"""


# Lua que marca correo con cuerpo en cirílico (spam de formularios web ES y spam
# ruso directo). Cuenta caracteres del bloque cirílico básico U+0400–U+04FF, que
# en UTF-8 son byte prefijo 0xD0/0xD1 (\\208/\\209) + byte de continuación.
_CYRILLIC_LUA_CONTENT = r"""-- SVQPanel — penaliza correo con cuerpo en alfabeto CIRÍLICO. NO editar a mano.
-- Spam de formularios de contacto (y spam directo) en ruso/ucraniano a negocios
-- españoles, que nunca reciben correo legítimo así. Peso 6 → va a Junk (no
-- rechazo: si llega algo legítimo en ruso, queda recuperable).
local N = 'SVQPANEL_CYRILLIC_BODY'
local MIN_CYR = 15   -- nº mínimo de caracteres cirílicos para marcar

rspamd_config:register_symbol({
  name = N,
  score = 6.0,
  description = 'Cuerpo con texto en alfabeto cirílico (spam típico en webs ES)',
  group = 'svqpanel',
  callback = function(task)
    local parts = task:get_text_parts()
    if not parts then return false end
    for _, part in ipairs(parts) do
      local content = part:get_content()
      if content then
        local s = tostring(content)
        local count = 0
        for _ in s:gmatch('[\208\209][\128-\191]') do
          count = count + 1
          if count >= MIN_CYR then
            return true, 1.0, count .. ' chars'
          end
        end
      end
    end
    return false
  end,
})
"""
