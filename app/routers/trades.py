# app/routers/trades.py
from fastapi import APIRouter, HTTPException, Query
from app.models import TradeCreate, TradeResponse, TradeUpdate
from app.database import (
    get_connection,
    crear_trade_db,
    obtener_trades_db,
    obtener_trade_db,
    actualizar_trade_db,
    eliminar_trade_db
)
from datetime import datetime
from typing import List, Optional

router = APIRouter(prefix="/trades", tags=["Trades"])

# CREATE
@router.post("/", response_model=TradeResponse, status_code=201)
def crear_trade(trade: TradeCreate):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    trade_id = crear_trade_db(
        tipo=trade.tipo,
        activo=trade.activo.upper(),
        precio=trade.precio,
        cantidad=trade.cantidad,
        fecha=fecha
    )
    
    return {
        "id": trade_id,
        "tipo": trade.tipo,
        "activo": trade.activo.upper(),
        "precio": trade.precio,
        "cantidad": trade.cantidad,
        "fecha": fecha
    }

# READ (listar)
@router.get("/", response_model=List[TradeResponse])
def listar_trades(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    tipo: Optional[str] = None,
    activo: Optional[str] = None
):
    return obtener_trades_db(skip=skip, limit=limit, tipo=tipo, activo=activo)

# READ (obtener uno)
@router.get("/{trade_id}", response_model=TradeResponse)
def obtener_trade(trade_id: int):
    trade = obtener_trade_db(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    return trade

# UPDATE
@router.patch("/{trade_id}", response_model=TradeResponse)
def actualizar_trade(trade_id: int, trade_update: TradeUpdate):
    # Verificar que el trade existe
    trade = obtener_trade_db(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    
    # Actualizar solo los campos que se enviaron
    campos_a_actualizar = {}
    if trade_update.tipo is not None:
        campos_a_actualizar["tipo"] = trade_update.tipo
    if trade_update.activo is not None:
        campos_a_actualizar["activo"] = trade_update.activo.upper()
    if trade_update.precio is not None:
        campos_a_actualizar["precio"] = trade_update.precio
    if trade_update.cantidad is not None:
        campos_a_actualizar["cantidad"] = trade_update.cantidad
    
    if campos_a_actualizar:
        actualizar_trade_db(trade_id, **campos_a_actualizar)
    
    # Devolver el trade actualizado
    return obtener_trade_db(trade_id)

# DELETE
@router.delete("/{trade_id}")
def eliminar_trade(trade_id: int):
    trade = obtener_trade_db(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    
    eliminar_trade_db(trade_id)
    return {"mensaje": f"Trade {trade_id} eliminado"}

@router.get("/resumen/pnl")
def calcular_pnl():
    """Calcula el P&L total del portfolio"""
    trades = obtener_trades_db(limit=1000)
    
    pnl = 0
    por_activo = {}
    
    for trade in trades:
        valor = trade["precio"] * trade["cantidad"]
        
        if trade["tipo"] == "compra":
            pnl -= valor
        else:
            pnl += valor
        
        # Agrupar por activo
        activo = trade["activo"]
        if activo not in por_activo:
            por_activo[activo] = {"compras": 0, "ventas": 0, "pnl": 0}
        
        if trade["tipo"] == "compra":
            por_activo[activo]["compras"] += valor
            por_activo[activo]["pnl"] -= valor
        else:
            por_activo[activo]["ventas"] += valor
            por_activo[activo]["pnl"] += valor
    
    return {
        "pnl_total": round(pnl, 2),
        "por_activo": por_activo,
        "total_trades": len(trades)
    }

@router.get("/resumen/mejor-trade")
def mejor_trade():
    """Encuentra el trade con mayor ganancia"""
    trades = obtener_trades_db(limit=1000)
    
    if not trades:
        raise HTTPException(status_code=404, detail="No hay trades")
    
    # Para simplificar, asumimos que las ventas son ganancias
    ventas = [t for t in trades if t["tipo"] == "venta"]
    
    if not ventas:
        return {"mensaje": "No hay ventas registradas"}
    
    mejor = max(ventas, key=lambda t: t["precio"] * t["cantidad"])
    return mejor

@router.get("/resumen/por-fecha")
def trades_por_fecha(desde: Optional[str] = None, hasta: Optional[str] = None):
    """Obtiene trades en un rango de fechas"""
    # Formato de fecha: YYYY-MM-DD
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    
    if desde:
        query += " AND fecha >= ?"
        params.append(desde)
    
    if hasta:
        query += " AND fecha <= ?"
        params.append(hasta + " 23:59")
    
    query += " ORDER BY fecha DESC"
    
    cursor.execute(query, params)
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return trades

@router.get("/estadisticas")
def estadisticas():
    """Estadísticas generales del portfolio"""
    trades = obtener_trades_db(limit=1000)
    
    if not trades:
        return {"mensaje": "No hay trades registrados"}
    
    compras = [t for t in trades if t["tipo"] == "compra"]
    ventas = [t for t in trades if t["tipo"] == "venta"]
    
    volumen_total = sum(t["precio"] * t["cantidad"] for t in trades)
    
    return {
        "total_trades": len(trades),
        "total_compras": len(compras),
        "total_ventas": len(ventas),
        "volumen_total": round(volumen_total, 2),
        "precio_promedio_compra": round(
            sum(t["precio"] for t in compras) / len(compras), 2
        ) if compras else 0,
        "precio_promedio_venta": round(
            sum(t["precio"] for t in ventas) / len(ventas), 2
        ) if ventas else 0,
        "activos_operados": list(set(t["activo"] for t in trades))
    }

"""
Exercise: Create a `/resumen/por-activo/{activo}` endpoint that returns:

    Total purchases of that asset
    Total sales of that asset
    P&L specific to that asset
    Average purchase and sale prices
"""

@router.get("/resumen/por-activo/{activo}")
def resumen_por_activo(activo: str):
    """Obtiene estadísticas de un activo específico."""

    trades = obtener_trades_db(limit=1000)

    # Filtrar por activo
    trades_activo = [t for t in trades if t["activo"].upper() == activo.upper()]

    if not trades_activo:
        raise HTTPException(status_code=404,detail=f"No hay trades registrados para {activo.upper()}")

    compras = [t for t in trades_activo if t["tipo"] == "compra"]
    ventas = [t for t in trades_activo if t["tipo"] == "venta"]
    total_compras = sum(t["precio"] * t["cantidad"] for t in compras)
    total_ventas = sum(t["precio"] * t["cantidad"] for t in ventas)
    pnl = total_ventas - total_compras
    precio_promedio_compra = (sum(t["precio"] for t in compras) / len(compras) if compras else 0)
    precio_promedio_venta = (sum(t["precio"] for t in ventas) / len(ventas) if ventas else 0)

    return {
        "activo": activo.upper(),
        "total_compras": round(total_compras, 2),
        "total_ventas": round(total_ventas, 2),
        "pnl": round(pnl, 2),
        "precio_promedio_compra": round(precio_promedio_compra, 2),
        "precio_promedio_venta": round(precio_promedio_venta, 2),
    }