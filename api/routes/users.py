"""
Rutas API para gestión de usuarios
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from api.models.database import get_db
from api.models.models_user import User
from api.schemas.user_schemas import UserCreate, UserUpdate, UserResponse
from api.dependencies import require_admin, require_auth, require_admin_or_reseller
from api.utils.security_audit import log_audit
from scripts.user_manager import UserManager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _is_admin(u: User) -> bool:
    """¿Es admin? Mira role Y is_admin porque pueden desincronizarse: cli.py y el
    importador escriben cada uno por su lado, y require_admin solo mira `role`."""
    return bool(getattr(u, "is_admin", False)) or getattr(u, "role", None) == "admin"


def _guard_admin_target(actor: User, target: User, action: str) -> None:
    """Impide que un admin toque la CUENTA de OTRO admin.

    Un admin no debe poder robar, degradar ni borrar la cuenta de otro admin
    (típicamente el fundador del panel): cambiarle la contraseña equivale a
    apropiarse de ella, y además se propaga al usuario Linux. Es la misma regla
    que ya aplicaban suspend_user() y sftp._resolve_target(); faltaba aquí.

    Sobre uno mismo sí se permite (cambiarse la propia contraseña es legítimo).

    Nota de alcance: esto NO es una frontera de privilegio dura. Por diseño
    cualquier admin puede abrir una terminal como root (ver terminal.py), así que
    un admin ya es todopoderoso en el servidor. Esto es una red de seguridad
    contra errores y apropiaciones silenciosas (que además quedan auditadas),
    no una defensa contra un admin hostil.
    """
    if target.id == actor.id:
        return
    if _is_admin(target):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"No se puede {action} la cuenta de otro administrador "
                    f"({target.username}). Debe hacerlo él mismo."),
        )


def _count_other_admins(db: Session, exclude_id: int) -> int:
    """Nº de admins del panel distintos del indicado."""
    return (db.query(User)
            .filter(((User.is_admin == True) | (User.role == "admin")),  # noqa: E712
                    User.id != exclude_id)
            .count())


def _apply_disk_quota(db_user: User) -> None:
    """
    Aplica la cuota de disco del usuario en el SO vía setquota.
    Tolerante a fallos: si el sistema de cuotas no está activo o algo falla,
    solo loguea (no rompe la operación del panel). disk_quota_mb=0 → ilimitado.
    """
    try:
        from scripts.quota_manager import QuotaManager
        qm = QuotaManager()
        if not qm.is_quota_active():
            logger.info("Sistema de cuotas inactivo; no se aplica disk_quota a %s", db_user.username)
            return
        qm.set_quota(db_user.username, db_user.disk_quota_mb or 0)
    except PermissionError:
        logger.warning("Sin privilegios root para aplicar cuota (¿entorno dev?)")
    except Exception as e:
        logger.warning("No se pudo aplicar cuota a %s: %s", db_user.username, e)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    request: Request,
    current_user: User = Depends(require_admin_or_reseller),
    db: Session = Depends(get_db)
):
    """Crear un nuevo usuario (admin: cualquier rol; reseller: solo usuarios regulares)"""
    user_manager = UserManager()

    # Reseller solo puede crear usuarios regulares (no admins ni otros resellers)
    role = user.role or "user"
    if current_user.role == "reseller" and role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los resellers solo pueden crear usuarios regulares"
        )

    # parent_id llega del body y NO se validaba: un reseller podía colgar cuentas
    # del árbol de OTRO reseller (metiendo/ocultando clientes en su cartera).
    # Aquí sí hay frontera de privilegio real (un reseller no tiene shell root).
    if user.parent_id is not None:
        if current_user.role == "reseller" and user.parent_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Un reseller solo puede crear clientes en su propia cuenta",
            )
        parent = db.query(User).filter(User.id == user.parent_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El padre indicado (parent_id={user.parent_id}) no existe",
            )
        if parent.role not in ("admin", "reseller"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Solo un admin o un reseller puede ser padre de una "
                        "cuenta; indicado: " + (parent.role or "user")),
            )

    # Política de contraseñas del panel
    from scripts.password_policy import enforce_or_400
    enforce_or_400(user.password, db)

    try:
        # Crear usuario del sistema
        user_manager.create_user(user.username, user.email, user.password)

        # Crear usuario en BD
        # Determinar parent_id:
        # 1. Si el body lo especifica explícitamente → usarlo (admin creando cliente de un reseller)
        # 2. Si quien crea es un reseller → se asigna a sí mismo
        # 3. Si es admin sin parent_id → None (cuenta de nivel superior)
        if user.parent_id is not None:
            parent_id = user.parent_id
        elif current_user.role == "reseller":
            parent_id = current_user.id
        else:
            parent_id = None

        db_user = User(
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=role,
            is_admin=(role == "admin"),
            domains_limit=user.domains_limit if user.domains_limit is not None else 10,
            parent_id=parent_id,
        )
        db_user.set_password(user.password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Auditoría: la creación de un admin/reseller es un cambio de privilegios
        # que debe quedar registrado (quién lo creó, con qué rol y bajo qué padre).
        log_audit(db, user=current_user, category="users", action="create",
                  target=db_user.username,
                  after={"username": db_user.username, "email": db_user.email,
                         "role": db_user.role, "parent_id": db_user.parent_id},
                  request=request)

        # Aplicar la cuota de disco en el SO (si el sistema de cuotas está activo).
        # Tolerante a fallos: si no hay cuotas activas, no rompe la creación.
        _apply_disk_quota(db_user)

        return db_user
    except IntegrityError:
        db.rollback()
        try:
            user_manager.delete_user(user.username)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario o email ya existe"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear usuario: {str(e)}"
        )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    parent_id: int = Query(None, description="Filtrar clientes de un reseller"),
    current_user: User = Depends(require_admin_or_reseller),
    db: Session = Depends(get_db)
):
    """
    Listar usuarios.
    - Admin: ve todos (o filtra por parent_id para ver clientes de un reseller)
    - Reseller: ve solo sus propios clientes (parent_id = current_user.id)
    """
    try:
        query = db.query(User)

        if current_user.role == "admin":
            if parent_id is not None:
                # Admin filtrando clientes de un reseller concreto
                query = query.filter(User.parent_id == parent_id)
        else:
            # Reseller solo ve sus clientes
            query = query.filter(User.parent_id == current_user.id)

        users = query.order_by(User.username).offset(skip).limit(limit).all()
        return users
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener un usuario por ID. Admin puede ver cualquiera; usuario solo el suyo propio."""
    # Un usuario normal solo puede ver su propia cuenta
    if not current_user.is_admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este usuario"
        )
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )
        return user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Actualizar un usuario"""
    try:
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        # No tocar la cuenta de otro admin (contraseña, rol, estado…).
        _guard_admin_target(current_user, db_user, "modificar")

        # El panel debe conservar SIEMPRE al menos un admin activo: si no, nadie
        # puede volver a entrar a administrarlo. Cubre degradar el rol y
        # desactivar la cuenta, incluido hacérselo a uno mismo (el caso fácil de
        # provocar por error). delete_user ya tenía este check; PUT no.
        _losing_admin = (_is_admin(db_user)
                         and user_update.role is not None
                         and user_update.role != "admin")
        _deactivating = (user_update.is_active is False and db_user.is_active
                         and _is_admin(db_user))
        if (_losing_admin or _deactivating) and _count_other_admins(db, db_user.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Es el único administrador del panel: no se puede quitarle "
                        "el rol de administrador ni desactivarlo (nadie podría "
                        "volver a administrar el panel). Crea otro admin primero."),
            )

        # Estado previo, para la auditoría (antes de mutar el objeto).
        _before = {"email": db_user.email, "role": db_user.role,
                   "is_active": db_user.is_active,
                   "domains_limit": db_user.domains_limit,
                   "disk_quota_mb": db_user.disk_quota_mb}

        if user_update.email is not None:
            db_user.email = user_update.email
        if user_update.first_name is not None:
            db_user.first_name = user_update.first_name
        if user_update.last_name is not None:
            db_user.last_name = user_update.last_name
        if user_update.is_active is not None:
            db_user.is_active = user_update.is_active
        if user_update.domains_limit is not None:
            db_user.domains_limit = user_update.domains_limit
        quota_changed = False
        if user_update.disk_quota_mb is not None and user_update.disk_quota_mb != db_user.disk_quota_mb:
            db_user.disk_quota_mb = user_update.disk_quota_mb
            quota_changed = True
        if user_update.role is not None:
            db_user.role = user_update.role
            db_user.is_admin = (user_update.role == "admin")

        # Cambio de contraseña (opcional)
        if user_update.new_password:
            from scripts.password_policy import enforce_or_400
            enforce_or_400(user_update.new_password, db)
            db_user.set_password(user_update.new_password)
            # Cambiar también en el sistema operativo
            try:
                user_manager = UserManager()
                user_manager.change_password(db_user.username, user_update.new_password)
            except Exception as e:
                # Si falla el cambio en el SO, avisamos pero no revertimos la BD
                import logging
                logging.getLogger(__name__).warning(f"OS password change failed for {db_user.username}: {e}")

        db.commit()
        db.refresh(db_user)

        # Auditoría: quién cambió qué y a quién. Sin esto, un cambio de rol o de
        # contraseña ajena no dejaba NINGÚN rastro en el panel.
        log_audit(db, user=current_user, category="users", action="update",
                  target=db_user.username, before=_before,
                  after={"email": db_user.email, "role": db_user.role,
                         "is_active": db_user.is_active,
                         "domains_limit": db_user.domains_limit,
                         "disk_quota_mb": db_user.disk_quota_mb,
                         "password_changed": bool(user_update.new_password)},
                  request=request)

        # Si cambió la cuota de disco, aplicarla en el SO
        if quota_changed:
            _apply_disk_quota(db_user)

        return db_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya existe"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Eliminar un usuario"""
    user_manager = UserManager()

    try:
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        # Borrar un usuario PURGA todo su sistema (home, correo, BDs, vhosts) y
        # es irreversible: un admin no puede hacérselo a otro admin.
        _guard_admin_target(current_user, db_user, "eliminar")

        # Tampoco puede borrarse a sí mismo: _guard_admin_target permite actuar
        # sobre uno mismo (para cambiar la propia contraseña), pero auto-borrarse
        # destruiría la sesión en curso y su home sin vuelta atrás.
        if db_user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("No puedes eliminar tu propia cuenta. Pide a otro "
                        "administrador que lo haga."),
            )

        # No permitir borrar el último admin del panel (quedaría sin acceso).
        if _is_admin(db_user) and _count_other_admins(db, db_user.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede eliminar el único administrador del panel",
            )

        # Limpieza COMPLETA de sistema (vhosts nginx+Apache, IPv6, correo,
        # DNS + cluster, BDs MariaDB, crontab, subcuentas SFTP, pools PHP…).
        # DEBE ir ANTES del db.delete: necesita los nombres de dominio/BD que
        # el cascade está a punto de borrar. Best-effort: acumula avisos.
        warnings = []
        try:
            from scripts.user_purge import purge_user_system
            warnings = purge_user_system(db, db_user)
        except Exception as e:
            warnings.append(f"purge: {e}")

        # Delete system user (home + spool de correo)
        try:
            user_manager.delete_user(db_user.username)
        except Exception as e:
            warnings.append(f"userdel: {e}")

        # Auditoría ANTES del delete: después el usuario ya no existe y no
        # podríamos registrar ni su username ni su rol.
        log_audit(db, user=current_user, category="users", action="delete",
                  target=db_user.username,
                  before={"username": db_user.username, "email": db_user.email,
                          "role": db_user.role, "id": db_user.id},
                  after=None, request=request,
                  success=not warnings,
                  error="; ".join(warnings) if warnings else None)

        # Delete from database (cascade borra domains/mail/db/cron de la BD)
        db.delete(db_user)
        db.commit()

        if warnings:
            # 207: el usuario se borró pero hubo errores en la limpieza de sistema.
            raise HTTPException(
                status_code=status.HTTP_207_MULTI_STATUS,
                detail={
                    "message": "Usuario eliminado, pero con avisos en la limpieza de sistema",
                    "warnings": warnings,
                },
            )
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar usuario: {str(e)}"
        )


