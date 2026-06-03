"""
Rutas API para gestión de bases de datos MariaDB de clientes.

Arquitectura:
  - PostgreSQL (interno del panel): guarda metadata en tabla client_databases
  - MariaDB (para clientes): motor real donde se crean CREATE DATABASE / CREATE USER

Naming convention (como cPanel):
  username "juan", sufijo "wordpress"
    → db_name = "juan_wordpress"   (nombre real en MariaDB)
    → db_user = "juan_wordpress"   (usuario real en MariaDB)

Endpoints:
  GET    /api/databases              → listar BDs del usuario
  POST   /api/databases              → crear BD + usuario MariaDB
  GET    /api/databases/{id}         → obtener detalle
  PUT    /api/databases/{id}         → actualizar quota/dominio/estado
  DELETE /api/databases/{id}         → eliminar BD y usuario de MariaDB
  PUT    /api/databases/{id}/password → cambiar contraseña del usuario MariaDB
  GET    /api/databases/charsets     → listar charsets/collations disponibles
"""

import json
import os
import re
import secrets
import string
import hashlib
import subprocess
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from api.models.database import get_db
from api.models.models_client_db import ClientDatabase
from api.models.models_db_user import DatabaseUser
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.database_schemas import (
    DatabaseCreate, DatabaseUpdate, DatabaseChangePassword,
    DatabaseResponse, DatabaseCreateResponse,
    DatabasePasswordResetResponse, DatabaseListResponse,
    DatabaseUserCreate, DatabaseUserUpdate, DatabaseUserResponse,
)
from api.dependencies import get_current_user, require_admin

router = APIRouter()

# ── Configuración MariaDB desde .env ─────────────────────────────────────────
MARIADB_ENABLED        = os.getenv("MARIADB_ENABLED", "false").lower() == "true"
MARIADB_HOST           = os.getenv("MARIADB_HOST", "localhost")
MARIADB_PANEL_USER     = os.getenv("MARIADB_PANEL_USER", "svqpanel_admin")
MARIADB_PANEL_PASSWORD = os.getenv("MARIADB_PANEL_PASSWORD", "")

# Clave Fernet para cifrado reversible de contraseñas (phpMyAdmin autologin)
# Generada en install_mariadb.sh: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PANEL_ENCRYPTION_KEY = os.getenv("PANEL_ENCRYPTION_KEY", "")


# ── Helpers internos ─────────────────────────────────────────────────────────

def _check_mariadb_enabled():
    """Lanza 503 si MariaDB no está habilitado en este servidor."""
    if not MARIADB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "MariaDB no está habilitado en este servidor. "
                "Instala MariaDB y configura MARIADB_ENABLED=true en .env"
            )
        )


