"""
Despliegue Git por dominio (estilo Capistrano) para SVQPanel.

Layout en /home/{user}/web/{domain}/:
    public_html  ->  git/releases/{ts}-{sha7}   (symlink a la release activa)
    git/
      repo.git/            clon bare; hace fetch del remoto
      releases/{ts}-{sha7} cada despliegue es una carpeta inmutable
      shared/              .env y dirs persistentes entre releases

Claves del diseño:
  - nginx y el pool PHP-FPM apuntan a public_html y NO se tocan en cada deploy:
    el symlink absorbe el cambio de versión. Rollback = reapuntar el symlink.
  - web/{dominio} es root:root 750 (aislamiento Hestia: el usuario no entra en
    su propia carpeta de dominio). Por eso:
      · git clone/fetch/checkout y el symlink → como ROOT (operación de sistema,
        no ejecuta código del repo). Los ficheros quedan con owner del usuario.
      · el BUILD del cliente (composer/npm) → como el USUARIO sin privilegios.
        Una ACL de solo-traverse (u:user:--x) en web/{dominio} le deja entrar a
        su release sin poder listar el dir ni ver otras carpetas (verificado).
  - La clave privada del deploy key vive en ~/.ssh (0600 del usuario); root puede
    leerla para clonar repos privados. En BD solo la pública.

Reutiliza helpers de app_installer (_run, _gen_password, _empty_or_safe,
_chown_tree) para no duplicar el patrón de ejecución segura sin shell=True.
"""

import datetime
import logging
import os
import re
import secrets

from scripts.app_installer import (
    _run, _gen_password, _empty_or_safe, _chown_tree, _SYS_ENV,
)

logger = logging.getLogger(__name__)


class GitError(RuntimeError):
    """Error de usuario en una operación Git (repo inválido, dir no vacío…).

    El endpoint lo traduce a HTTP 4xx con el mensaje tal cual.
    """


# Validación de URL de repositorio: https://... o git@host:owner/repo(.git)
_RE_HTTPS = re.compile(r"^https://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+$")
_RE_SSH   = re.compile(r"^(ssh://)?[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[A-Za-z0-9._~/+-]+$")


def validate_repo_url(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > 500:
        raise GitError("URL de repositorio vacía o demasiado larga")
    if not (_RE_HTTPS.match(url) or _RE_SSH.match(url)):
        raise GitError("URL de repositorio no válida (usa https://… o git@host:owner/repo.git)")
    return url


def sanitize_ref(ref: str, default: str = "main") -> str:
    """Rama/ref seguro: sin espacios, sin '..', sin caracteres de shell."""
    ref = (ref or "").strip() or default
    if ".." in ref or any(c in ref for c in " \t\n;&|`$()<>"):
        raise GitError(f"Nombre de rama/ref no válido: {ref}")
    if not re.match(r"^[A-Za-z0-9._/-]+$", ref):
        raise GitError(f"Nombre de rama/ref no válido: {ref}")
    return ref


def gen_webhook_token() -> str:
    return secrets.token_urlsafe(32)


# ─────────────────────────────────────────────────────────────────────────────
# Rutas del layout
# ─────────────────────────────────────────────────────────────────────────────
def _domain_root(user: str, domain: str) -> str:
    return f"/home/{user}/web/{domain}"


def _public_html(user: str, domain: str) -> str:
    return f"{_domain_root(user, domain)}/public_html"


def _git_dir(user: str, domain: str) -> str:
    return f"{_domain_root(user, domain)}/git"


def _bare_repo(user: str, domain: str) -> str:
    return f"{_git_dir(user, domain)}/repo.git"


def _releases_dir(user: str, domain: str) -> str:
    return f"{_git_dir(user, domain)}/releases"


def _shared_dir(user: str, domain: str) -> str:
    return f"{_git_dir(user, domain)}/shared"


def _ssh_key_path(user: str, domain: str) -> str:
    return f"/home/{user}/.ssh/svqpanel_git_{domain}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────
def _git_env(user: str, domain: str) -> dict:
    """Entorno para que git use la deploy key del dominio si existe."""
    env = dict(_SYS_ENV)
    key = _ssh_key_path(user, domain)
    # -o accept-new: confía en el host la primera vez sin prompt interactivo.
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {key} -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new"
    )
    return env


def _run_user(cmd, user, cwd=None, timeout=600, env=None, input_text=None):
    """Comando como el usuario del dominio (sin privilegios). Para el BUILD del
    cliente: nunca corre código del repo como root."""
    full = ["sudo", "-u", user, "-H"]
    if env:
        for k in ("GIT_SSH_COMMAND",):
            if k in env:
                full += [f"{k}={env[k]}"]
    full += cmd
    import subprocess
    try:
        r = subprocess.run(full, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env or _SYS_ENV, input=input_text)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout tras {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def _run_root(cmd, cwd=None, timeout=600, env=None, input_text=None):
    """Comando como ROOT, con env opcional (para GIT_SSH_COMMAND). Operaciones de
    sistema: clone/fetch/checkout/symlink. NUNCA ejecuta código del repo cliente."""
    import subprocess
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env or _SYS_ENV, input=input_text)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout tras {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def _ensure_traverse_acl(user: str, domain: str):
    """
    Da al usuario permiso de SOLO ATRAVESAR (--x, sin lectura) el directorio
    web/{dominio}, que es root:root 750 por el aislamiento Hestia. Con esto el
    build del cliente (que corre como el usuario) puede 'cd' a su release y
    trabajar dentro, PERO sigue sin poder listar el dir del dominio ni acceder a
    otras carpetas root-only. Es el mínimo privilegio necesario; no relaja el
    aislamiento (verificado en el servidor de test).
    """
    _run(["setfacl", "-m", f"u:{user}:--x", _domain_root(user, domain)])


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _reload_php(domain: str):
    """Recarga el pool PHP-FPM del dominio (limpia opcache tras el deploy)."""
    try:
        from scripts import php_ini_manager as phpini
        ver = phpini.has_pool(domain)
        if ver:
            phpini._reload_fpm(ver)
    except Exception as e:
        logger.warning(f"No se pudo recargar PHP-FPM de {domain}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GitManager
# ─────────────────────────────────────────────────────────────────────────────
class GitManager:
    """
    Orquesta clone/deploy/rollback de un dominio.

    Modelo de seguridad (web/{dominio} es root:root 750 por el aislamiento Hestia;
    el usuario no puede entrar en su propia carpeta de dominio):
      - Operaciones de SISTEMA (clone, fetch, checkout, symlink, copia) → ROOT.
        No ejecutan código del repo; solo mueven ficheros. Los archivos quedan
        con owner del usuario (chown), nunca root.
      - BUILD del cliente (composer/npm/artisan) → SIEMPRE como el usuario sin
        privilegios. Una ACL de solo-traverse (u:{user}:--x) en web/{dominio} le
        deja 'cd' a su release sin poder listar el dir ni ver otras carpetas.
    """

    # ── Deploy key ──────────────────────────────────────────────────────────
    def gen_deploy_key(self, user: str, domain: str) -> str:
        """Genera (o regenera) un par ed25519 para el dominio. Devuelve la pública."""
        ssh_dir = f"/home/{user}/.ssh"
        key = _ssh_key_path(user, domain)
        _run(["install", "-d", "-m", "700", "-o", user, "-g", user, ssh_dir])
        # Borrar par previo si lo había (regeneración)
        _run(["rm", "-f", key, f"{key}.pub"])
        rc, _, err = _run_user(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q",
             "-C", f"svqpanel-git-{domain}", "-f", key],
            user=user,
        )
        if rc != 0:
            raise GitError(f"No se pudo generar la deploy key: {err}")
        _run(["chmod", "600", key])
        _run(["chown", f"{user}:{user}", key, f"{key}.pub"])
        try:
            with open(f"{key}.pub") as f:
                return f.read().strip()
        except OSError as e:
            raise GitError(f"No se pudo leer la clave pública: {e}")

    def deploy_key_pub(self, user: str, domain: str) -> str:
        pub = f"{_ssh_key_path(user, domain)}.pub"
        if os.path.isfile(pub):
            try:
                with open(pub) as f:
                    return f.read().strip()
            except OSError:
                pass
        return ""

    # ── Setup (clonado inicial) ───────────────────────────────────────────────
    def setup(self, user: str, domain: str, repo_url: str, branch: str = "main",
              build_commands: str = "", keep: int = 5) -> dict:
        """Activa git deploy: valida docroot vacío, clona bare, primer deploy."""
        repo_url = validate_repo_url(repo_url)
        branch = sanitize_ref(branch)

        domain_root = _domain_root(user, domain)
        public_html = _public_html(user, domain)
        if not os.path.isdir(domain_root):
            raise GitError(f"El dominio {domain} no existe en el servidor")

        # Si public_html ya es symlink (git ya activo) lo permitimos; si es dir
        # con datos, exigimos vacío (mismo criterio que el autoinstalador).
        if not os.path.islink(public_html):
            if not _empty_or_safe(public_html):
                raise GitError(
                    "public_html no está vacío. El despliegue Git requiere un dominio "
                    "limpio (haz backup y vacía public_html, o usa otro dominio)."
                )

        # ACL de solo-traverse para que el build (que corre como el usuario)
        # pueda 'cd' a su release dentro de web/{dominio} (root:root 750).
        _ensure_traverse_acl(user, domain)

        git_dir = _git_dir(user, domain)
        bare = _bare_repo(user, domain)
        for d in (git_dir, _releases_dir(user, domain), _shared_dir(user, domain)):
            _run(["install", "-d", "-m", "755", "-o", user, "-g", user, d])

        env = _git_env(user, domain)
        # Clon bare como ROOT (operación de sistema; web/{dominio} es root-owned).
        # No ejecuta código del repo, solo descarga objetos git. Usa la deploy key
        # del usuario (root puede leerla) para repos privados.
        _run(["rm", "-rf", bare])
        rc, _, err = _run_root(
            ["git", "clone", "--bare", "--branch", branch, repo_url, bare],
            env=env, timeout=900,
        )
        if rc != 0:
            # Reintento sin --branch (algunos repos usan master u otra rama default)
            rc2, _, err2 = _run_root(
                ["git", "clone", "--bare", repo_url, bare],
                env=env, timeout=900,
            )
            if rc2 != 0:
                raise GitError(f"No se pudo clonar el repositorio: {err or err2}")
        _chown_tree(bare, user)

        return self.deploy(user, domain, branch=branch,
                           build_commands=build_commands, keep=keep,
                           trigger="initial", _first=True)

    # ── Deploy (crear release y activarla) ──────────────────────────────────────
    def deploy(self, user: str, domain: str, branch: str = "main",
               build_commands: str = "", keep: int = 5,
               trigger: str = "manual", _first: bool = False) -> dict:
        """Hace fetch, crea una release nueva, ejecuta build y reapunta el symlink."""
        branch = sanitize_ref(branch)
        bare = _bare_repo(user, domain)
        if not os.path.isdir(bare):
            raise GitError("El despliegue Git no está configurado para este dominio")

        env = _git_env(user, domain)
        # Asegurar la ACL de traverse en cada deploy (idempotente; cubre dominios
        # cuyo git se configuró antes de existir esta ACL).
        _ensure_traverse_acl(user, domain)

        # 1) Traer cambios del remoto (como ROOT: operación de sistema)
        rc, _, err = _run_root(
            ["git", "--git-dir", bare, "fetch", "--prune", "origin",
             f"+refs/heads/{branch}:refs/heads/{branch}"],
            env=env, timeout=900,
        )
        if rc != 0:
            raise GitError(f"git fetch falló: {err}")

        # 2) Resolver el commit actual de la rama
        rc, sha, err = _run_root(["git", "--git-dir", bare, "rev-parse", branch], env=env)
        if rc != 0 or not sha:
            raise GitError(f"No se pudo resolver la rama {branch}: {err}")
        sha7 = sha[:7]
        rc, msg, _ = _run_root(
            ["git", "--git-dir", bare, "log", "-1", "--pretty=%s", branch], env=env)
        commit_msg = (msg or "")[:480]

        # 3) Crear la carpeta de release y hacer checkout del árbol (como ROOT).
        #    Si ya existe (dos deploys del mismo commit en el mismo segundo),
        #    añadimos un sufijo para no sobrescribir la release anterior.
        rel_name = f"{_timestamp()}-{sha7}"
        rels_dir = _releases_dir(user, domain)
        if os.path.exists(f"{rels_dir}/{rel_name}"):
            rel_name = f"{rel_name}-{secrets.token_hex(2)}"
        rel_dir = f"{rels_dir}/{rel_name}"
        _run(["install", "-d", "-m", "755", "-o", user, "-g", user, rel_dir])
        rc, _, err = _run_root(
            ["git", "--git-dir", bare, "--work-tree", rel_dir, "checkout", "-f", branch],
            env=env, timeout=600,
        )
        if rc != 0:
            _run(["rm", "-rf", rel_dir])
            raise GitError(f"git checkout falló: {err}")

        # 4) Symlink de shared/.env si existe (persistencia entre releases)
        shared_env = f"{_shared_dir(user, domain)}/.env"
        if os.path.isfile(shared_env):
            _run(["ln", "-sfn", shared_env, f"{rel_dir}/.env"])

        # Los archivos del repo quedan con owner del usuario (no root)
        _chown_tree(rel_dir, user)

        # 5) Ejecutar comandos de build COMO EL USUARIO sin privilegios (código
        #    del cliente: jamás como root). La ACL de traverse le deja entrar.
        build_log = ""
        ok_build = True
        if build_commands and build_commands.strip():
            # Cada línea es un comando; se ejecutan en secuencia con bash -lc.
            script = " && ".join(
                line.strip() for line in build_commands.splitlines() if line.strip()
            )
            rc, out, err = _run_user(
                ["bash", "-lc", script], user=user, cwd=rel_dir, timeout=900,
            )
            build_log = (out + ("\n" + err if err else ""))[-8000:]
            if rc != 0:
                ok_build = False

        if not ok_build:
            # Build falló: no activamos esta release (dejamos la activa intacta).
            # Borramos la release fallida para no acumular basura.
            _run(["rm", "-rf", rel_dir])
            raise GitError(
                f"El despliegue se clonó pero los comandos de build fallaron:\n{build_log[-1500:]}"
            )

        # 6) Reapuntar public_html → rel_dir de forma atómica (ln -sfn)
        self._activate_release(user, domain, rel_dir)

        # 7) Recargar PHP-FPM (limpia opcache) y podar releases viejas
        _reload_php(domain)
        self._prune_releases(user, domain, keep)

        return {
            "release_dir": rel_dir,
            "release_name": rel_name,
            "commit_sha": sha,
            "commit_msg": commit_msg,
            "branch": branch,
            "build_log": build_log,
            "trigger": trigger,
        }

    def _activate_release(self, user: str, domain: str, rel_dir: str):
        """public_html → rel_dir, atómico. Maneja el caso primer-deploy (dir real).

        El symlink se crea como ROOT: el directorio padre web/{dominio} es
        root-owned (lo crea create_domain como root), así que el usuario no puede
        escribir ahí. El enlace queda con owner del usuario por coherencia (nginx
        solo necesita poder seguirlo, no importa el owner del symlink).
        """
        public_html = _public_html(user, domain)
        if os.path.isdir(public_html) and not os.path.islink(public_html):
            # Primer deploy: public_html era una carpeta (vacía/trivial). La
            # quitamos para poder ponerla como symlink.
            _run(["rm", "-rf", public_html])
        # ln -s vía un tmp + mv -T para que el reemplazo sea atómico (como root)
        tmp_link = f"{public_html}.tmp.{secrets.token_hex(4)}"
        rc, _, err = _run(["ln", "-s", rel_dir, tmp_link])
        if rc != 0:
            raise GitError(f"No se pudo crear el symlink de la release: {err}")
        rc, _, err = _run(["mv", "-Tf", tmp_link, public_html])
        if rc != 0:
            _run(["rm", "-f", tmp_link])
            raise GitError(f"No se pudo activar la release (symlink): {err}")
        # owner del symlink = usuario (no afecta a nginx, pero mantiene coherencia)
        _run(["chown", "-h", f"{user}:{user}", public_html])

    def _prune_releases(self, user: str, domain: str, keep: int):
        """Conserva las `keep` releases más recientes; borra el resto."""
        try:
            keep = max(1, int(keep or 5))
        except (TypeError, ValueError):
            keep = 5
        rels = self.list_releases(user, domain)
        active = self.active_release(user, domain)
        # Ordenadas desc por nombre (timestamp). No borrar la activa.
        to_remove = [r for r in rels[keep:] if r["dir"] != active]
        for r in to_remove:
            _run(["rm", "-rf", r["dir"]])

    # ── Rollback ────────────────────────────────────────────────────────────────
    def rollback(self, user: str, domain: str, release_name: str) -> dict:
        """Reapunta public_html a una release existente."""
        if "/" in release_name or ".." in release_name:
            raise GitError("Nombre de release no válido")
        rel_dir = f"{_releases_dir(user, domain)}/{release_name}"
        if not os.path.isdir(rel_dir):
            raise GitError("Esa versión ya no existe en el servidor")
        self._activate_release(user, domain, rel_dir)
        _reload_php(domain)
        return {"release_dir": rel_dir, "release_name": release_name}

    # ── Lectura de estado ─────────────────────────────────────────────────────
    def list_releases(self, user: str, domain: str) -> list:
        """Releases existentes, más reciente primero."""
        rdir = _releases_dir(user, domain)
        if not os.path.isdir(rdir):
            return []
        out = []
        for name in sorted(os.listdir(rdir), reverse=True):
            full = os.path.join(rdir, name)
            if os.path.isdir(full):
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = 0
                out.append({"name": name, "dir": full, "mtime": mtime})
        return out

    def active_release(self, user: str, domain: str) -> str:
        """Ruta de la release a la que apunta public_html (o '')."""
        public_html = _public_html(user, domain)
        if os.path.islink(public_html):
            try:
                return os.path.realpath(public_html)
            except OSError:
                return ""
        return ""

    def status(self, user: str, domain: str) -> dict:
        """Estado de disco (symlink + releases) para la UI."""
        active = self.active_release(user, domain)
        rels = self.list_releases(user, domain)
        active_name = ""
        for r in rels:
            if r["dir"] == active:
                active_name = r["name"]
                break
        return {
            "public_html_is_symlink": os.path.islink(_public_html(user, domain)),
            "active_release": active_name,
            "releases": [r["name"] for r in rels],
            "deploy_key_pub": self.deploy_key_pub(user, domain),
        }

    # ── Desactivar ──────────────────────────────────────────────────────────────
    def disable(self, user: str, domain: str, restore_files: bool = True) -> dict:
        """
        Desactiva git deploy. Si restore_files: convierte public_html (symlink)
        en una copia real de la release activa, para que el sitio siga sirviendo
        sin depender de git/. Deja git/ intacto (el endpoint decide si borrarlo).
        """
        public_html = _public_html(user, domain)
        if restore_files and os.path.islink(public_html):
            active = self.active_release(user, domain)
            if active and os.path.isdir(active):
                # Copia como root (web/{dominio} es root-owned); luego owner=usuario.
                tmp = f"{public_html}.real.{secrets.token_hex(4)}"
                _run(["install", "-d", "-m", "755", "-o", user, "-g", user, tmp])
                _run(["bash", "-c", f"shopt -s dotglob && cp -a {active}/. {tmp}/"])
                _run(["rm", "-f", public_html])
                _run(["mv", "-Tf", tmp, public_html])
                _chown_tree(public_html, user)
        return {"disabled": True}
