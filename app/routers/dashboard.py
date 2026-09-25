# app/routers/dashboard.py
from fastapi import APIRouter, Depends
from utils.authorization import get_current_user
from app.dao.TradeDAO import TradeDAO
from app.services.coingecko import obtener_precios_multiples
from app.services.cache import cache
from datetime import datetime

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
dao = TradeDAO()

COIN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot"
}

@router.get("/completo")
async def dashboard_completo(current_user: dict = Depends(get_current_user)):
    """Dashboard completo con toda la información del usuario"""
    
    # Verificar caché
    cache_key = f"dashboard_{current_user['id']}"
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "from_cache": True}
    
    # Obtener trades del usuario
    trades = dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)
    
    # Obtener precios actuales
    activos = list(set(t["activo"] for t in trades))
    coin_ids = [COIN_MAP.get(a, a.lower()) for a in activos]
    precios = await obtener_precios_multiples(coin_ids) if coin_ids else {}
    
    # Calcular estadísticas
    total_compras = sum(1 for t in trades if t["tipo"] == "compra")
    total_ventas = sum(1 for t in trades if t["tipo"] == "venta")
    volumen_total = sum(t["precio"] * t["cantidad"] for t in trades)
    
    # Calcular P&L por activo
    pnl_por_activo = {}
    for trade in trades:
        activo = trade["activo"]
        coin_id = COIN_MAP.get(activo, activo.lower())
        precio_actual = precios.get(coin_id, {}).get("usd", 0)
        
        if activo not in pnl_por_activo:
            pnl_por_activo[activo] = {
                "cantidad": 0,
                "costo": 0,
                "valor_actual": 0,
                "precio_actual": precio_actual
            }
        
        if trade["tipo"] == "compra":
            pnl_por_activo[activo]["cantidad"] += trade["cantidad"]
            pnl_por_activo[activo]["costo"] += trade["precio"] * trade["cantidad"]
        else:
            pnl_por_activo[activo]["cantidad"] -= trade["cantidad"]
            pnl_por_activo[activo]["costo"] -= trade["precio"] * trade["cantidad"]
    
    # Calcular P&L
    pnl_total = 0
    for activo, datos in pnl_por_activo.items():
        datos["valor_actual"] = datos["cantidad"] * datos["precio_actual"]
        datos["pnl"] = datos["valor_actual"] - datos["costo"]
        datos["pnl_pct"] = round(
            (datos["pnl"] / datos["costo"] * 100) if datos["costo"] > 0 else 0, 2
        )
        pnl_total += datos["pnl"]
    
    dashboard = {
        "usuario": {
            "id": current_user["id"],
            "username": current_user["username"]
        },
        "resumen": {
            "total_trades": len(trades),
            "total_compras": total_compras,
            "total_ventas": total_ventas,
            "volumen_total": round(volumen_total, 2),
            "pnl_total": round(pnl_total, 2),
            "activos_operados": len(pnl_por_activo)
        },
        "por_activo": pnl_por_activo,
        "ultimos_trades": trades[:5],
        "generado_en": datetime.now().isoformat()
    }
    
    # Guardar en caché por 30 segundos
    cache.set(cache_key, dashboard, ttl_seconds=30)
    
    return dashboard