def _get_fernet():
    """
    Devuelve una instancia Fernet si PANEL_ENCRYPTION_KEY está configurada,
    o None si no hay clave (phpMyAdmin no configurado).
    """
    if not PANEL_ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(PANEL_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def _encrypt_password(password: str) -> Optional[str]:
    """Cifra con Fernet. Devuelve None si no hay clave configurada."""
    f = _get_fernet()
    if not f:
        return None
    return f.encrypt(password.encode()).decode()


def _decrypt_password(enc: str) -> Optional[str]:
    """Descifra con Fernet. Devuelve None si falla o no hay clave."""
    f = _get_fernet()
    if not f or not enc:
        return None
    try:
        return f.decrypt(enc.encode()).decode()
    except Exception:
        return None


def _mariadb_binary() -> str:
    """
    Devuelve la ruta completa al binario cliente de MariaDB/MySQL.
    Busca en rutas explícitas además del PATH del proceso (que en systemd
    puede ser más restrictivo que el PATH interactivo del usuario).
    """
    import shutil
    # Rutas explícitas primero (systemd puede tener PATH limitado)
    explicit_paths = [
        "/usr/bin/mariadb",
        "/usr/bin/mysql",
        "/usr/local/bin/mariadb",
        "/usr/local/bin/mysql",
        "/opt/mariadb/bin/mariadb",
    ]
    for path in explicit_paths:
        import os
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    # Fallback: buscar en PATH del proceso
    for binary in ("mariadb", "mysql"):
        found = shutil.which(binary)
        if found:
            return found
    raise Exception(
        "Cliente MariaDB/MySQL no encontrado. "
        "Ejecuta en el servidor: apt install -y mariadb-client"
    )


def _run_mariadb(sql: str) -> str:
    """
    Ejecuta SQL en MariaDB usando el usuario administrador del panel.
    Usa el cliente CLI (mariadb o mysql) sin dependencias Python extra.
    Lanza Exception con el mensaje de error si falla.
    """
    try:
        binary = _mariadb_binary()
        cmd = [
            binary,
            f"--host={MARIADB_HOST}",
            f"--user={MARIADB_PANEL_USER}",
            f"--password={MARIADB_PANEL_PASSWORD}",
            "--silent",
            "--execute", sql,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            err = result.stderr.strip()
            # Quitar advertencias de contraseña en línea de comandos
            err = "\n".join(
                line for line in err.splitlines()
                if "Using a password on the command line" not in line
                and "Deprecated program name" not in line
            )
            raise Exception(err or "Error desconocido en MariaDB")
        return result.stdout
    except subprocess.TimeoutExpired:
        raise Exception("Timeout al ejecutar comando MariaDB (>30 s)")
    except FileNotFoundError:
        raise Exception(
            "Cliente MariaDB/MySQL no encontrado. "
            "Instala mariadb-client: apt install mariadb-client"
        )


def _hash_password(password: str) -> str:
    """PBKDF2-SHA256 con salt aleatorio."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _generate_password(length: int = 20) -> str:
    """Genera una contraseña aleatoria segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # Asegurar al menos una letra, número y símbolo
        if (any(c.isalpha() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in "!@#$%^&*()" for c in pwd)):
            return pwd


def _make_db_name(username: str, suffix: str) -> str:
    """
    Genera el nombre real de la BD en MariaDB.
    Formato: {username[:16]}_{suffix}  →  max 64 chars (límite MariaDB).
    """
    prefix = re.sub(r'[^a-z0-9_]', '_', username.lower())[:16]
    return f"{prefix}_{suffix}"[:64]


def _make_db_user(username: str, suffix: str) -> str:
    """
    Genera el nombre real del usuario en MariaDB.
    Formato: {username[:10]}_{suffix}  →  max 32 chars (límite MariaDB seguro).
    """
    prefix = re.sub(r'[^a-z0-9_]', '_', username.lower())[:10]
    return f"{prefix}_{suffix}"[:32]


def _assert_can_manage(current_user: User, owner_id: int, db: Session):
    """Lanza 403 si current_user no puede gestionar recursos de owner_id."""
    if current_user.role == "admin":
        return
    if current_user.role == "reseller":
        owner = db.query(User).filter(User.id == owner_id).first()
        if owner and owner.parent_id == current_user.id:
            return
        if current_user.id == owner_id:
            return
        raise HTTPException(status_code=403, detail="Sin permisos para gestionar este recurso")
    if current_user.id != owner_id:
        raise HTTPException(status_code=403, detail="Sin permisos")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/databases/charsets", tags=["Databases"])
def list_charsets():
    """Lista charsets y collations disponibles para crear BDs MariaDB."""
    return {
        "status": "success",
        "charsets": [
            {
                "charset": "utf8mb4",
                "description": "UTF-8 completo (recomendado para todos los idiomas y emojis)",
                "collations": [
                    {"name": "utf8mb4_unicode_ci",  "description": "Unicode CI — recomendada"},
                    {"name": "utf8mb4_general_ci",  "description": "General CI — más rápida"},
                    {"name": "utf8mb4_spanish_ci",  "description": "Español (ñ, ü, tildes)"},
                ],
                "default_collation": "utf8mb4_unicode_ci",
            },
            {
                "charset": "utf8",
                "description": "UTF-8 básico (3 bytes, sin emojis — usar utf8mb4 preferiblemente)",
                "collations": [
                    {"name": "utf8_unicode_ci", "description": "Unicode CI"},
                    {"name": "utf8_general_ci", "description": "General CI"},
                ],
                "default_collation": "utf8_unicode_ci",
            },
            {
                "charset": "latin1",
                "description": "ISO-8859-1 (Europa occidental, legacy)",
                "collations": [
                    {"name": "latin1_swedish_ci", "description": "Swedish CI (default MariaDB)"},
                    {"name": "latin1_spanish_ci", "description": "Español"},
                ],
                "default_collation": "latin1_swedish_ci",
            },
        ]
    }


@router.get("/databases", response_model=DatabaseListResponse, tags=["Databases"])
def list_databases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = Query(None, description="Filtrar por usuario (solo admin/reseller)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista bases de datos MariaDB.
    - Admin: ve todas (o filtradas por user_id)
    - Reseller: ve las propias + las de sus clientes
    - User: solo ve las suyas
    """
    query = db.query(ClientDatabase)

    if current_user.role == "admin":
        if user_id is not None:
            query = query.filter(ClientDatabase.user_id == user_id)
    elif current_user.role == "reseller":
        client_ids = [
            u.id for u in db.query(User).filter(User.parent_id == current_user.id).all()
        ]
        client_ids.append(current_user.id)
        if user_id is not None:
            if user_id not in client_ids:
                raise HTTPException(status_code=403, detail="Sin permisos para ver ese usuario")
            query = query.filter(ClientDatabase.user_id == user_id)
        else:
            query = query.filter(ClientDatabase.user_id.in_(client_ids))
    else:
        query = query.filter(ClientDatabase.user_id == current_user.id)

    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.post("/databases", response_model=DatabaseCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Databases"])
def create_database(
    data: DatabaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea una base de datos MariaDB para el usuario.

    - Genera el nombre real: `{username}_{db_name_suffix}`
    - Genera el usuario real: `{username}_{db_user_suffix}`
    - Ejecuta CREATE DATABASE + CREATE USER + GRANT en MariaDB
    - Guarda la metadata en PostgreSQL
    - **Devuelve la contraseña una sola vez** — el cliente debe guardarla
    """
    _check_mariadb_enabled()

    # ── Determinar propietario ────────────────────────────────────────────────
    # Un admin puede crear BDs para cualquier usuario si pasara user_id,
    # pero en este endpoint el propietario siempre es el usuario autenticado.
    owner = current_user

    # ── Verificar límite ──────────────────────────────────────────────────────
    db_count = db.query(ClientDatabase).filter(ClientDatabase.user_id == owner.id).count()
    if owner.databases_limit > 0 and db_count >= owner.databases_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Límite de bases de datos alcanzado ({owner.databases_limit}). "
                   f"Contacta con el administrador para ampliar el límite."
        )

    # ── Generar nombres reales en MariaDB ─────────────────────────────────────
    db_name = _make_db_name(owner.username, data.db_name_suffix)
    db_user = _make_db_user(owner.username, data.db_user_suffix)

    # ── Verificar unicidad ────────────────────────────────────────────────────
    if db.query(ClientDatabase).filter(ClientDatabase.db_name == db_name).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La base de datos '{db_name}' ya existe"
        )
    if db.query(ClientDatabase).filter(ClientDatabase.db_user == db_user).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario de BD '{db_user}' ya existe"
        )

    # ── Verificar dominio (si se especificó) ──────────────────────────────────
    if data.domain_id:
        domain = db.query(Domain).filter(Domain.id == data.domain_id).first()
        if not domain:
            raise HTTPException(status_code=404, detail="Dominio no encontrado")
        if domain.user_id != owner.id and current_user.role not in ["admin", "reseller"]:
            raise HTTPException(status_code=403, detail="Sin permisos para ese dominio")

    # ── Crear en MariaDB ──────────────────────────────────────────────────────
    db_charset   = data.db_charset
    db_collation = data.db_collation
    password  = data.db_password

    # Escapar backtick en el nombre de la BD (prevención de SQL injection)
    safe_db_name = db_name.replace("`", "``")
    # Los usuarios y contraseñas van entre comillas simples — escapar ' → ''
    safe_db_user = db_user.replace("'", "''")
    safe_password = password.replace("'", "''")

    created_db   = False
    created_user = False

    try:
        _run_mariadb(
            f"CREATE DATABASE `{safe_db_name}` "
            f"CHARACTER SET {db_charset} COLLATE {db_collation};"
        )
        created_db = True

        _run_mariadb(
            f"CREATE USER '{safe_db_user}'@'localhost' "
            f"IDENTIFIED BY '{safe_password}';"
        )
        created_user = True

        # Otorgar permisos específicos (no ALL PRIVILEGES — requiere tenerlos
        # todos en la cuenta admin, lo que puede no cumplirse siempre)
        _run_mariadb(
            f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, "
            f"CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, "
            f"CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, "
            f"EVENT, TRIGGER ON `{safe_db_name}`.* "
            f"TO '{safe_db_user}'@'localhost';"
        )
        _run_mariadb("FLUSH PRIVILEGES;")

    except Exception as exc:
        # Limpieza: deshacer lo que se llegó a crear
        try:
            if created_user:
                _run_mariadb(f"DROP USER IF EXISTS '{safe_db_user}'@'localhost';")
        except Exception:
            pass
        try:
            if created_db:
                _run_mariadb(f"DROP DATABASE IF EXISTS `{safe_db_name}`;")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creando base de datos en MariaDB: {exc}"
        )

    # ── Guardar metadata en PostgreSQL ────────────────────────────────────────
    try:
        client_db = ClientDatabase(
            user_id          = owner.id,
            domain_id        = data.domain_id,
            db_name          = db_name,
            db_name_suffix   = data.db_name_suffix,
            db_user          = db_user,
            db_user_suffix   = data.db_user_suffix,
            db_password_hash = _hash_password(password),
            db_password_enc  = _encrypt_password(password),  # para phpMyAdmin autologin
            db_charset       = db_charset,
            db_collation     = db_collation,
            quota_mb         = data.quota_mb,
        )
        db.add(client_db)
        db.commit()
        db.refresh(client_db)
    except IntegrityError:
        db.rollback()
        # Si falla en PostgreSQL, limpiar MariaDB
        try:
            _run_mariadb(f"DROP USER IF EXISTS '{safe_db_user}'@'localhost';")
            _run_mariadb(f"DROP DATABASE IF EXISTS `{safe_db_name}`;")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto al guardar la BD en el panel"
        )

    # ── Respuesta (contraseña solo esta vez) ──────────────────────────────────
    return DatabaseCreateResponse(
        **{k: v for k, v in client_db.__dict__.items() if not k.startswith("_")},
        db_password=password,
        message=(
            "⚠ Base de datos creada. Guarda la contraseña ahora mismo. "
            "No se puede recuperar después; si la pierdes deberás resetearla."
        )
    )


