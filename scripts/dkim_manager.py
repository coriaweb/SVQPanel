"""
DKIM Manager — generación y gestión de claves DKIM por dominio via Rspamd.

Ficheros gestionados:
  /etc/rspamd/dkim/{domain}.{selector}.key  → clave privada RSA 2048
  /etc/rspamd/dkim/selectors.map            → domain → selector

Registro DNS a crear por cada dominio:
  {selector}._domainkey.{domain}  IN  TXT  "v=DKIM1; k=rsa; p={public_key}"
"""

import os
import logging
from .base import SystemManager

logger = logging.getLogger(__name__)


class DkimManager(SystemManager):
    """Gestiona claves DKIM para firma de correo saliente via Rspamd"""

    DKIM_DIR     = "/etc/rspamd/dkim"
    SELECTOR_MAP = "/etc/rspamd/dkim/selectors.map"

    # Usuarios posibles del proceso Rspamd (varía según versión/distro)
    _RSPAMD_USERS = ["_rspamd", "rspamd"]

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────

    def generate_key(self, domain, selector="mail"):
        """
        Genera un par de claves RSA 2048 para DKIM:
        1. Genera clave privada en /etc/rspamd/dkim/{domain}.{selector}.key
        2. Extrae la clave pública en formato PEM
        3. Actualiza selectors.map
        4. Recarga Rspamd
        Devuelve dict con rutas y el registro TXT para el DNS.
        """
        os.makedirs(self.DKIM_DIR, exist_ok=True)
        key_path = self._key_path(domain, selector)

        # Generar clave privada RSA 2048
        self.execute_command([
            "openssl", "genrsa", "-out", key_path, "2048"
        ])
        os.chmod(key_path, 0o600)
        self._chown_rspamd(key_path)
        logger.info(f"Clave DKIM generada: {key_path}")

        # Extraer clave pública en PEM
        code, pub_pem, err = self.execute_command([
            "openssl", "rsa", "-in", key_path, "-pubout", "-outform", "PEM"
        ])
        if code != 0:
            raise RuntimeError(f"Error extrayendo clave pública: {err}")

        public_key_b64 = self._pem_to_b64(pub_pem)
        dns_value      = f"v=DKIM1; k=rsa; p={public_key_b64}"
        dns_name       = f"{selector}._domainkey.{domain}"

        # Actualizar mapa de selectores de Rspamd
        self._update_selector_map(domain, selector, remove=False)

        # Recargar Rspamd para que aplique la nueva clave
        self._reload_rspamd()

        return {
            "success":         True,
            "selector":        selector,
            "key_path":        key_path,
            "public_key_pem":  pub_pem.strip(),
            "public_key_b64":  public_key_b64,
            "dns_record_name": dns_name,
            "dns_record_value": dns_value,
        }

    def remove_key(self, domain, selector="mail"):
        """
        Elimina la clave DKIM de un dominio:
        1. Borra el fichero de clave privada
        2. Elimina la entrada de selectors.map
        3. Recarga Rspamd
        """
        key_path = self._key_path(domain, selector)

        if os.path.exists(key_path):
            os.remove(key_path)
            logger.info(f"Clave DKIM eliminada: {key_path}")
        else:
            logger.warning(f"Clave DKIM no encontrada: {key_path}")

        self._update_selector_map(domain, selector, remove=True)
        self._reload_rspamd()

        return {"success": True}

    def get_key_info(self, domain, selector="mail"):
        """
        Devuelve información de la clave DKIM existente.
        Devuelve None si no existe la clave.
        """
        key_path = self._key_path(domain, selector)
        if not os.path.exists(key_path):
            return None

        code, pub_pem, err = self.execute_command([
            "openssl", "rsa", "-in", key_path, "-pubout", "-outform", "PEM"
        ], check=False)

        if code != 0:
            logger.warning(f"No se pudo leer la clave pública de {key_path}: {err}")
            return None

        public_key_b64 = self._pem_to_b64(pub_pem)
        dns_name       = f"{selector}._domainkey.{domain}"
        dns_value      = f"v=DKIM1; k=rsa; p={public_key_b64}"

        # Tamaño del fichero como indicador de que la clave existe
        key_size = os.path.getsize(key_path)

        return {
            "selector":        selector,
            "key_path":        key_path,
            "key_size_bytes":  key_size,
            "public_key_pem":  pub_pem.strip(),
            "public_key_b64":  public_key_b64,
            "dns_record_name": dns_name,
            "dns_record_value": dns_value,
        }

    def key_exists(self, domain, selector="mail"):
        """Comprueba si existe la clave privada para un dominio"""
        return os.path.exists(self._key_path(domain, selector))

    def dkim_available(self):
        """Comprueba si Rspamd está instalado (directorio DKIM accesible)"""
        return os.path.isdir(self.DKIM_DIR)

    # ─────────────────────────────────────────────────────────────────────
    # Internos
    # ─────────────────────────────────────────────────────────────────────

    def _key_path(self, domain, selector):
        return os.path.join(self.DKIM_DIR, f"{domain}.{selector}.key")

    def _chown_rspamd(self, path):
        """Cambia la propiedad al usuario de Rspamd (varía según distro)"""
        for user in self._RSPAMD_USERS:
            code, _, _ = self.execute_command(
                ["chown", f"{user}:{user}", path], check=False
            )
            if code == 0:
                return
        logger.warning(f"No se pudo cambiar propietario de {path} a rspamd/_rspamd")

    def _reload_rspamd(self):
        code, _, err = self.execute_command(
            ["systemctl", "reload-or-restart", "rspamd"], check=False
        )
        if code != 0:
            logger.warning(f"No se pudo recargar Rspamd: {err}")

    @staticmethod
    def _pem_to_b64(pem_str):
        """
        Convierte una clave pública PEM a base64 desnuda para el TXT de DNS.
        Elimina las líneas de cabecera/pie del PEM y une las líneas restantes.
        """
        lines = pem_str.strip().split("\n")
        b64_lines = [l for l in lines if not l.startswith("-----")]
        return "".join(b64_lines)

    def _read_selector_map(self):
        """Lee selectors.map → dict {domain: selector}"""
        entries = {}
        if not os.path.exists(self.SELECTOR_MAP):
            return entries
        with open(self.SELECTOR_MAP, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    entries[parts[0]] = parts[1]
        return entries

    def _update_selector_map(self, domain, selector, remove=False):
        """Añade, actualiza o elimina una entrada en selectors.map"""
        entries = self._read_selector_map()

        if remove:
            entries.pop(domain, None)
        else:
            entries[domain] = selector

        tmp = self.SELECTOR_MAP + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# SVQPanel — gestionado automáticamente, no editar manualmente\n")
            for d in sorted(entries):
                f.write(f"{d}\t{entries[d]}\n")
        os.replace(tmp, self.SELECTOR_MAP)
        logger.info(f"selectors.map actualizado: {domain} → "
                    f"{'eliminado' if remove else selector}")
