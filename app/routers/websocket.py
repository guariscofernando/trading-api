# app/routers/websocket.py
import asyncio
import json
import random
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, logger
from app.services.coingecko import obtener_precios_multiples
from typing import List
from typing import Dict
from utils.authorization import decode_access_token
from app.dao.UserDAO import UserDAO
from app.dao.TradeDAO import TradeDAO
from app.dao.WatchlistDAO import WatchlistDAO
from app.services.coingecko import obtener_precios_multiples
from app.routers.analisis import _calcular_pnl_por_activo, COIN_MAP

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
        """Envía una notificación a todas las conexiones activas de ese usuario"""
        conexiones_muertas = []
        for ws in self.conexiones.get(usuario_id, []):
            try:
                await ws.send_json(mensaje)
            except Exception:
                conexiones_muertas.append(ws)
        for ws in conexiones_muertas:
            self.disconnect(usuario_id, ws)

notification_manager = NotificationManager()
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
async def websocket_chat(websocket: WebSocket):
    """WebSocket de chat simple"""
    await manager.connect(websocket)
    
    try:
        while True:
            # Recibir mensaje del cliente
            data = await websocket.receive_text()
            
            # Broadcast a todos los clientes
            await manager.broadcast(f"Nuevo mensaje: {data}")
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.websocket("/ws/precios-reales")
async def websocket_precios_reales(websocket: WebSocket):
    """WebSocket con precios reales de CoinGecko"""
    await manager.connect(websocket)
    
    try:
        while True:
            # Obtener precios reales
            precios = await obtener_precios_multiples(
                ["bitcoin", "ethereum", "solana"]
            )
            
            if precios:
                datos = {}
                for coin_id, data in precios.items():
                    datos[coin_id] = {
                        "precio": data.get("usd", 0),
                        "cambio_24h": round(data.get("usd_24h_change", 0), 2)
                    }
                
                await websocket.send_json({
                    "tipo": "precios_reales",
                    "datos": datos
                })
            
            # Esperar 30 segundos (para no hacer rate limit)
            await asyncio.sleep(30)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

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