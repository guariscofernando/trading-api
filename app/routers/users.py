# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException
from app.dto.UserDTO import UsuarioCreate, UsuarioResponse, UsuarioLogin
from app.dao.UserDAO import UserDAO
from datetime import datetime
from utils.authorization import get_current_user, hash_password, verify_password, create_access_token

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])
dao = UserDAO()

@router.post("/login")
def login(datos: UsuarioLogin):
    # Buscar usuario
    usuario = dao.obtener_usuario_por_username(datos.username)
    
    if not usuario:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    # Verificar contraseña
    if not verify_password(datos.password, usuario["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    # Generar token
    token = create_access_token(data={"sub": str(usuario["id"])})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": usuario["id"],
            "username": usuario["username"],
            "email": usuario["email"]
        }
    }

# Actualizar el endpoint de registro para usar bcrypt
@router.post("/registro", response_model=UsuarioResponse, status_code=201)
def registrar_usuario(usuario: UsuarioCreate):
    if dao.obtener_usuario_por_username(usuario.username):
        raise HTTPException(status_code=400, detail="Username ya registrado")
    
    if dao.obtener_usuario_por_email(usuario.email):
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    # Usar bcrypt en lugar de SHA-256
    password_hash = hash_password(usuario.password)
    
    user_id = dao.crear_usuario_db(
        username=usuario.username,
        email=usuario.email,
        password_hash=password_hash
    )
    
    if not user_id:
        raise HTTPException(status_code=500, detail="Error al crear usuario")
    
    return {
        "id": user_id,
        "username": usuario.username,
        "email": usuario.email,
        "creado_en": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

"""
Ejercicio: Crea un endpoint /usuarios/me que devuelva la info del usuario autenticado 
usando current_user.
"""
@router.get("/me", response_model=UsuarioResponse)
def info(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=404, detail="Usuario no autenticado")
    return dao.obtener_usuario_por_id(current_user["id"])

@router.get("/{user_id}", response_model=UsuarioResponse)
def obtener_usuario(user_id: int):
    usuario = dao.obtener_usuario_por_id(user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario

