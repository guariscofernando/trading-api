# app/routers/websocket.py
import asyncio
import json
import random
import anyio
from app.config import config
from app.services.bus import bus
from app.services.ratelimit import golpear_sin_bloquear
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.coingecko import obtener_precios_multiples
from typing import List
from typing import Dict
from utils.authorization import decode_access_token
from app.dao.UserDAO import UserDAO
from app.dao.TradeDAO import TradeDAO
from app.dao.WatchlistDAO import WatchlistDAO
from app.services.coingecko import obtener_precios_multiples
from app.routers.analisis import _calcular_pnl_por_activo, COIN_MAP

logger = logging.getLogger("trading-api")

UMBRAL_PNL_SIGNIFICATIVO = 10  # porcentaje, para positivo o negativo

user_dao = UserDAO()
trade_dao = TradeDAO()
watchlist_dao = WatchlistDAO()

# Lista de clientes conectados
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: str):
        """Envía un mensaje a todos los clientes conectados"""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass
class NotificationManager:
    def __init__(self):
        self.conexiones: Dict[int, list] = {}

    async def connect(self, usuario_id: int, websocket: WebSocket):
        await websocket.accept()
        self.conexiones.setdefault(usuario_id, []).append(websocket)

    def disconnect(self, usuario_id: int, websocket: WebSocket):
        if usuario_id in self.conexiones:
            if websocket in self.conexiones[usuario_id]:
                self.conexiones[usuario_id].remove(websocket)
            if not self.conexiones[usuario_id]:
                del self.conexiones[usuario_id]

    async def notificar(self, usuario_id: int, mensaje: dict):
        """Envía una notificación a todas las conexiones activas de ese usuario, estén en el proceso que estén."""
        await bus.publicar("notif", {"usuario_id": usuario_id, "mensaje": mensaje})

    async def entregar_local(self, usuario_id: int, mensaje: dict):
        conexiones_muertas = []
        for ws in self.conexiones.get(usuario_id, []):
            try:
                await ws.send_json(mensaje)
            except Exception:
                conexiones_muertas.append(ws)
        for ws in conexiones_muertas:
            self.disconnect(usuario_id, ws)

class ChatManager:
    """Conexiones del chat. Aparte de ConnectionManager para que los mensajes del chat no lleguen
    a quien solo está viendo precios (antes compartían lista)."""
    TIMEOUT_ENVIO = 5   # segundos: un cliente lento no debe frenar al resto

    def __init__(self):
        self.conexiones: Dict[WebSocket, dict] = {}

    def conectadas_de(self, usuario_id: int) -> int:
        return sum(1 for u in self.conexiones.values() if u["id"] == usuario_id)

    async def connect(self, websocket: WebSocket, usuario: dict):
        await websocket.accept()
        self.conexiones[websocket] = {"id": usuario["id"], "username": usuario["username"]}

    def disconnect(self, websocket: WebSocket):
        self.conexiones.pop(websocket, None)

    async def _enviar(self, ws: WebSocket, mensaje: dict) -> bool:
        try:
            with anyio.fail_after(self.TIMEOUT_ENVIO):
                await ws.send_json(mensaje)
            return True
        except Exception:
            return False

    async def broadcast(self, mensaje: dict):
        """Publica el mensaje en el bus: llega a los clientes de TODOS los procesos."""
        await bus.publicar("chat", mensaje)

    async def entregar_local(self, mensaje: dict):
        conexiones = list(self.conexiones)
        resultados = await asyncio.gather(*(self._enviar(ws, mensaje) for ws in conexiones))
        for ws, ok in zip(conexiones, resultados):
            if not ok:
                self.disconnect(ws)


def _usuario_desde_token(token: str):
    """(usuario, motivo_de_rechazo). Mismas comprobaciones que get_current_user para HTTP."""
    payload = decode_access_token(token)
    if payload is None:
        return None, "Token inválido o expirado"
    user_id = payload.get("sub")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None, "Token inválido"
    usuario = user_dao.obtener_usuario_por_id(user_id)
    if usuario is None:
        return None, "Usuario no encontrado"
    return usuario, None


notification_manager = NotificationManager()
chat_manager = ChatManager()


async def _entregar_chat(datos: dict):
    await chat_manager.entregar_local(datos)


async def _entregar_notificacion(datos: dict):
    await notification_manager.entregar_local(int(datos["usuario_id"]), datos["mensaje"])


bus.registrar("chat", _entregar_chat)
bus.registrar("notif", _entregar_notificacion)
manager = ConnectionManager()
router = APIRouter(tags=["WebSocket"])

