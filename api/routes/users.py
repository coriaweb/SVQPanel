"""
Rutas API para gestión de usuarios
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from api.models.database import get_db
from api.models.models_user import User
from api.schemas.user_schemas import UserCreate, UserUpdate, UserResponse
from api.dependencies import require_admin, require_auth, require_admin_or_reseller
from scripts.user_manager import UserManager

router = APIRouter()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
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

    try:
        # Crear usuario del sistema
        user_manager.create_user(user.username, user.email, user.password)

        # Crear usuario en BD
        db_user = User(
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=role,
            is_admin=(role == "admin"),
            domains_limit=user.domains_limit if user.domains_limit is not None else 10,
            # Si lo crea un reseller, ese reseller es el parent
            parent_id=current_user.id if current_user.role == "reseller" else None,
        )
        db_user.set_password(user.password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
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

        users = query.offset(skip).limit(limit).all()
        return users
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Obtener un usuario por ID"""
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
        if user_update.role is not None:
            db_user.role = user_update.role
            db_user.is_admin = (user_update.role == "admin")

        db.commit()
        db.refresh(db_user)
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

        # Delete system user
        user_manager.delete_user(db_user.username)

        # Delete from database
        db.delete(db_user)
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar usuario: {str(e)}"
        )
