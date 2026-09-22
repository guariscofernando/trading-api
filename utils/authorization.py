import hashlib

from fastapi import HTTPException, Header
from app.config import API_KEY

def verificar_api_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida")

def hash_password(password: str) -> str:
    """Hashea una contraseña usando SHA-256"""
    # NOTA: En producción real usarías bcrypt, pero para aprender SHA-256 está bien
    return hashlib.sha256(password.encode()).hexdigest()