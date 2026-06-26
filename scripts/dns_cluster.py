"""
Orquestador del cluster DNS (master/slave) de SVQPanel.

Arquitectura:
    VPS PANEL ──(SSH)──► ns1 (master) ──(AXFR + TSIG)──► ns2 (slave)

El panel NO sirve DNS cuando hay cluster: empuja las zonas al master (ns1) por
SSH, y el master replica al slave (ns2) con el protocolo nativo de BIND (AXFR),
autenticado con una clave TSIG compartida.

Conexión saliente por `ssh`/`scp` (subprocess, como backup_manager.py — el
proyecto no usa paramiko). Autenticación por clave privada o, si se indica
contraseña, vía `sshpass` (disponible en el servidor real).

Todo comando remoto va como lista de args (sin shell con input de usuario); los
ficheros de config se generan localmente y se suben por scp.
"""

import logging
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _bin(name: str) -> str:
    """Resuelve la ruta absoluta de un binario del sistema.

    El servicio systemd del panel puede correr con un PATH reducido; buscamos
    primero en rutas estándar de Debian y luego en el PATH. Si no se encuentra,
    devolvemos el nombre tal cual (subprocess dará un error claro).
    """
    explicit = (
        f"/usr/bin/{name}", f"/bin/{name}",
        f"/usr/sbin/{name}", f"/sbin/{name}",
        f"/usr/local/bin/{name}",
    )
    for path in explicit:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which(name) or name

# ── Namespace por panel en los nodos DNS compartidos ───────────────────────────
# Varios paneles SVQPanel pueden compartir los mismos nodos (ns1/ns2). Para que
# no se pisen las configuraciones, CADA panel escribe bajo su propio namespace
# /etc/bind/svqpanel/{panel_id}/ y /var/lib/bind/svqpanel/{panel_id}/. Las rutas
# concretas las construye DNSCluster a partir de self.panel_id (ver propiedades).
#
# El named.conf.local del nodo NO contiene las zonas: incluye UNA sola vez (de
# forma idempotente) el fichero compartido _INCLUDES_CONF, que a su vez incluye
# (con globs) los tsig.conf/zones.conf de TODOS los paneles.
REMOTE_BIND_DIR      = "/etc/bind"                 # raíz BIND del nodo
REMOTE_BIND_ETC_BASE = "/etc/bind/svqpanel"       # raíz común (un subdir por panel)
REMOTE_BIND_VAR_BASE = "/var/lib/bind/svqpanel"   # raíz común escribible por named
REMOTE_NAMED_LOCAL   = "/etc/bind/named.conf.local"
REMOTE_INCLUDES_CONF = f"{REMOTE_BIND_ETC_BASE}/_includes.conf"
# Política DNSSEC de BIND 9.16+: 'default' = ECDSAP256SHA256, CSK, rotación e
# inline-signing automáticos. No requiere gestionar claves a mano.
DNSSEC_POLICY = "default"

# Contenido (reescribible) del _includes.conf compartido. Sus globs ya cubren a
# TODOS los paneles automáticamente, así que regenerarlo entero es seguro: no
# contiene nada específico de un panel concreto.
_INCLUDES_CONF_TEXT = (
    "// SVQPanel — includes de todos los paneles (no editar a mano)\n"
    f'include "{REMOTE_BIND_ETC_BASE}/*/tsig.conf";\n'
    f'include "{REMOTE_BIND_ETC_BASE}/*/zones.conf";\n'
)

DEFAULT_TSIG_ALGO = "hmac-sha256"

# Clave SSH dedicada del panel para hablar con los nodos DNS. Se genera una vez
# y se instala en cada nodo durante la provisión (usando la contraseña una sola
# vez). A partir de ahí TODO el SSH (provisión y push diario de zonas) usa la
# clave: no dependemos de contraseñas en memoria, que se pierden al reiniciar.
PANEL_SSH_KEY = "/opt/svqpanel/.ssh/dns_cluster_ed25519"


class DNSClusterError(RuntimeError):
    """Fallo de aprovisionamiento o sincronización del cluster."""


