from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base
import hashlib
import secrets

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # Información personal
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    
    # Sistema
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    # Límites
    domains_limit = Column(Integer, default=10)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # Shell access
    shell_path = Column(String(255), default="/bin/bash")
    home_dir = Column(String(255), nullable=True)  # /home/usuario
    
    # Relaciones
    domains = relationship("Domain", back_populates="user", cascade="all, delete-orphan")
    
    def set_password(self, password: str):
        """Hash y guarda la contraseña"""
        salt = secrets.token_hex(32)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        self.password_hash = f"{salt}${pwd_hash.hex()}"
    
    def check_password(self, password: str) -> bool:
        """Verifica la contraseña"""
        try:
            salt, pwd_hash = self.password_hash.split('$')
            pwd_check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return pwd_check.hex() == pwd_hash
        except:
            return False
    
    def __repr__(self):
        return f"<User {self.username}>"
