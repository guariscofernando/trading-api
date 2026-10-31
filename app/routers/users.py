# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app.dto.UserDTO import CambioPassword, UsuarioCreate, UsuarioResponse, UsuarioLogin
from app.dao.UserDAO import UserDAO
from datetime import datetime
from app.services import login_guard
from app.services.bus import bus
from app.services.ratelimit import ip_cliente
from utils.authorization import (
    HASH_FICTICIO, create_access_token, get_current_user, hash_password, verify_password,
)

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])
dao = UserDAO()

@router.post("/login")
def login(datos: UsuarioLogin, request: Request):
    ip = ip_cliente(request.scope)

    # Bloqueo por intentos fallidos (ver app/services/login_guard.py)
    espera = login_guard.segundos_de_bloqueo(ip, datos.username)
    if espera:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Intenta de nuevo en {espera} segundos.",
            headers={"Retry-After": str(espera)},
        )

    usuario = dao.obtener_usuario_por_username(datos.username)

    # Se verifica SIEMPRE un hash, exista o no el usuario: así ambos casos tardan lo mismo.
    hash_a_comparar = usuario["password_hash"] if usuario else HASH_FICTICIO
    contrasena_correcta = verify_password(datos.password, hash_a_comparar)

    if not usuario or not contrasena_correcta:
        login_guard.registrar_fallo(ip, datos.username)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    login_guard.registrar_exito(ip, datos.username)

    # Generar token
    token = create_access_token(data={"sub": str(usuario["id"]), "tv": usuario["token_version"]})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": usuario["id"],
            "username": usuario["username"],
            "email": usuario["email"],
            "rol": usuario["rol"]
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

@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Cierra TODAS tus sesiones: los tokens emitidos hasta ahora (de este y de cualquier otro dispositivo) dejan de valer
    al instante y se cierran tus WebSockets abiertos. Para volver a entrar hay que iniciar sesión otra vez.
    """
    await run_in_threadpool(dao.revocar_sesiones, current_user["id"])
    await bus.publicar("sesion_revocada", {"usuario_id": current_user["id"]})
    return {"mensaje": "Sesiones cerradas"}


@router.post("/cambiar-password")
async def cambiar_password(datos: CambioPassword, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Cambia tu contraseña. Exige la actual (un token robado no basta para quedarse con la cuenta) y revoca todas las
    sesiones; la respuesta trae un token nuevo para seguir en este dispositivo. Los intentos con la contraseña actual
    errónea cuentan en el mismo bloqueo que el login.
    """
    ip = ip_cliente(request.scope)
    username = current_user["username"]
    espera = await run_in_threadpool(login_guard.segundos_de_bloqueo, ip, username)
    if espera:
        raise HTTPException(status_code=429, detail=f"Demasiados intentos fallidos. Intenta de nuevo en {espera} segundos.",
                            headers={"Retry-After": str(espera)})

    if not await run_in_threadpool(verify_password, datos.password_actual, current_user["password_hash"]):
        await run_in_threadpool(login_guard.registrar_fallo, ip, username)
        raise HTTPException(status_code=403, detail="La contraseña actual no es correcta")
    if datos.password_nueva == datos.password_actual:
        raise HTTPException(status_code=422, detail="La contraseña nueva debe ser distinta de la actual")

    nuevo_hash = await run_in_threadpool(hash_password, datos.password_nueva)
    version = await run_in_threadpool(dao.cambiar_password, current_user["id"], current_user["password_hash"], nuevo_hash)
    if version is None:
        raise HTTPException(status_code=409, detail="Tu cuenta cambió mientras se procesaba la petición. Inténtalo de nuevo.")
    await run_in_threadpool(login_guard.registrar_exito, ip, username)
    await bus.publicar("sesion_revocada", {"usuario_id": current_user["id"]})
    token = create_access_token(data={"sub": str(current_user["id"]), "tv": version})
    return {"mensaje": "Contraseña cambiada; las demás sesiones se cerraron", "access_token": token, "token_type": "bearer"}


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
def obtener_usuario(user_id: int, current_user: dict = Depends(get_current_user)):
    # Cada usuario solo puede consultar su propio perfil (incluye el email).
    # Mismo 404 para "no existe" y "es de otro": no revela qué IDs existen.
    usuario = dao.obtener_usuario_por_id(user_id) if user_id == current_user["id"] else None
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return usuario

