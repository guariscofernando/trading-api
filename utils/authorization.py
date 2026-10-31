# utils/authorization.py
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import config
from app.dao.UserDAO import UserDAO
import bcrypt


# Configuración
SECRET_KEY = config.SECRET_KEY
ALGORITHM = config.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES

# Para extraer el token del header
security = HTTPBearer()

dao = UserDAO()

def hash_password(password: str) -> str:
    """Hashea una contraseña con bcrypt"""
    return bcrypt.hashpw(password.encode(config.ENCODE), bcrypt.gensalt()).decode(config.ENCODE)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña coincide con el hash"""
    try:
        return bcrypt.checkpw(plain_password.encode(config.ENCODE), hashed_password.encode(config.ENCODE))
    except ValueError:
        # bcrypt solo admite contraseñas de hasta 72 bytes (los caracteres no ASCII ocupan varios) y
        # lanza ValueError con más: nunca puede coincidir. Un hash corrupto también cae aquí.
        return False

# Hash de una contraseña que nadie puede conocer. El login lo compara cuando el usuario NO existe,
# para tardar lo mismo que con un usuario real: si no, el tiempo de respuesta (4 ms frente a ~300 ms)
# delataría qué nombres de usuario están registrados.
HASH_FICTICIO = hash_password("contraseña-ficticia-que-nadie-conoce")

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Genera un token JWT"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    """Decodifica un token JWT"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def usuario_desde_token(token: str):
    """
    (usuario, motivo_de_rechazo). Es LA validación de tokens: la usan las rutas http y los WebSockets.
    Además de firma y caducidad comprueba que el token sea de la versión vigente del usuario: al cerrar sesión o
    cambiar la contraseña la versión sube y los tokens anteriores quedan revocados al instante.
    Los tokens sin versión (emitidos antes de existir esta comprobación) cuentan como versión 0.
    """
    payload = decode_access_token(token)
    if payload is None:
        return None, "Token inválido o expirado"
    user_id = payload.get("sub")
    version = payload.get("tv", 0)
    if user_id is None or isinstance(version, bool) or not isinstance(version, int):
        return None, "Token inválido"
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None, "Token inválido"
    usuario = dao.obtener_usuario_por_id(user_id)
    if usuario is None:
        return None, "Usuario no encontrado"
    if version != usuario["token_version"]:
        return None, "Sesión cerrada o revocada"
    return usuario, None


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependencia que extrae y valida el usuario actual"""
    usuario, motivo = usuario_desde_token(credentials.credentials)
    if usuario is None:
        raise HTTPException(status_code=401, detail=motivo)
    return usuario


def require_admin(usuario: dict = Depends(get_current_user)):
    """Dependencia: solo deja pasar a administradores (403 al resto).

    El rol se lee de la base en cada petición (get_current_user), no del token: quitar el rol
    a alguien surte efecto de inmediato, sin esperar a que caduque su token.
    """
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol de administrador")
    return usuario
