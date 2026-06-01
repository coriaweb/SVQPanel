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
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Rutas estándar en los nodos Debian 12 (idénticas al VPS de test)
REMOTE_ZONES_DIR   = "/etc/bind/zones"           # master: ficheros estáticos (subidos por scp)
REMOTE_ZONES_CONF  = "/etc/bind/named.conf.zones"
REMOTE_NAMED_LOCAL = "/etc/bind/named.conf.local"
REMOTE_TSIG_CONF   = "/etc/bind/svqpanel-tsig.conf"
# El slave ESCRIBE las zonas recibidas por AXFR: deben ir a una ruta escribible
# por named y permitida por el perfil AppArmor de Debian (/var/lib/bind), no a
# /etc/bind (de solo lectura para named bajo AppArmor).
REMOTE_SLAVE_ZONES_DIR = "/var/lib/bind"

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
    """

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
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", PANEL_SSH_KEY,
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
    def generate_tsig(self, key_name: str = "svq-xfer",
                      algo: str = DEFAULT_TSIG_ALGO) -> Dict[str, str]:
        """
        Genera una clave TSIG localmente (tsig-keygen del paquete bind9-utils,
        instalado en el VPS panel). Devuelve {name, algo, secret}.
        """
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
    def _master_named_local(self, slave_ip: str, tsig_name: str) -> str:
        """named.conf.local del master: include TSIG + include de zonas."""
        return (
            "// Generado por SVQPanel — cluster DNS (master)\n"
            f'include "{REMOTE_TSIG_CONF}";\n'
            f'include "{REMOTE_ZONES_CONF}";\n'
        )

    def _master_zone_block(self, domain: str, slave_ip: str, tsig_name: str) -> str:
        """Bloque zone master con transferencia/notify al slave autenticada por TSIG."""
        return (
            f'zone "{domain}" IN {{\n'
            f'    type master;\n'
            f'    file "{REMOTE_ZONES_DIR}/db.{domain}";\n'
            f'    allow-transfer {{ key {tsig_name}; }};\n'
            f'    also-notify {{ {slave_ip} key {tsig_name}; }};\n'
            f'    notify yes;\n'
            f'}};\n\n'
        )

    def _slave_zone_block(self, domain: str, master_ip: str, tsig_name: str) -> str:
        return (
            f'zone "{domain}" IN {{\n'
            f'    type slave;\n'
            f'    file "{REMOTE_SLAVE_ZONES_DIR}/db.{domain}";\n'
            f'    masters {{ {master_ip} key {tsig_name}; }};\n'
            f'    allow-notify {{ {master_ip}; }};\n'
            f'}};\n\n'
        )

    def _slave_named_local(self, master_ip: str, tsig_name: str,
                           domains: List[str]) -> str:
        lines = [
            "// Generado por SVQPanel — cluster DNS (slave)\n",
            f'include "{REMOTE_TSIG_CONF}";\n',
            f'include "{REMOTE_ZONES_CONF}";\n',
        ]
        return "".join(lines)

    # ── Aprovisionamiento ────────────────────────────────────────────────────
    def _ensure_bind_installed(self, node: Dict) -> Tuple[bool, str]:
        """Instala bind9+dnsutils en el nodo si no está. Idempotente."""
        sudo = "" if node.get("ssh_user", "root") == "root" else "sudo "
        # Instalamos siempre dnsutils (dig) además de bind9/bind9-utils.
        rc, out, err = self._run_remote(
            node,
            f"{sudo}bash -c '(command -v named >/dev/null 2>&1 && command -v dig >/dev/null 2>&1) || "
            f"(export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && "
            f"apt-get install -y -qq bind9 bind9-utils dnsutils)' && "
            f"{sudo}mkdir -p {REMOTE_ZONES_DIR} && "
            f"{sudo}chown root:bind {REMOTE_ZONES_DIR} && "
            f"{sudo}chmod 2775 {REMOTE_ZONES_DIR} && "
            f"{sudo}touch {REMOTE_ZONES_CONF}",
            timeout=300,
        )
        if rc != 0:
            return False, err or "fallo instalando bind9"
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
            f"{sudo}chown root:bind {REMOTE_TSIG_CONF} {REMOTE_ZONES_CONF} && "
            f"{sudo}chmod 640 {REMOTE_TSIG_CONF} {REMOTE_ZONES_CONF} && "
            f"{sudo}chown root:bind {REMOTE_ZONES_DIR}/db.* 2>/dev/null; "
            f"{sudo}chmod 644 {REMOTE_ZONES_DIR}/db.* 2>/dev/null; true",
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

        rc, _, err = self._upload(master, self._tsig_conf_text(tsig), REMOTE_TSIG_CONF)
        if rc != 0:
            raise DNSClusterError(f"master TSIG upload: {err}")

        rc, _, err = self._upload(
            master, self._master_named_local(slave["ip"], tsig["name"]),
            REMOTE_NAMED_LOCAL)
        if rc != 0:
            raise DNSClusterError(f"master named.conf.local: {err}")

        # Construir named.conf.zones (bloques master) y subir cada zone file
        zones_conf = "// SVQPanel zones (master) — no editar a mano\n\n"
        for z in zones:
            zones_conf += self._master_zone_block(z["domain"], slave["ip"], tsig["name"])
            rc, _, err = self._upload(master, z["zone_text"],
                                      f"{REMOTE_ZONES_DIR}/db.{z['domain']}")
            if rc != 0:
                raise DNSClusterError(f"master zone {z['domain']}: {err}")
        rc, _, err = self._upload(master, zones_conf, REMOTE_ZONES_CONF)
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

        rc, _, err = self._upload(slave, self._tsig_conf_text(tsig), REMOTE_TSIG_CONF)
        if rc != 0:
            raise DNSClusterError(f"slave TSIG upload: {err}")

        rc, _, err = self._upload(
            slave, self._slave_named_local(master["ip"], tsig["name"], domains),
            REMOTE_NAMED_LOCAL)
        if rc != 0:
            raise DNSClusterError(f"slave named.conf.local: {err}")

        zones_conf = "// SVQPanel zones (slave) — no editar a mano\n\n"
        for domain in domains:
            zones_conf += self._slave_zone_block(domain, master["ip"], tsig["name"])
        rc, _, err = self._upload(slave, zones_conf, REMOTE_ZONES_CONF)
        if rc != 0:
            raise DNSClusterError(f"slave named.conf.zones: {err}")

        self._fix_bind_perms(slave)
        sudo = "" if slave.get("ssh_user", "root") == "root" else "sudo "
        # El slave ESCRIBE las zonas recibidas por AXFR en /var/lib/bind (ruta
        # escribible por named y permitida por AppArmor). Aseguramos que existe
        # y es de bind.
        rc, out, err = self._run_remote(
            slave, f"{sudo}mkdir -p {REMOTE_SLAVE_ZONES_DIR} && "
                   f"{sudo}chown bind:bind {REMOTE_SLAVE_ZONES_DIR} && "
                   f"{sudo}named-checkconf && {sudo}systemctl restart named && "
                   f"{sudo}systemctl is-active named", timeout=60)
        if rc != 0 or "active" not in out:
            raise DNSClusterError(f"slave reload named: {err or out}")
        return {"ok": True, "zones": len(domains)}

    # ── Empuje de una zona concreta (alta/edición desde el panel) ──────────────
    def push_zone(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                  domain: str, zone_text: str, all_domains: List[str]) -> Dict:
        """
        Empuja/actualiza una zona en el master y regenera named.conf.zones con
        TODAS las zonas activas. El master notifica al slave automáticamente.
        """
        rc, _, err = self._upload(master, zone_text,
                                  f"{REMOTE_ZONES_DIR}/db.{domain}")
        if rc != 0:
            raise DNSClusterError(f"push zone {domain}: {err}")

        zones_conf = "// SVQPanel zones (master) — no editar a mano\n\n"
        for d in all_domains:
            zones_conf += self._master_zone_block(d, slave["ip"], tsig["name"])
        rc, _, err = self._upload(master, zones_conf, REMOTE_ZONES_CONF)
        if rc != 0:
            raise DNSClusterError(f"push named.conf.zones: {err}")

        self._fix_bind_perms(master)
        sudo = "" if master.get("ssh_user", "root") == "root" else "sudo "
        rc, out, err = self._run_remote(
            master, f"{sudo}named-checkconf && {sudo}rndc reload", timeout=45)
        if rc != 0:
            raise DNSClusterError(f"rndc reload master: {err or out}")
        return {"ok": True}

    def remove_zone(self, master: Dict, slave: Dict, tsig: Dict[str, str],
                    domain: str, all_domains: List[str]) -> Dict:
        """Elimina una zona del master y del slave; regenera named.conf.zones."""
        sudo_m = "" if master.get("ssh_user", "root") == "root" else "sudo "
        self._run_remote(master, f"{sudo_m}rm -f {REMOTE_ZONES_DIR}/db.{domain}")
        zones_conf = "// SVQPanel zones (master) — no editar a mano\n\n"
        for d in all_domains:
            zones_conf += self._master_zone_block(d, slave["ip"], tsig["name"])
        self._upload(master, zones_conf, REMOTE_ZONES_CONF)
        self._run_remote(master, f"{sudo_m}named-checkconf && {sudo_m}rndc reload")

        # Slave
        sudo_s = "" if slave.get("ssh_user", "root") == "root" else "sudo "
        self._run_remote(slave, f"{sudo_s}rm -f {REMOTE_SLAVE_ZONES_DIR}/db.{domain}")
        slave_conf = "// SVQPanel zones (slave) — no editar a mano\n\n"
        for d in all_domains:
            slave_conf += self._slave_zone_block(d, master["ip"], tsig["name"])
        self._upload(slave, slave_conf, REMOTE_ZONES_CONF)
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
    tsig = {
        "name":   s.dns_tsig_name or "svq-xfer",
        "algo":   s.dns_tsig_algo or DEFAULT_TSIG_ALGO,
        "secret": s.dns_tsig_secret,
    }
    return {
        "master": _node_dict(master_row),
        "slave":  _node_dict(slave_row) if slave_row else None,
        "tsig":   tsig,
    }


def compute_cluster_health(db) -> Optional[Dict]:
    """
    Calcula la salud del cluster comparando el serial de cada zona en la BD del
    panel con el que sirven ns1 y ns2. Devuelve None si no hay cluster.

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
    cl = DNSCluster()
    rows = cl.cluster_health(cluster["master"], cluster["slave"], zones)

    summary = {"total": len(rows), "ok": 0, "desync": 0,
               "master_down": 0, "slave_down": 0}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {
        "rows": rows,
        "summary": summary,
        "all_ok": summary["total"] > 0 and summary["ok"] == summary["total"],
    }


def push_zone_to_cluster(db, domain: str, zone_text: str,
                         all_domains: List[str]) -> bool:
    """
    Si hay cluster configurado, empuja la zona al master. Devuelve True si lo
    hizo, False si no hay cluster (el caller usa entonces el BIND local).
    Las excepciones se propagan para que la ruta las reporte.
    """
    cluster = load_cluster(db)
    if not cluster:
        return False
    cl = DNSCluster()
    # El slave puede no estar dado de alta todavía; usamos su IP solo para
    # also-notify. Si no hay slave, also-notify queda con la IP del master (no
    # rompe; simplemente no notifica a nadie externo).
    slave = cluster["slave"] or cluster["master"]
    cl.push_zone(cluster["master"], slave, cluster["tsig"],
                 domain, zone_text, all_domains)
    return True