@router.get("/databases/{db_id}", response_model=DatabaseResponse, tags=["Databases"])
def get_database(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene los detalles de una base de datos por ID."""
    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _assert_can_manage(current_user, client_db.user_id, db)
    return client_db


@router.get("/databases/{db_id}/pma-token", tags=["Databases"])
def get_pma_token(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Genera un token de acceso phpMyAdmin de un solo uso (válido 5 minutos).

    Flujo:
      1. Frontend llama a este endpoint.
      2. El panel crea /tmp/pma_tokens/{token}.json con user+password+exp.
      3. Devuelve { pma_url: "/pma/signon.php?token=..." }.
      4. Frontend abre esa URL en nueva pestaña.
      5. signon.php lee el fichero (lo elimina), inicia sesión phpMyAdmin y redirige.
      6. El usuario ve solo su BD, sin acceso a otras.
    """
    _check_mariadb_enabled()

    if not PANEL_ENCRYPTION_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "phpMyAdmin no está configurado. "
                "Ejecuta install_mariadb.sh para instalarlo, o añade "
                "PANEL_ENCRYPTION_KEY al .env y reinicia el panel."
            ),
        )

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _assert_can_manage(current_user, client_db.user_id, db)

    if not client_db.db_password_enc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No hay contraseña guardada para esta BD. "
                "Cambia la contraseña desde el panel para habilitar phpMyAdmin autologin."
            ),
        )

    plaintext = _decrypt_password(client_db.db_password_enc)
    if not plaintext:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error descifrando la contraseña almacenada. Comprueba PANEL_ENCRYPTION_KEY.",
        )

    # ── Crear token de un solo uso ────────────────────────────────────────────
    token = uuid.uuid4().hex  # 32 chars hex, sin guiones
    token_dir = "/tmp/pma_tokens"
    # 711: root puede crear/borrar; otros pueden acceder si conocen el nombre exacto.
    # El nombre es un UUID de 128 bits → prácticamente imposible de adivinar.
    os.makedirs(token_dir, mode=0o711, exist_ok=True)
    # Asegurar permisos del directorio incluso si ya existía con permisos incorrectos
    os.chmod(token_dir, 0o711)
    token_file = os.path.join(token_dir, f"{token}.json")
    token_data = {
        "user":     client_db.db_user,
        "password": plaintext,
        "db":       client_db.db_name,
        "exp":      time.time() + 300,  # 5 minutos
    }
    with open(token_file, "w") as fh:
        json.dump(token_data, fh)
    # 644: legible por www-data (PHP-FPM); el UUID en el nombre lo hace inaccesible por fuerza bruta
    os.chmod(token_file, 0o644)

    return {
        "status":      "success",
        "pma_url":     f"/pma/signon.php?token={token}",
        "expires_in":  300,
        "db_name":     client_db.db_name,
        "db_user":     client_db.db_user,
    }


