# app/routers/websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.coingecko import obtener_precios_multiples
from typing import List
import asyncio
import json
import random

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