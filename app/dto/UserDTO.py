import re
from pydantic import BaseModel, Field, field_validator

class UsuarioCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., description="Email válido")
    password: str = Field(..., min_length=6, max_length=50)
    
    @field_validator('username')
    @classmethod
    def validar_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Username solo puede contener letras, números y _")
        return v.lower()
    
    @field_validator('email')
    @classmethod
    def validar_email(cls, v):
        patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(patron, v):
            raise ValueError("Email inválido")
        return v.lower()

class UsuarioResponse(BaseModel):
    id: int
    username: str
    email: str
    creado_en: str

class UsuarioLogin(BaseModel):
    username: str
    password: str