@router.put("/databases/{db_id}", response_model=DatabaseResponse, tags=["Databases"])
def update_database(
    db_id: int,
    data: DatabaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actualiza parámetros de una BD (quota, dominio asociado, estado activo).
    No cambia el nombre ni el usuario de MariaDB (usa el endpoint /password para eso).
    """
    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _assert_can_manage(current_user, client_db.user_id, db)

    if data.domain_id is not None:
        domain = db.query(Domain).filter(Domain.id == data.domain_id).first()
        if not domain:
            raise HTTPException(status_code=404, detail="Dominio no encontrado")
        client_db.domain_id = data.domain_id

    if data.quota_mb is not None:
        client_db.quota_mb = data.quota_mb

    if data.is_active is not None:
        client_db.is_active = data.is_active

    db.commit()
    db.refresh(client_db)
    return client_db


@router.put("/databases/{db_id}/password", response_model=DatabasePasswordResetResponse, tags=["Databases"])
def reset_database_password(
    db_id: int,
    data: DatabaseChangePassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cambia la contraseña del usuario MariaDB de una BD.
    Actualiza tanto MariaDB (ALTER USER) como el hash en PostgreSQL.
    Devuelve la nueva contraseña en claro una sola vez.
    """
    _check_mariadb_enabled()

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _assert_can_manage(current_user, client_db.user_id, db)

    safe_user = client_db.db_user.replace("'", "''")
    safe_pass = data.new_password.replace("'", "''")

    try:
        _run_mariadb(
            f"ALTER USER '{safe_user}'@'localhost' IDENTIFIED BY '{safe_pass}';"
        )
        _run_mariadb("FLUSH PRIVILEGES;")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cambiando contraseña en MariaDB: {exc}"
        )

    client_db.db_password_hash = _hash_password(data.new_password)
    client_db.db_password_enc  = _encrypt_password(data.new_password)  # refrescar cifrado phpMyAdmin
    db.commit()

    return DatabasePasswordResetResponse(
        db_user=client_db.db_user,
        new_password=data.new_password,
    )