class DNSCluster:
    """
    Gestiona los nodos DNS remotos por SSH. Recibe dicts de nodo con:
      {hostname, ip, ssh_user, ssh_port, ssh_key_path, ssh_password?}

    `panel_id` es el namespace de ESTA instalación en los nodos compartidos: todas
    las rutas remotas (tsig, zones.conf, zone files, zonas firmadas, key-directory)
    cuelgan de él para que varios paneles compartan ns1/ns2 sin pisarse. Es
    obligatorio para las operaciones que tocan rutas por-panel (provision_*,
    push_zone, remove_zone); las puramente diagnósticas (test_connection,
    query_serial, dnssec_status…) no lo necesitan.
    """

    def __init__(self, panel_id: Optional[str] = None):
        self.panel_id = panel_id

    # ── Rutas por-panel (namespace) ──────────────────────────────────────────
    def _require_panel_id(self) -> str:
        if not self.panel_id:
            raise DNSClusterError(
                "DNSCluster sin panel_id: esta operación escribe rutas por-panel "
                "en los nodos. Instancia DNSCluster(panel_id=...) desde load_cluster()."
            )
        return self.panel_id

    @property
    def _base_etc(self) -> str:
        # /etc/bind/svqpanel/{panel_id} — config legible por named (root:bind)
        return f"{REMOTE_BIND_ETC_BASE}/{self._require_panel_id()}"

    @property
    def _base_var(self) -> str:
        # /var/lib/bind/svqpanel/{panel_id} — escribible por named (bind:bind):
        # zonas firmadas DNSSEC, zonas AXFR del slave y key-directory.
        return f"{REMOTE_BIND_VAR_BASE}/{self._require_panel_id()}"

    @property
    def _zones_conf(self) -> str:
        return f"{self._base_etc}/zones.conf"

    @property
    def _tsig_conf(self) -> str:
        return f"{self._base_etc}/tsig.conf"

    @property
    def _zones_dir(self) -> str:
        # Zone files NO firmados (estáticos, subidos por scp).
        return f"{self._base_etc}/zones"

    @property
    def _signed_dir(self) -> str:
        # Zonas firmadas DNSSEC (inline-signing las reescribe → dir escribible).
        return self._base_var

    @property
    def _keys_dir(self) -> str:
        # key-directory DNSSEC (named genera/rota las claves aquí).
        return self._base_var

    @property
    def _slave_zones_dir(self) -> str:
        # El slave escribe aquí las zonas recibidas por AXFR.
        return self._base_var

    # ── SSH helpers ──────────────────────────────────────────────────────────
    def _ssh_base(self, node: Dict) -> List[str]:
        """Construye el prefijo ssh para un nodo. Soporta clave o contraseña."""
        opts = [
            "-p", str(node.get("ssh_port", 22)),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes" if node.get("ssh_key_path") else "BatchMode=no",
            "-o", "ConnectTimeout=15",
        ]
        key = node.get("ssh_key_path")
        if key:
            opts += ["-i", key]
        target = f'{node.get("ssh_user", "root")}@{node["ip"]}'

        if node.get("ssh_password") and not key:
            # sshpass -e lee la contraseña de la variable de entorno SSHPASS
            return ["sshpass", "-e", "ssh"] + opts + [target]
        return ["ssh"] + opts + [target]

    def _scp_base(self, node: Dict, local: str, remote: str) -> List[str]:
        opts = [
            "-P", str(node.get("ssh_port", 22)),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=15",
        ]
        key = node.get("ssh_key_path")
        if key:
            opts += ["-i", key]
        target = f'{node.get("ssh_user", "root")}@{node["ip"]}:{remote}'
        if node.get("ssh_password") and not key:
            return ["sshpass", "-e", "scp"] + opts + [local, target]
        return ["scp"] + opts + [local, target]

    def _env_for(self, node: Dict) -> dict:
        env = os.environ.copy()
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        if node.get("ssh_password") and not node.get("ssh_key_path"):
            env["SSHPASS"] = node["ssh_password"]
        return env

    def _run_remote(self, node: Dict, remote_cmd: str, timeout: int = 120
                    ) -> Tuple[int, str, str]:
        """
        Ejecuta un comando en el nodo. `remote_cmd` se ejecuta con `bash -c` en
        el remoto; lo pasamos como UN argumento (ssh lo entrega al shell remoto).
        No interpolamos input de usuario sin sanear: los valores variables
        (hostnames/IPs) se validan en la capa de endpoints.
        """
        cmd = self._ssh_base(node) + ["bash", "-c", shlex.quote(remote_cmd)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, env=self._env_for(node))
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"timeout tras {timeout}s conectando a {node['ip']}"
        except Exception as e:
            return -1, "", str(e)

    def _upload(self, node: Dict, content: str, remote_path: str,
                timeout: int = 60) -> Tuple[int, str, str]:
        """Sube `content` a remote_path vía un fichero temporal local + scp."""
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".svq")
        try:
            tmp.write(content)
            tmp.close()
            cmd = self._scp_base(node, tmp.name, remote_path)
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, env=self._env_for(node))
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"timeout subiendo a {node['ip']}"
        except Exception as e:
            return -1, "", str(e)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    # ── Clave SSH del panel ────────────────────────────────────────────────────
    def ensure_panel_key(self) -> str:
        """Genera (si no existe) la clave SSH dedicada del panel. Devuelve la ruta."""
        if not os.path.exists(PANEL_SSH_KEY):
            os.makedirs(os.path.dirname(PANEL_SSH_KEY), mode=0o700, exist_ok=True)
            subprocess.run(
                [_bin("ssh-keygen"), "-t", "ed25519", "-N", "", "-f", PANEL_SSH_KEY,
                 "-C", "svqpanel-dns-cluster"],
                capture_output=True, text=True, timeout=30,
            )
        return PANEL_SSH_KEY

    def install_panel_key(self, node: Dict) -> Tuple[bool, str]:
        """
        Instala la clave pública del panel en authorized_keys del nodo, usando la
        contraseña del nodo UNA vez. Tras esto, el nodo es accesible por clave.
        Idempotente (no duplica la clave).
        """
        self.ensure_panel_key()
        try:
            with open(PANEL_SSH_KEY + ".pub") as f:
                pubkey = f.read().strip()
        except OSError as e:
            return False, f"no se pudo leer la clave pública: {e}"

        # Append idempotente a authorized_keys (vía contraseña)
        remote = (
            "umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
            f"grep -qxF {shlex.quote(pubkey)} ~/.ssh/authorized_keys || "
            f"echo {shlex.quote(pubkey)} >> ~/.ssh/authorized_keys"
        )
        # Forzamos uso de contraseña (sin clave) para esta instalación inicial
        node_pw = dict(node)
        node_pw["ssh_key_path"] = None
        cmd = self._ssh_base(node_pw) + ["bash", "-c", shlex.quote(remote)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=30, env=self._env_for(node_pw))
            if r.returncode != 0:
                return False, r.stderr.strip() or "fallo instalando la clave"
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── Conexión / diagnóstico ─────────────────────────────────────────────────
    def test_connection(self, node: Dict) -> Dict:
        """Comprueba SSH + que el usuario pueda usar sudo/root. No cambia nada."""
        rc, out, err = self._run_remote(node, "id -u && uname -a", timeout=20)
        if rc != 0:
            return {"ok": False, "error": err or "no se pudo conectar por SSH"}
        lines = out.splitlines()
        uid = lines[0].strip() if lines else "?"
        if uid != "0":
            # Si no es root, verificar sudo no interactivo
            rc2, _, err2 = self._run_remote(node, "sudo -n true", timeout=20)
            if rc2 != 0:
                return {"ok": False,
                        "error": "el usuario SSH no es root ni tiene sudo sin contraseña"}
        return {"ok": True, "info": out}

    # ── TSIG ───────────────────────────────────────────────────────────────────
    def generate_tsig(self, key_name: str = None,
                      algo: str = DEFAULT_TSIG_ALGO) -> Dict[str, str]:
        """
        Genera una clave TSIG localmente (tsig-keygen del paquete bind9-utils,
        instalado en el VPS panel). Devuelve {name, algo, secret}.

        `key_name` debería ser único por panel (p. ej. svq-{panel_id}) para que
        varios paneles que compartan los mismos nodos no colisionen. Si no se
        indica, usamos el panel_id de la instancia o, en último término, un
        nombre derivado de bytes aleatorios.
        """
        if not key_name:
            key_name = f"svq-{self.panel_id}" if self.panel_id else f"svq-{secrets.token_hex(4)}"
        try:
            r = subprocess.run(["tsig-keygen", "-a", algo, key_name],
                              capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and "secret" in r.stdout:
                secret = ""
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("secret"):
                        # secret "BASE64==";
                        secret = line.split('"')[1]
                        break
                if secret:
                    return {"name": key_name, "algo": algo, "secret": secret}
        except Exception as e:
            logger.warning(f"tsig-keygen no disponible ({e}); usando fallback")
        # Fallback: 32 bytes aleatorios en base64 (válido para hmac-sha256)
        import base64
        secret = base64.b64encode(secrets.token_bytes(32)).decode()
        return {"name": key_name, "algo": algo, "secret": secret}

    def _tsig_conf_text(self, tsig: Dict[str, str]) -> str:
        return (
            f'key "{tsig["name"]}" {{\n'
            f'    algorithm {tsig["algo"]};\n'
            f'    secret "{tsig["secret"]}";\n'
            f'}};\n'
        )

    # ── Generación de config BIND ──────────────────────────────────────────────
    def master_zone_file(self, domain: str, dnssec: bool = False) -> str:
        """Ruta (por-panel) del zone file en el master según esté firmada o no."""
        base = self._signed_dir if dnssec else self._zones_dir
        return f"{base}/db.{domain}"

    def _master_zone_block(self, domain: str, slave_ip: str, tsig_name: str,
                           dnssec: bool = False) -> str:
        """
        Bloque zone master con transferencia/notify al slave (TSIG). Si dnssec,
        añade dnssec-policy + inline-signing + key-directory: BIND 9.16+ genera
        claves, firma la zona y la mantiene firmada automáticamente. El fichero
        debe estar en un dir escribible por named (/var/lib/bind).
        """
        block = (
            f'zone "{domain}" IN {{\n'
            f'    type master;\n'
            f'    file "{self.master_zone_file(domain, dnssec)}";\n'
            f'    allow-transfer {{ key {tsig_name}; }};\n'
            f'    also-notify {{ {slave_ip} key {tsig_name}; }};\n'
            f'    notify yes;\n'
        )
        if dnssec:
            block += (
                f'    dnssec-policy {DNSSEC_POLICY};\n'
                f'    inline-signing yes;\n'
                f'    key-directory "{self._keys_dir}";\n'
            )
        block += '};\n\n'
        return block

    def _slave_zone_block(self, domain: str, master_ip: str, tsig_name: str) -> str:
        return (
            f'zone "{domain}" IN {{\n'
            f'    type slave;\n'
            f'    file "{self._slave_zones_dir}/db.{domain}";\n'
            f'    masters {{ {master_ip} key {tsig_name}; }};\n'
            f'    allow-notify {{ {master_ip}; }};\n'
            f'}};\n\n'
        )

    # ── Aprovisionamiento ────────────────────────────────────────────────────
    def _ensure_bind_installed(self, node: Dict) -> Tuple[bool, str]:
        """Instala bind9+dnsutils y crea el namespace por-panel. Idempotente."""
        sudo = "" if node.get("ssh_user", "root") == "root" else "sudo "
        base_etc = self._base_etc
        zones_dir = self._zones_dir
        base_var = self._base_var
        # Instalamos siempre dnsutils (dig) además de bind9/bind9-utils.
        # Creamos:
        #  - {base_etc}/zones   (root:bind 2775)  → config + zone files no firmados
        #  - {base_var}         (bind:bind)       → firmadas DNSSEC / AXFR / claves
        rc, out, err = self._run_remote(
            node,
            f"{sudo}bash -c '(command -v named >/dev/null 2>&1 && command -v dig >/dev/null 2>&1) || "
            f"(export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
            f"apt-get install -y -qq bind9 bind9-utils dnsutils)' && "
            f"{sudo}mkdir -p {zones_dir} && "
            f"{sudo}chown root:bind {REMOTE_BIND_ETC_BASE} {base_etc} {zones_dir} && "
            f"{sudo}chmod 2775 {REMOTE_BIND_ETC_BASE} {base_etc} {zones_dir} && "
            f"{sudo}touch {self._zones_conf} && "
            f"{sudo}mkdir -p {base_var} && "
            f"{sudo}chown bind:bind {base_var} && "
            f"{sudo}chmod 2775 {base_var}",
            timeout=300,
        )
        if rc != 0:
            return False, err or "fallo instalando bind9"
        # Asegurar el include compartido en named.conf.local (idempotente) y
        # (re)generar el _includes.conf con los globs de todos los paneles.
        ok, ierr = self._ensure_local_include(node)
        if not ok:
            return False, ierr
        return True, ""

    def _ensure_local_include(self, node: Dict) -> Tuple[bool, str]:
        """
        Hace que named.conf.local incluya UNA sola vez el _includes.conf compartido
        (append idempotente, sin reescribir el resto del fichero) y (re)genera el
        _includes.conf con los globs que cubren a TODOS los paneles.
        """
        # 1) (re)generar el _includes.conf compartido (seguro: solo globs)
        rc, _, err = self._upload(node, _INCLUDES_CONF_TEXT, REMOTE_INCLUDES_CONF)
        if rc != 0:
            return False, f"subiendo _includes.conf: {err}"
        sudo = "" if node.get("ssh_user", "root") == "root" else "sudo "
        include_line = f'include "{REMOTE_INCLUDES_CONF}";'
        # 2) Limpiar residuo del esquema GLOBAL antiguo (pre multi-panel): los
        #    includes y ficheros /etc/bind/svqpanel-tsig.conf y named.conf.zones
        #    colisionan con el namespace nuevo (p.ej. clave TSIG 'svq-xfer'
        #    duplicada → named no arranca). Es el caso "nodo ya usado".
        legacy_tsig  = f"{REMOTE_BIND_DIR}/svqpanel-tsig.conf"
        legacy_zones = f"{REMOTE_BIND_DIR}/named.conf.zones"
        # 3) append idempotente de la línea include en named.conf.local. NO se
        #    reescribe el fichero (eso borraría includes de otros paneles/sistema).
        rc, _, err = self._run_remote(
            node,
            f"{sudo}touch {REMOTE_NAMED_LOCAL} && "
            # quitar includes legacy globales (líneas exactas) si existieran
            f"{sudo}sed -i '\\#include \"{legacy_tsig}\";#d; \\#include \"{legacy_zones}\";#d' {REMOTE_NAMED_LOCAL} && "
            f"{sudo}rm -f {legacy_tsig} {legacy_zones} && "
            f"{sudo}chown root:bind {REMOTE_INCLUDES_CONF} && "
            f"{sudo}chmod 640 {REMOTE_INCLUDES_CONF} && "
            f"{sudo}grep -qF {shlex.quote(include_line)} {REMOTE_NAMED_LOCAL} || "
            f"echo {shlex.quote(include_line)} | {sudo}tee -a {REMOTE_NAMED_LOCAL} >/dev/null",
            timeout=30,
        )
        if rc != 0:
            return False, f"asegurando include en named.conf.local: {err}"
        return True, ""

    def _fix_bind_perms(self, node: Dict) -> None:
        """
        named corre como usuario 'bind': debe poder LEER el TSIG, named.conf.zones
        y los zone files. Tras subirlos por scp (root:root 0600) hay que ajustar
        propietario/permisos o named falla con 'permission denied'.
        """
        sudo = "" if node.get("ssh_user", "root") == "root" else "sudo "
        self._run_remote(
            node,
            f"{sudo}chown root:bind {self._tsig_conf} {self._zones_conf} && "
            f"{sudo}chmod 640 {self._tsig_conf} {self._zones_conf} && "
            f"{sudo}chown root:bind {self._zones_dir}/db.* 2>/dev/null; "
            f"{sudo}chmod 644 {self._zones_dir}/db.* 2>/dev/null; "
            # Zonas firmadas en {base_var}: bind debe poder reescribirlas
            # (inline-signing) y crear .jnl/.signed/claves → owner bind:bind.
            f"{sudo}chown bind:bind {self._signed_dir}/db.* 2>/dev/null; "
            f"{sudo}chmod 644 {self._signed_dir}/db.* 2>/dev/null; true",
            timeout=45,
        )

    def provision_master(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                         zones: List[Dict]) -> Dict:
        """
        Prepara ns1 como master: instala bind9, sube TSIG, named.conf.local,
        genera los bloques zone master para cada zona y sube los zone files.
        `zones` = [{domain, zone_text}].
        """
        ok, err = self._ensure_bind_installed(master)
        if not ok:
            raise DNSClusterError(f"master {master['ip']}: {err}")

        rc, _, err = self._upload(master, self._tsig_conf_text(tsig), self._tsig_conf)
        if rc != 0:
            raise DNSClusterError(f"master TSIG upload: {err}")

        # key-directory escribible por named (para DNSSEC) — idempotente. El
        # namespace por-panel ya lo crea _ensure_bind_installed; reforzamos owner.
        sudo0 = "" if master.get("ssh_user", "root") == "root" else "sudo "
        self._run_remote(master, f"{sudo0}mkdir -p {self._keys_dir} && "
                                 f"{sudo0}chown bind:bind {self._keys_dir}", timeout=30)

        # Construir named.conf.zones (bloques master) y subir cada zone file.
        # Las zonas firmadas van a /var/lib/bind (escribible para inline-signing);
        # las no firmadas a /etc/bind/zones (estáticas).
        zones_conf = "// SVQPanel zones (master) — no editar a mano\n\n"
        for z in zones:
            dnssec = bool(z.get("dnssec"))
            zones_conf += self._master_zone_block(z["domain"], slave["ip"],
                                                  tsig["name"], dnssec)
            rc, _, err = self._upload(master, z["zone_text"],
                                      self.master_zone_file(z["domain"], dnssec))
            if rc != 0:
                raise DNSClusterError(f"master zone {z['domain']}: {err}")
        rc, _, err = self._upload(master, zones_conf, self._zones_conf)
        if rc != 0:
            raise DNSClusterError(f"master named.conf.zones: {err}")

        self._fix_bind_perms(master)
        sudo = "" if master.get("ssh_user", "root") == "root" else "sudo "
        rc, out, err = self._run_remote(
            master, f"{sudo}named-checkconf && {sudo}systemctl restart named && "
                    f"{sudo}systemctl is-active named", timeout=60)
        if rc != 0 or "active" not in out:
            raise DNSClusterError(f"master reload named: {err or out}")
        return {"ok": True, "zones": len(zones)}

    def provision_slave(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                        domains: List[str]) -> Dict:
        """Prepara ns2 como slave: bind9, TSIG, bloques zone slave apuntando al master."""
        ok, err = self._ensure_bind_installed(slave)
        if not ok:
            raise DNSClusterError(f"slave {slave['ip']}: {err}")

        rc, _, err = self._upload(slave, self._tsig_conf_text(tsig), self._tsig_conf)
        if rc != 0:
            raise DNSClusterError(f"slave TSIG upload: {err}")

        zones_conf = "// SVQPanel zones (slave) — no editar a mano\n\n"
        for domain in domains:
            zones_conf += self._slave_zone_block(domain, master["ip"], tsig["name"])
        rc, _, err = self._upload(slave, zones_conf, self._zones_conf)
        if rc != 0:
            raise DNSClusterError(f"slave named.conf.zones: {err}")

        self._fix_bind_perms(slave)
        sudo = "" if slave.get("ssh_user", "root") == "root" else "sudo "
        # El slave ESCRIBE las zonas recibidas por AXFR bajo el namespace por-panel
        # en /var/lib/bind (escribible por named y permitido por AppArmor).
        # _ensure_bind_installed ya creó el dir; reforzamos owner y recargamos.
        rc, out, err = self._run_remote(
            slave, f"{sudo}mkdir -p {self._slave_zones_dir} && "
                   f"{sudo}chown bind:bind {self._slave_zones_dir} && "
                   f"{sudo}named-checkconf && {sudo}systemctl restart named && "
                   f"{sudo}systemctl is-active named", timeout=60)
        if rc != 0 or "active" not in out:
            raise DNSClusterError(f"slave reload named: {err or out}")
        return {"ok": True, "zones": len(domains)}

    def _master_zones_conf(self, all_zones: List[Dict], slave_ip: str,
                           tsig_name: str) -> str:
        """Regenera named.conf.zones del master. all_zones: [{domain, dnssec}]."""
        out = "// SVQPanel zones (master) — no editar a mano\n\n"
        for z in all_zones:
            out += self._master_zone_block(z["domain"], slave_ip, tsig_name,
                                           bool(z.get("dnssec")))
        return out

    def _slave_zones_conf(self, all_zones: List[Dict], master_ip: str,
                          tsig_name: str) -> str:
        out = "// SVQPanel zones (slave) — no editar a mano\n\n"
        for z in all_zones:
            out += self._slave_zone_block(z["domain"], master_ip, tsig_name)
        return out

    # ── Empuje de una zona concreta (alta/edición desde el panel) ──────────────
    def _check_zone_not_in_other_panel(self, master: Dict, domain: str, sudo: str) -> None:
        """Falla con un mensaje CLARO si `domain` ya está declarado en el
        zones.conf de OTRO panel del mismo master. Evita el conflicto de zona
        duplicada en BIND (named-checkconf fallaría con un error técnico)."""
        my_id = self._require_panel_id()
        # Buscar `zone "domain"` en los zones.conf de todos los paneles MENOS el
        # mío. grep -l lista los ficheros que casan; nos quedamos con el panel_id.
        dom_re = domain.replace(".", r"\.")
        cmd = (
            f'for f in {REMOTE_BIND_ETC_BASE}/*/zones.conf; do '
            f'  [ -e "$f" ] || continue; '
            f'  pid=$(basename $(dirname "$f")); '
            f'  [ "$pid" = "{my_id}" ] && continue; '
            f'  if {sudo}grep -Eq \'^[[:space:]]*zone[[:space:]]+"{dom_re}"\' "$f"; then '
            f'    echo "$pid"; fi; '
            f'done'
        )
        rc, out, _ = self._run_remote(master, cmd, timeout=30)
        other = (out or "").strip().splitlines()
        if other:
            raise DNSClusterError(
                f"El dominio «{domain}» ya está gestionado por otro panel "
                f"(id: {other[0]}) en este cluster DNS. Un cluster no puede "
                f"servir la misma zona desde dos paneles a la vez. Elimina la "
                f"zona en el otro panel antes de crearla aquí."
            )

    def push_zone(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                  domain: str, zone_text: str, all_zones: List[Dict],
                  dnssec: bool = False) -> Dict:
        """
        Empuja/actualiza una zona en el master y regenera named.conf.zones con
        TODAS las zonas activas. El master notifica al slave automáticamente.
        all_zones: [{domain, dnssec}] (incluye la que se empuja).
        """
        sudo = "" if master.get("ssh_user", "root") == "root" else "sudo "

        # PRECHECK: ¿este dominio ya está gestionado por OTRO panel en el mismo
        # cluster? Si así fuera, BIND tendría la zona declarada dos veces y el
        # named-checkconf fallaría con un error críptico. Mejor avisar claro AHORA
        # y no tocar nada.
        self._check_zone_not_in_other_panel(master, domain, sudo)

        # Detectar si el estado DNSSEC cambió: si ya existe el fichero de la ruta
        # contraria, es que veníamos del otro modo (on↔off).
        other_file = self.master_zone_file(domain, not dnssec)
        _, out_chk, _ = self._run_remote(master, f"test -e {other_file} && echo CHG || echo SAME")
        dnssec_changed = "CHG" in out_chk

        rc, _, err = self._upload(master, zone_text,
                                  self.master_zone_file(domain, dnssec))
        if rc != 0:
            raise DNSClusterError(f"push zone {domain}: {err}")

        # Limpiar TODOS los artefactos de la ruta contraria: fichero, journals
        # (.jnl/.jbk/.signed.jnl), zona firmada y CLAVES DNSSEC del dominio.
        # Si no, named arrastra firmas/seriales viejos al cambiar de modo.
        self._run_remote(
            master,
            f"{sudo}rm -f {other_file} {other_file}.jnl {other_file}.jbk "
            f"{other_file}.signed {other_file}.signed.jnl 2>/dev/null; "
            # claves del dominio (solo al volver a NO firmado; si firmamos las
            # genera named). Las dejamos si dnssec=True.
            + (f"{sudo}rm -f {self._keys_dir}/K{domain}.+*.key "
               f"{self._keys_dir}/K{domain}.+*.private "
               f"{self._keys_dir}/K{domain}.+*.state 2>/dev/null; " if not dnssec else "")
            + "true")

        zones_conf = self._master_zones_conf(all_zones, slave["ip"], tsig["name"])
        rc, _, err = self._upload(master, zones_conf, self._zones_conf)
        if rc != 0:
            raise DNSClusterError(f"push named.conf.zones: {err}")

        self._fix_bind_perms(master)
        rc, out, err = self._run_remote(
            master, f"{sudo}named-checkconf && {sudo}rndc reload", timeout=45)
        if rc != 0:
            raise DNSClusterError(f"rndc reload master: {err or out}")

        # Declarar la zona en el SLAVE: su named.conf.zones debe incluir cada zona
        # como 'type slave' para transferirla del master. Sin esto, una zona NUEVA
        # llega al master pero el slave nunca la conoce (no replica). Regeneramos
        # el zones.conf del slave con TODAS las zonas y lo recargamos.
        if slave and slave.get("ip") and slave.get("ip") != master.get("ip"):
            sudo_s = "" if slave.get("ssh_user", "root") == "root" else "sudo "
            slave_conf = self._slave_zones_conf(all_zones, master["ip"], tsig["name"])
            rc_s, _, err_s = self._upload(slave, slave_conf, self._zones_conf)
            if rc_s == 0:
                self._fix_bind_perms(slave)
                self._run_remote(
                    slave, f"{sudo_s}named-checkconf && {sudo_s}rndc reload", timeout=45)
            else:
                # No abortamos el push entero: el master ya tiene la zona. Pero
                # avisamos en el log (el slave quedará desfasado hasta el próximo).
                logger.warning(f"push_zone: no se pudo actualizar zones.conf del slave: {err_s}")

        # Si cambió el estado DNSSEC, el serial del master pudo bajar respecto al
        # que el slave ya tenía (inline-signing lo había subido). El slave rechaza
        # AXFR con serial menor (anti-rollback) y se queda pegado. Forzamos una
        # retransferencia completa en el slave para que adopte la nueva zona.
        if dnssec_changed and slave and slave.get("ip") != master.get("ip"):
            sudo_s = "" if slave.get("ssh_user", "root") == "root" else "sudo "
            self._run_remote(slave, f"{sudo_s}rm -f {self._slave_zones_dir}/db.{domain} 2>/dev/null; "
                                    f"{sudo_s}rndc retransfer {shlex.quote(domain)} 2>/dev/null; true",
                             timeout=45)
        return {"ok": True}

    def remove_zone(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                    domain: str, all_zones: List[Dict]) -> Dict:
        """Elimina una zona del master y del slave; regenera named.conf.zones."""
        sudo_m = "" if master.get("ssh_user", "root") == "root" else "sudo "
        # Borrar el fichero esté firmado o no (+ artefactos de firma)
        for path in (self.master_zone_file(domain, False),
                     self.master_zone_file(domain, True)):
            self._run_remote(master, f"{sudo_m}rm -f {path} {path}.jnl {path}.signed 2>/dev/null; true")
        zones_conf = self._master_zones_conf(all_zones, slave["ip"], tsig["name"])
        self._upload(master, zones_conf, self._zones_conf)
        self._run_remote(master, f"{sudo_m}named-checkconf && {sudo_m}rndc reload")

        # Slave
        sudo_s = "" if slave.get("ssh_user", "root") == "root" else "sudo "
        self._run_remote(slave, f"{sudo_s}rm -f {self._slave_zones_dir}/db.{domain} 2>/dev/null; true")
        slave_conf = self._slave_zones_conf(all_zones, master["ip"], tsig["name"])
        self._upload(slave, slave_conf, self._zones_conf)
        self._run_remote(slave, f"{sudo_s}named-checkconf && {sudo_s}rndc reload")
        return {"ok": True}

    # ── Verificación de replicación ────────────────────────────────────────────
    def verify_replication(self, slave: Dict, domain: str) -> Dict:
        """
        Comprueba (vía SSH al slave, con dig local del slave) que la zona se ha
        transferido y el slave responde autoritativo para el SOA del dominio.
        """
        rc, out, err = self._run_remote(
            slave, f"dig +short @127.0.0.1 {shlex.quote(domain)} SOA", timeout=30)
        if rc != 0:
            return {"ok": False, "error": err or "dig falló en el slave"}
        if out.strip():
            return {"ok": True, "soa": out.strip()}
        return {"ok": False, "error": "el slave no responde SOA (zona no transferida aún)"}

    def query_serial(self, node: Dict, domain: str) -> Optional[int]:
        """
        Devuelve el serial SOA que el nodo sirve para `domain` (consultando su
        propio 127.0.0.1 vía SSH), o None si no responde / no es autoritativo.
        El serial es el 3er campo del SOA en 'dig +short'.
        """
        rc, out, _ = self._run_remote(
            node, f"dig +short +time=3 +tries=1 @127.0.0.1 {shlex.quote(domain)} SOA",
            timeout=20)
        if rc != 0 or not out.strip():
            return None
        parts = out.strip().split()
        # formato: "ns1.host. hostmaster.dom. SERIAL refresh retry expire min"
        if len(parts) >= 3 and parts[2].isdigit():
            return int(parts[2])
        return None

    # ── DNSSEC ──────────────────────────────────────────────────────────────────
    def dnssec_status(self, master: Dict, domain: str) -> Dict:
        """
        ¿Está la zona firmada en el master? Comprueba que sirve DNSKEY y RRSIG.
        Devuelve {signed: bool, dnskeys: int}.
        """
        rc, out, _ = self._run_remote(
            master, f"dig +short +time=3 +tries=1 @127.0.0.1 {shlex.quote(domain)} DNSKEY",
            timeout=25)
        keys = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
        return {"signed": len(keys) > 0, "dnskeys": len(keys)}

    def get_ds_records(self, master: Dict, domain: str) -> List[str]:
        """
        Devuelve los registros DS (Delegation Signer) que el usuario debe subir
        a su REGISTRADOR. Se derivan de la DNSKEY KSK firmada.
        Usa `dnssec-dsfromkey -2` (SHA-256) sobre la DNSKEY que sirve named.
        """
        # Obtenemos la DNSKEY de la zona y derivamos el DS con dnssec-dsfromkey.
        # -f - lee del stdin un RRset en formato presentación.
        d = shlex.quote(domain)
        rc, out, err = self._run_remote(
            master,
            f"dig +noall +answer +time=3 +tries=1 @127.0.0.1 {d} DNSKEY "
            f"| dnssec-dsfromkey -2 -A -f - {d} 2>/dev/null",
            timeout=30)
        if rc != 0:
            return []
        # Cada línea: "domain. IN DS 12345 13 2 ABCDEF..."
        return [l.strip() for l in out.splitlines() if " DS " in l]

    def cluster_health(self, master: Dict, slave: Optional[Dict],
                       zones: List[Dict]) -> List[Dict]:
        """
        Para cada zona {domain, db_serial}, consulta el serial en ns1 y ns2 y
        compara con el de la BD del panel. Devuelve una fila por zona:
          {domain, db_serial, master_serial, slave_serial, status}
        status: 'ok' (todos coinciden) | 'desync' (algún serial difiere) |
                'master_down' | 'slave_down'.
        """
        rows = []
        for z in zones:
            domain = z["domain"]
            db_serial = z["db_serial"]
            ms = self.query_serial(master, domain) if master else None
            ss = self.query_serial(slave, domain) if slave else None

            if ms is None:
                status = "master_down"
            elif slave and ss is None:
                status = "slave_down"
            elif ms != db_serial or (slave and ss != ms):
                status = "desync"
            else:
                status = "ok"

            rows.append({
                "domain": domain,
                "db_serial": db_serial,
                "master_serial": ms,
                "slave_serial": ss,
                "status": status,
            })
        return rows


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de integración con la BD (usados por las rutas)
# ─────────────────────────────────────────────────────────────────────────────
def _node_dict(node_row) -> Dict:
    """Convierte un DnsNode ORM en el dict que consume DNSCluster."""
    return {
        "hostname":     node_row.hostname,
        "ip":           node_row.ip,
        "ssh_user":     node_row.ssh_user or "root",
        "ssh_port":     node_row.ssh_port or 22,
        "ssh_key_path": node_row.ssh_key_path or None,
    }


def load_cluster(db) -> Optional[Dict]:
    """
    Carga master+slave+tsig desde BD. Devuelve None si el cluster no está
    completo (no hay master). El panel sirve DNS local mientras esto sea None.
    {master, slave, tsig} con master/slave como dicts de DNSCluster.
    """
    from api.models.models_dns_node import DnsNode
    from api.models.models_settings import Settings

    master_row = db.query(DnsNode).filter(DnsNode.role == "master").first()
    if not master_row:
        return None
    slave_row = db.query(DnsNode).filter(DnsNode.role == "slave").first()

    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s or not s.dns_tsig_secret:
        return None

    # panel_id: namespace único y estable de esta instalación en los nodos. Si
    # aún no existe (instalación previa al cambio o recién creada), lo generamos
    # y persistimos. "p" + 8 hex = 9 chars, cabe holgado en VARCHAR(32).
    panel_id = s.dns_panel_id
    if not panel_id:
        panel_id = "p" + secrets.token_hex(4)
        s.dns_panel_id = panel_id
        db.commit()

    tsig = {
        # Por compatibilidad con clusters ya montados, respetamos el nombre
        # guardado. Solo cae al derivado del panel cuando no hay ninguno.
        "name":   s.dns_tsig_name or f"svq-{panel_id}",
        "algo":   s.dns_tsig_algo or DEFAULT_TSIG_ALGO,
        "secret": s.dns_tsig_secret,
    }
    return {
        "master":   _node_dict(master_row),
        "slave":    _node_dict(slave_row) if slave_row else None,
        "tsig":     tsig,
        "panel_id": panel_id,
    }


def resync_zone(db, domain: str) -> bool:
    """
    Reempuja UNA zona de la BD al cluster (master→slave). Úsalo para auto-curar
    una zona que quedó desfasada porque un push anterior falló (p. ej. timeout
    SSH puntual): la BD tiene el serial bueno pero los nameservers van atrás.
    Devuelve True si el push se intentó (cluster presente), False si no hay
    cluster. Las excepciones se propagan.
    """
    from api.models.models_dns import DnsZone, DnsRecord
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain).first()
    if not zone:
        return False
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    record_dicts = [
        {"record_type": r.record_type, "name": r.name,
         "content": r.content, "ttl": r.ttl, "priority": r.priority}
        for r in records
    ]
    from scripts.dns_manager import DNSManager, get_panel_nameservers
    panel_ns1, _ = get_panel_nameservers(db)
    soa_ns = zone.soa_ns or panel_ns1
    zone_text = DNSManager.render_zone(
        zone.domain_name, zone.serial, record_dicts,
        soa_ns=soa_ns, ttl=zone.ttl or 14400,
    )
    return push_zone_to_cluster(db, zone.domain_name, zone_text,
                                dnssec=bool(zone.dnssec_enabled))


