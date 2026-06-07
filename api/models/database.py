from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://panel_user:panel_password_123@localhost/panel_db"
)

# Create engine
engine = create_engine(
    DATABASE_URL,
    echo=False,  # True para debug SQL
    poolclass=NullPool,
    connect_args={"connect_timeout": 10}
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para modelos
Base = declarative_base()

# Dependency para obtener BD en endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def load_all_models():
    """Importa TODOS los modelos para registrarlos en Base.metadata y permitir
    que SQLAlchemy resuelva las relationships por nombre (p.ej. Domain ->
    'GitDeployment', User -> 'CronJob') y las FK (User.plan_id -> plans).

    ÚNICA fuente de verdad: cualquier script que use la BD (install, cli,
    main, schedulers) debe llamar a esto ANTES de hacer queries o create_all.
    Si se añade un modelo nuevo, añadirlo SOLO aquí.
    """
    from api.models import (  # noqa: F401
        models_user, models_domain, models_settings, models_dns,
        models_dns_node, models_mail, models_client_db, models_db_user,
        models_security, models_server_ip, models_backup, models_notification,
        models_git, models_plan, models_cron, models_template,
        models_sftp_account, models_metrics,
    )


# Crear todas las tablas
def create_tables():
    load_all_models()
    Base.metadata.create_all(bind=engine)