@router.delete("/databases/{db_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Databases"])
def delete_database(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina una BD y su usuario de MariaDB, y borra el registro del panel.
    Si hay errores en MariaDB, el registro del panel se borra igualmente
    y se devuelve un warning en el header X-Warning.
    """
    _check_mariadb_enabled()

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _assert_can_manage(current_user, client_db.user_id, db)

    safe_db_name = client_db.db_name.replace("`", "``")
    safe_db_user = client_db.db_user.replace("'", "''")

    mariadb_errors = []

    try:
        _run_mariadb(f"DROP DATABASE IF EXISTS `{safe_db_name}`;")
    except Exception as exc:
        mariadb_errors.append(f"drop_db: {exc}")

    try:
        _run_mariadb(f"DROP USER IF EXISTS '{safe_db_user}'@'localhost';")
        _run_mariadb("FLUSH PRIVILEGES;")
    except Exception as exc:
        mariadb_errors.append(f"drop_user: {exc}")

    # Eliminar siempre del panel, aunque haya errores en MariaDB
    db.delete(client_db)
    db.commit()

    if mariadb_errors:
        # Devolver 207 con detalle de lo que falló
        raise HTTPException(
            status_code=207,
            detail={
                "message": "BD eliminada del panel pero con errores en MariaDB",
                "errors": mariadb_errors,
            }
        )

    return None


# ── Endpoints: usuarios adicionales de BD ────────────────────────────────────

def _check_db_access(current_user: User, client_db: ClientDatabase, db: Session):
    """
    Lanza 403/404 si current_user no puede gestionar esta BD.
    Reutiliza la lógica de _assert_can_manage.
    """
    _assert_can_manage(current_user, client_db.user_id, db)


def _make_db_extra_user(owner_username: str, suffix: str) -> str:
    """
    Genera el nombre de un usuario adicional de MariaDB.
    Formato: {owner_username[:10]}_{suffix}  →  máx 64 chars.
    El límite real de MariaDB para usuarios es 80 chars desde 10.4,
    pero usamos 64 para ser conservadores y evitar problemas con versiones antiguas.
    """
    prefix = re.sub(r'[^a-z0-9_]', '_', owner_username.lower())[:10]
    full = f"{prefix}_{suffix}"
    if len(full) > 64:
        raise ValueError(
            f"El nombre de usuario resultante '{full}' supera 64 caracteres. "
            f"Usa un suffix más corto."
        )
    return full


@router.get(
    "/databases/{db_id}/users",
    response_model=List[DatabaseUserResponse],
    tags=["Databases"],
)
def list_db_users(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista los usuarios adicionales de una BD.
    El usuario principal (db_user) NO aparece aquí.
    """
    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _check_db_access(current_user, client_db, db)

    users_list = (
        db.query(DatabaseUser)
        .filter(DatabaseUser.database_id == db_id)
        .order_by(DatabaseUser.created_at)
        .all()
    )
    return users_list


@router.post(
    "/databases/{db_id}/users",
    response_model=DatabaseUserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Databases"],
)
def create_db_user(
    db_id: int,
    data: DatabaseUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crea un usuario adicional de MariaDB para una BD.

    - El nombre completo en MariaDB: `{owner_username}_{suffix}` (máx 64 chars)
    - Permisos configurables: SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES, LOCK TABLES
    - La contraseña se guarda cifrada con Fernet para phpMyAdmin autologin
    - Si falla el INSERT en PostgreSQL, se hace DROP USER en MariaDB (rollback limpio)
    """
    _check_mariadb_enabled()

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _check_db_access(current_user, client_db, db)

    # Obtener el propietario de la BD para construir el nombre del usuario
    owner = db.query(User).filter(User.id == client_db.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario de la BD no encontrado")

    # Construir nombre completo en MariaDB
    try:
        full_username = _make_db_extra_user(owner.username, data.username_suffix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Verificar que el suffix no colisione con el usuario principal
    if full_username == client_db.db_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este nombre de usuario coincide con el usuario principal de la BD",
        )

    # Verificar unicidad en la tabla database_users
    existing = (
        db.query(DatabaseUser)
        .filter(
            DatabaseUser.database_id == db_id,
            DatabaseUser.username == full_username,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario '{full_username}' ya existe para esta BD",
        )

    # Construir sentencia GRANT
    safe_username = full_username.replace("'", "''")
    safe_password = data.password.replace("'", "''")
    safe_db_name  = client_db.db_name.replace("`", "``")
    perms_str     = ", ".join(sorted(data.permissions))

    created_mariadb_user = False
    try:
        _run_mariadb(
            f"CREATE USER '{safe_username}'@'localhost' IDENTIFIED BY '{safe_password}';"
        )
        created_mariadb_user = True

        _run_mariadb(
            f"GRANT {perms_str} ON `{safe_db_name}`.* "
            f"TO '{safe_username}'@'localhost';"
        )
        _run_mariadb("FLUSH PRIVILEGES;")

    except Exception as exc:
        # Limpieza: si el usuario se creó pero el GRANT falló, hacer DROP
        if created_mariadb_user:
            try:
                _run_mariadb(f"DROP USER IF EXISTS '{safe_username}'@'localhost';")
                _run_mariadb("FLUSH PRIVILEGES;")
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creando usuario en MariaDB: {exc}",
        )

    # Guardar en PostgreSQL
    import json
    try:
        db_user_obj = DatabaseUser(
            database_id      = db_id,
            username         = full_username,
            username_suffix  = data.username_suffix,
            permissions      = json.dumps(sorted(data.permissions)),
            db_password_hash = _hash_password(data.password),
            db_password_enc  = _encrypt_password(data.password),
            is_active        = True,
        )
        db.add(db_user_obj)
        db.commit()
        db.refresh(db_user_obj)
    except IntegrityError:
        db.rollback()
        # Rollback en MariaDB
        try:
            _run_mariadb(
                f"REVOKE ALL ON `{safe_db_name}`.* FROM '{safe_username}'@'localhost';"
            )
            _run_mariadb(f"DROP USER IF EXISTS '{safe_username}'@'localhost';")
            _run_mariadb("FLUSH PRIVILEGES;")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto al guardar el usuario en el panel",
        )

    return db_user_obj


@router.put(
    "/databases/{db_id}/users/{user_id}",
    response_model=DatabaseUserResponse,
    tags=["Databases"],
)
def update_db_user(
    db_id: int,
    user_id: int,
    data: DatabaseUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actualiza permisos y/o contraseña de un usuario adicional.

    - Para los permisos: REVOKE ALL + GRANT nuevos permisos + FLUSH PRIVILEGES
    - Para la contraseña: ALTER USER + actualizar hash/cifrado en PostgreSQL
    - is_active=False no revoca permisos en MariaDB (solo marca en panel)
    """
    _check_mariadb_enabled()

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _check_db_access(current_user, client_db, db)

    db_user_obj = (
        db.query(DatabaseUser)
        .filter(
            DatabaseUser.id == user_id,
            DatabaseUser.database_id == db_id,
        )
        .first()
    )
    if not db_user_obj:
        raise HTTPException(status_code=404, detail="Usuario de BD no encontrado")

    safe_username = db_user_obj.username.replace("'", "''")
    safe_db_name  = client_db.db_name.replace("`", "``")

    import json

    # ── Actualizar permisos en MariaDB ────────────────────────────────────
    if data.permissions is not None:
        perms_str = ", ".join(sorted(data.permissions))
        try:
            _run_mariadb(
                f"REVOKE ALL PRIVILEGES ON `{safe_db_name}`.* "
                f"FROM '{safe_username}'@'localhost';"
            )
            _run_mariadb(
                f"GRANT {perms_str} ON `{safe_db_name}`.* "
                f"TO '{safe_username}'@'localhost';"
            )
            _run_mariadb("FLUSH PRIVILEGES;")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error actualizando permisos en MariaDB: {exc}",
            )
        db_user_obj.permissions = json.dumps(sorted(data.permissions))

    # ── Actualizar contraseña en MariaDB ──────────────────────────────────
    if data.password is not None:
        safe_password = data.password.replace("'", "''")
        try:
            _run_mariadb(
                f"ALTER USER '{safe_username}'@'localhost' "
                f"IDENTIFIED BY '{safe_password}';"
            )
            _run_mariadb("FLUSH PRIVILEGES;")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error actualizando contraseña en MariaDB: {exc}",
            )
        db_user_obj.db_password_hash = _hash_password(data.password)
        db_user_obj.db_password_enc  = _encrypt_password(data.password)

    # ── Actualizar estado activo (solo en panel) ──────────────────────────
    if data.is_active is not None:
        db_user_obj.is_active = data.is_active

    db.commit()
    db.refresh(db_user_obj)
    return db_user_obj