def compute_cluster_health(db, auto_resync: bool = True) -> Optional[Dict]:
    """
    Calcula la salud del cluster comparando el serial de cada zona en la BD del
    panel con el que sirven ns1 y ns2. Devuelve None si no hay cluster.

    Si auto_resync=True y una zona está desfasada PORQUE la BD va por delante del
    master (db_serial > master_serial), reintenta empujar esa zona y recomprueba
    su estado: auto-cura desfases por fallos de push puntuales. NO toca zonas
    donde el master va por delante (caso anómalo que no debe pisar el panel).

    {
      "rows":    [ {domain, db_serial, master_serial, slave_serial, status}, … ],
      "summary": {total, ok, desync, master_down, slave_down},
      "all_ok":  bool,
    }
    """
    from api.models.models_dns import DnsZone
    cluster = load_cluster(db)
    if not cluster:
        return None

    zones = [
        {"domain": z.domain_name, "db_serial": z.serial}
        for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()  # noqa: E712
    ]
    cl = DNSCluster(panel_id=cluster["panel_id"])
    rows = cl.cluster_health(cluster["master"], cluster["slave"], zones)

    if auto_resync:
        for r in rows:
            ms = r["master_serial"]
            ss = r.get("slave_serial")
            # Casos recuperables con un re-push (push_zone reconfigura master Y
            # slave, así que cura ambos):
            #   a) BD por delante del master (push al master perdido).
            #   b) el slave va por detrás del master o NO tiene la zona (slave_serial
            #      None o < master): zona nueva que no se declaró en el slave.
            need = (
                r["status"] == "desync" and ms is not None and (
                    r["db_serial"] > ms or
                    ss is None or ss < ms
                )
            )
            if need:
                try:
                    if resync_zone(db, r["domain"]):
                        import logging, time
                        logging.getLogger(__name__).info(
                            f"auto-resync de zona desfasada: {r['domain']} "
                            f"(BD={r['db_serial']} > master={ms})")
                        # Recomprobar tras el push, con un par de reintentos: el
                        # slave tarda unos segundos en recibir el AXFR (NOTIFY).
                        for _ in range(3):
                            time.sleep(2)
                            new = cl.cluster_health(
                                cluster["master"], cluster["slave"],
                                [{"domain": r["domain"], "db_serial": r["db_serial"]}])
                            if new:
                                r.update(new[0])
                                if r["status"] == "ok":
                                    break
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(
                        f"auto-resync de {r['domain']} falló: {e}")

    summary = {"total": len(rows), "ok": 0, "desync": 0,
               "master_down": 0, "slave_down": 0}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "rows": rows,
        "summary": summary,
        "all_ok": summary["total"] > 0 and summary["ok"] == summary["total"],
    }


def all_zones_meta(db) -> List[Dict]:
    """Lista de zonas activas con su flag DNSSEC: [{domain, dnssec}]."""
    from api.models.models_dns import DnsZone
    return [
        {"domain": z.domain_name, "dnssec": bool(z.dnssec_enabled)}
        for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()  # noqa: E712
    ]


def push_zone_to_cluster(db, domain: str, zone_text: str,
                         dnssec: bool = False) -> bool:
    """
    Si hay cluster configurado, empuja la zona al master. Devuelve True si lo
    hizo, False si no hay cluster (el caller usa entonces el BIND local).
    Las excepciones se propagan para que la ruta las reporte.
    """
    cluster = load_cluster(db)
    if not cluster:
        return False
    cl = DNSCluster(panel_id=cluster["panel_id"])
    # El slave puede no estar dado de alta todavía; usamos su IP solo para
    # also-notify. Si no hay slave, also-notify queda con la IP del master (no
    # rompe; simplemente no notifica a nadie externo).
    slave = cluster["slave"] or cluster["master"]
    cl.push_zone(cluster["master"], slave, cluster["tsig"],
                 domain, zone_text, all_zones_meta(db), dnssec=dnssec)
    return True
