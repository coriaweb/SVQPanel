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

# Crear todas las tablas
def create_tables():
    # Importar modelos para que SQLAlchemy los registre en Base.metadata
    from api.models import (
        models_user, models_domain, models_settings, models_dns,
        models_mail, models_client_db, models_security, models_server_ip,
        models_backup, models_notification,
    )  # noqa
    Base.metadata.create_all(bind=engine)