@router.delete(
    "/databases/{db_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Databases"],
)
def delete_db_user(
    db_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Elimina un usuario adicional de MariaDB y borra el registro del panel.

    - Ejecuta DROP USER IF EXISTS en MariaDB + FLUSH PRIVILEGES
    - Elimina siempre el registro del panel aunque MariaDB falle
      (se devuelve 207 con detalle de errores si los hay)
    """
    _check_mariadb_enabled()

    client_db = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not client_db:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    _check_db_access(current_user, client_db, db)

    db_user_obj = (
        db.query(DatabaseUser)
        .filter(
            DatabaseUser.id == user_id,
            DatabaseUser.database_id == db_id,
        )
        .first()
    )
    if not db_user_obj:
        raise HTTPException(status_code=404, detail="Usuario de BD no encontrado")

    safe_username = db_user_obj.username.replace("'", "''")
    mariadb_errors = []

    try:
        _run_mariadb(f"DROP USER IF EXISTS '{safe_username}'@'localhost';")
        _run_mariadb("FLUSH PRIVILEGES;")
    except Exception as exc:
        mariadb_errors.append(f"drop_user: {exc}")

    # Eliminar siempre del panel, aunque haya errores en MariaDB
    db.delete(db_user_obj)
    db.commit()

    if mariadb_errors:
        raise HTTPException(
            status_code=207,
            detail={
                "message": "Usuario eliminado del panel pero con errores en MariaDB",
                "errors": mariadb_errors,
            },
        )

    return None


# ── Endpoint de administración ────────────────────────────────────────────────

@router.post("/admin/databases/sync-sizes", tags=["Databases"])
def sync_database_sizes(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    (Admin) Sincroniza el tamaño real de todas las BDs MariaDB
    consultando information_schema y actualizando size_mb en PostgreSQL.
    """
    _check_mariadb_enabled()

    try:
        sql = """
            SELECT table_schema AS db_name,
                   ROUND(SUM(data_length + index_length) / 1048576, 2) AS size_mb
            FROM information_schema.tables
            WHERE table_schema NOT IN
                  ('mysql','information_schema','performance_schema','sys')
            GROUP BY table_schema;
        """
        output = _run_mariadb(sql)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando information_schema: {exc}"
        )

    # Parsear output (tab-separated)
    size_map: dict[str, float] = {}
    for line in output.strip().splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2:
            try:
                size_map[parts[0]] = float(parts[1])
            except ValueError:
                pass

    # Actualizar en PostgreSQL
    updated = 0
    all_dbs = db.query(ClientDatabase).all()
    for client_db in all_dbs:
        if client_db.db_name in size_map:
            client_db.size_mb = int(size_map[client_db.db_name])
            updated += 1

    db.commit()

    return {
        "status": "success",
        "updated": updated,
        "total": len(all_dbs),
        "message": f"Tamaños actualizados para {updated} de {len(all_dbs)} bases de datos",
    }