# ── Cuotas de disco ──────────────────────────────────────────────────────────

@router.get("/quota/status")
async def quota_system_status(current_user: User = Depends(require_admin)):
    """Estado del sistema de cuotas del servidor (activo o no, punto de montaje)."""
    try:
        from scripts.quota_manager import QuotaManager
        return QuotaManager().status()
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        return {"active": False, "mount": None, "message": f"No disponible: {e}"}


@router.get("/users/{user_id}/disk-usage")
async def user_disk_usage(
    user_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Uso de disco real del usuario (vía repquota) + su límite.
    Accesible por el propio usuario o por admin/reseller padre.
    """
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(404, "Usuario no encontrado")

    # Permisos: el propio usuario, un admin, o el reseller padre
    if not (current_user.is_admin
            or current_user.id == db_user.id
            or db_user.parent_id == current_user.id):
        raise HTTPException(403, "Sin permiso para ver este usuario")

    try:
        from scripts.quota_manager import QuotaManager
        usage = QuotaManager().get_usage(db_user.username)
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        usage = {"active": False, "used_mb": None, "limit_mb": None,
                 "percent": None, "over_quota": False, "error": str(e)}

    # Si la cuota del SO no está activa, devolver al menos el límite del plan (BD)
    if not usage.get("active"):
        usage["limit_mb"] = db_user.disk_quota_mb or 0
    return usage


@router.post("/users/{user_id}/apply-quota")
async def apply_user_quota(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reaplica la cuota del usuario en el SO (útil tras activar cuotas o reparar)."""
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(404, "Usuario no encontrado")
    try:
        from scripts.quota_manager import QuotaManager
        qm = QuotaManager()
        if not qm.is_quota_active():
            raise HTTPException(409, "El sistema de cuotas no está activo en el servidor")
        qm.set_quota(db_user.username, db_user.disk_quota_mb or 0)
        return {"status": "success", "disk_quota_mb": db_user.disk_quota_mb or 0}
    except HTTPException:
        raise
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        raise HTTPException(500, f"Error aplicando cuota: {e}")


@router.post("/users/{user_id}/suspend")
async def suspend_user_endpoint(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Suspende un usuario EN CASCADA: webs, correo, BDs, cuenta del
    sistema (SSH/FTP) y acceso al panel. No borra nada; reversible."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    if u.is_admin or u.role == "admin":
        raise HTTPException(403, "No se puede suspender a un administrador")
    from scripts.suspend_manager import suspend_user
    res = suspend_user(u, suspend=True, db=db)
    return {"status": "ok", **res}


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user_endpoint(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Reactiva un usuario suspendido (revierte la cascada)."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    from scripts.suspend_manager import suspend_user
    res = suspend_user(u, suspend=False, db=db)
    return {"status": "ok", **res}
