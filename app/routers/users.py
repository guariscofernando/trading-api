# app/routers/users.py
from fastapi import APIRouter, HTTPException
from app.dto.UserDTO import UsuarioCreate, UsuarioResponse
from app.dao.UserDAO import UserDAO
from datetime import datetime
from utils.authorization import hash_password

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])
dao = UserDAO()

@router.post("/registro", response_model=UsuarioResponse, status_code=201)
def registrar_usuario(usuario: UsuarioCreate):
    # Verificar si el username ya existe
    if dao.obtener_usuario_por_username(usuario.username):
        raise HTTPException(status_code=400, detail="Username ya registrado")
    
    # Verificar si el email ya existe
    if dao.obtener_usuario_por_email(usuario.email):
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    # Hashear la contraseña
    password_hash = hash_password(usuario.password)
    
    # Crear usuario
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

@router.get("/{user_id}", response_model=UsuarioResponse)
def obtener_usuario(user_id: int):
    usuario = dao.obtener_usuario_por_id(user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario