import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

MAX_BYTES_PASSWORD = 72   # límite de bcrypt: más allá lanza error (y los caracteres no ASCII ocupan varios bytes)


class UsuarioCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., description="Email válido")
    password: str = Field(..., min_length=6, max_length=50)
    
    @field_validator('password')
    @classmethod
    def validar_password(cls, v):
        if len(v.encode("utf-8")) > MAX_BYTES_PASSWORD:
            raise ValueError(
                f"La contraseña no puede superar {MAX_BYTES_PASSWORD} bytes "
                "(los emojis y las letras con tilde ocupan más de uno)"
            )
        return v

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

    @field_validator('creado_en', mode='before')
    @classmethod
    def formatear_fecha(cls, v):
        # PostgreSQL devuelve un datetime; la API siempre expone "YYYY-MM-DD HH:MM"
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M")
        return v

class UsuarioLogin(BaseModel):
    # Mismos máximos que el registro (username) y un tope razonable para la contraseña: sin tope se
    # aceptaban cuerpos de megabytes. Una contraseña de más de 72 bytes no puede ser válida (el registro
    # no la admite): llega al login, falla como cualquier credencial incorrecta y cuenta como intento.
    username: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator('username')
    @classmethod
    def normalizar_username(cls, v):
        # El registro guarda el usuario en minúsculas: sin esto "Ana" no podía entrar con la cuenta "ana".
        return v.lower()