"""
Esquemas Pydantic para usuarios
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field("user", pattern="^(admin|reseller|user)$")
    domains_limit: Optional[int] = Field(10, ge=0)
    parent_id: Optional[int] = Field(None, description="ID del reseller propietario")


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field(None, pattern="^(admin|reseller|user)$")
    is_active: Optional[bool] = None
    domains_limit: Optional[int] = Field(None, ge=0)
    new_password: Optional[str] = Field(None, min_length=8, description="Nueva contraseña (opcional)")


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: Optional[str] = "user"
    is_admin: bool
    is_active: bool
    domains_limit: int
    parent_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True