@router.websocket("/ws/precios")
async def websocket_precios(websocket: WebSocket):
    """WebSocket que envía precios actualizados cada 5 segundos"""
    await manager.connect(websocket)
    
    try:
        while True:
            # Obtener precios (simulado, podrías usar CoinGecko)
            precios = {
                "BTC": 50000 + random.randint(-1000, 1000),
                "ETH": 3000 + random.randint(-100, 100),
                "SOL": 100 + random.randint(-10, 10)
            }
            
            # Enviar precios al cliente
            await websocket.send_json({
                "tipo": "precios",
                "datos": precios
            })
            
            # Esperar 5 segundos
            await asyncio.sleep(5)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, token: str = ""):
    """
    Chat para usuarios autenticados: /ws/chat?token=<jwt> (mismo token que /ws/notificaciones).

    - Sin token válido el handshake se rechaza antes de aceptarlo (cierre 1008).
    - Límite por USUARIO (no por conexión: abrir más pestañas no da más cupo): CHAT_MAX_MESSAGES
      mensajes cada CHAT_WINDOW_SECONDS. Los que sobran se descartan con un aviso {"tipo": "error"}.
    - Un mensaje de más de CHAT_MAX_LENGTH caracteres cierra la conexión (1009).
    - Como máximo CHAT_MAX_CONNECTIONS_PER_USER conexiones simultáneas por usuario.
    - Cada mensaje se emite como JSON con el autor tomado del token, no de lo que diga el cliente.
    """
    usuario, motivo = _usuario_desde_token(token)
    if usuario is None:
        await websocket.close(code=1008, reason=motivo)
        return
    if chat_manager.conectadas_de(usuario["id"]) >= config.CHAT_MAX_CONNECTIONS_PER_USER:
        await websocket.close(code=1008, reason="Demasiadas conexiones abiertas")
        return

    await chat_manager.connect(websocket, usuario)
    try:
        await websocket.send_json({"tipo": "conexion", "mensaje": f"Conectado al chat como {usuario['username']}"})
        while True:
            texto = (await websocket.receive_text()).strip()
            if len(texto) > config.CHAT_MAX_LENGTH:
                await websocket.close(code=1009, reason="Mensaje demasiado largo")
                break
            if not texto:
                continue
            resultado = await golpear_sin_bloquear(
                f"chat:{usuario['id']}", config.CHAT_MAX_MESSAGES, config.CHAT_WINDOW_SECONDS)
            if resultado is not None and not resultado.permitido:
                await websocket.send_json({
                    "tipo": "error",
                    "mensaje": f"Estás enviando mensajes demasiado rápido. Espera {resultado.reinicia_en} segundos.",
                    "reintentar_en": resultado.reinicia_en,
                })
                continue
            await chat_manager.broadcast({"tipo": "mensaje", "usuario": usuario["username"], "mensaje": texto})
    except WebSocketDisconnect:
        pass
    finally:
        chat_manager.disconnect(websocket)


@router.websocket("/ws/notificaciones")
async def websocket_notificaciones(websocket: WebSocket, token: str):
    """WebSocket de notificaciones autenticado por token en query param"""
    payload = decode_access_token(token)

    if payload is None:
        await websocket.close(code=1008, reason="Token inválido o expirado")
        return

    user_id_str = payload.get("sub")
    if user_id_str is None:
        await websocket.close(code=1008, reason="Token inválido")
        return

    usuario = user_dao.obtener_usuario_por_id(int(user_id_str))
    if usuario is None:
        await websocket.close(code=1008, reason="Usuario no encontrado")
        return

    usuario_id = usuario["id"]
    await notification_manager.connect(usuario_id, websocket)

    try:
        await websocket.send_json({
            "tipo": "conexion",
            "mensaje": "Conectado a notificaciones"
        })
        while True:
            # Mantiene la conexión viva; no esperamos mensajes del cliente,
            # pero hay que seguir "escuchando" para detectar el disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_manager.disconnect(usuario_id, websocket)

async def verificar_alertas():
    """Tarea en background: revisa watchlist y P&L de todos los usuarios conectados"""
    while True:
        await asyncio.sleep(60)  # cada 60 segundos

        usuarios_conectados = list(notification_manager.conexiones.keys())

        for usuario_id in usuarios_conectados:
            try:
                # Si el usuario tiene conexiones en varios procesos, solo el primero en llegar revisa este ciclo
                # (ventana < 60 s: con un solo proceso siempre se permite).
                turno = await golpear_sin_bloquear(f"alertas:{usuario_id}", 1, 50)
                if turno is not None and not turno.permitido:
                    continue
                # 1. Chequear watchlist: precio objetivo alcanzado
                items_watchlist = watchlist_dao.obtener_por_usuario_db(usuario_id)
                if items_watchlist:
                    coin_ids = list(set(item["coin_id"] for item in items_watchlist))
                    precios = await obtener_precios_multiples(coin_ids)

                    if precios:
                        for item in items_watchlist:
                            precio_actual = precios.get(item["coin_id"], {}).get("usd")
                            if precio_actual is not None and precio_actual >= item["precio_alerta"]:
                                await notification_manager.notificar(usuario_id, {
                                    "tipo": "precio_objetivo",
                                    "mensaje": f"{item['coin_id']} alcanzó ${precio_actual}, tu alerta era ${item['precio_alerta']}",
                                    "coin_id": item["coin_id"],
                                    "precio_actual": precio_actual,
                                    "precio_alerta": item["precio_alerta"]
                                })

                # 2. Chequear P&L significativo
                trades = trade_dao.obtener_trades_db(usuario_id=usuario_id, limit=1000)
                if trades:
                    activos = list(set(t["activo"] for t in trades))
                    coin_ids_trades = [COIN_MAP.get(a, a.lower()) for a in activos]
                    precios_trades = await obtener_precios_multiples(coin_ids_trades)

                    if precios_trades:
                        pnl_por_activo = _calcular_pnl_por_activo(trades, precios_trades)
                        for activo, datos in pnl_por_activo.items():
                            if abs(datos["pnl_porcentaje"]) >= UMBRAL_PNL_SIGNIFICATIVO:
                                await notification_manager.notificar(usuario_id, {
                                    "tipo": "pnl_significativo",
                                    "mensaje": f"{activo}: P&L de {datos['pnl_porcentaje']}%",
                                    "activo": activo,
                                    "pnl_porcentaje": datos["pnl_porcentaje"]
                                })

            except Exception as e:
                logger.error(f"Error verificando alertas para usuario {usuario_id}: {e}")