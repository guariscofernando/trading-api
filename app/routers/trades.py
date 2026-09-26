# app/routers/trades.py
import csv
import io
import math
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from app.dto.TradeDTO import TradeCreate, TradeResponse, TradeUpdate
from app.dao.TradeDAO import TradeDAO
from datetime import datetime
from typing import List, Optional
from utils.authorization import get_current_user

router = APIRouter(prefix="/trades", tags=["Trades"])
dao = TradeDAO()

# READ (protegido - solo ver trades propios)
@router.get("/", response_model=List[TradeResponse])
def listar_trades(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    tipo: Optional[str] = None,
    activo: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Listar trades del usuario autenticado"""
    return dao.obtener_trades_db(
        usuario_id=current_user["id"],
        skip=skip,
        limit=limit,
        tipo=tipo,
        activo=activo
    )
   
# CREATE (protegido)
from app.routers.websocket import notification_manager

@router.post("/", response_model=TradeResponse, status_code=201)
async def crear_trade(
    trade: TradeCreate,
    current_user: dict = Depends(get_current_user)
):
    """Crear un trade (requiere autenticación)"""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    trade_id = dao.crear_trade_db(
        usuario_id=current_user["id"],
        tipo=trade.tipo,
        activo=trade.activo.upper(),
        precio=trade.precio,
        cantidad=trade.cantidad,
        fecha=fecha
    )

    resultado = {
        "id": trade_id,
        "usuario_id": current_user["id"],
        "tipo": trade.tipo,
        "activo": trade.activo.upper(),
        "precio": trade.precio,
        "cantidad": trade.cantidad,
        "fecha": fecha
    }

    await notification_manager.notificar(current_user["id"], {
        "tipo": "nuevo_trade",
        "mensaje": f"Nuevo trade registrado: {trade.tipo} {trade.cantidad} {trade.activo.upper()}",
        "datos": resultado
    })

    return resultado

@router.get("/buscar")
def buscar_trades(
    activo: Optional[str] = None,
    tipo: Optional[str] = None,
    precio_min: Optional[float] = None,
    precio_max: Optional[float] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None
):
    """Búsqueda avanzada con múltiples filtros"""

    trades = dao.obtener_trades_db(limit=10000)

    resultados = trades

    if activo:
        resultados = [t for t in resultados if t["activo"].upper() == activo.upper()]

    if tipo:
        resultados = [t for t in resultados if t["tipo"].lower() == tipo.lower()]

    if precio_min is not None:
        resultados = [t for t in resultados if t["precio"] >= precio_min]

    if precio_max is not None:
        resultados = [t for t in resultados if t["precio"] <= precio_max]

    if fecha_desde:
        resultados = [t for t in resultados if t["fecha"] >= fecha_desde]

    if fecha_hasta:
        resultados = [t for t in resultados if t["fecha"] <= fecha_hasta + " 23:59"]

    return resultados

@router.get("/exportar/csv")
def exportar_csv():
    """Exporta todos los trades a CSV"""
    trades = dao.obtener_trades_db(limit=10000)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Encabezado
    writer.writerow(["id", "tipo", "activo", "precio", "cantidad", "fecha"])
    
    # Datos
    for trade in trades:
        writer.writerow([
            trade["id"], trade["tipo"], trade["activo"],
            trade["precio"], trade["cantidad"], trade["fecha"]
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"}
    )

@router.get("/estadisticas")
def estadisticas():
    """Estadísticas generales del portfolio"""
    trades = dao.obtener_trades_db(limit=1000)
    
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

@router.get("/resumen/pnl")
def calcular_pnl():
    """Calcula el P&L total del portfolio"""
    trades = dao.obtener_trades_db(limit=1000)
    
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
    trades = dao.obtener_trades_db(limit=1000)
    
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
    return dao.trades_por_fecha_db(desde, hasta)

@router.get("/paginado")
def trades_paginado(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    orden: str = "fecha",
    direccion: str = "desc",
    current_user: dict = Depends(get_current_user)
):
    """Paginación avanzada con ordenamiento"""
    trades, total = dao.obtener_trades_paginado_db(
        usuario_id=current_user["id"],
        page=page,
        per_page=per_page,
        orden=orden,
        direccion=direccion
    )

    total_pages = math.ceil(total / per_page) if total > 0 else 0

    return {
        "data": trades,
        "paginacion": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "orden": orden,
            "direccion": direccion
        }
    }

"""
Exercise: Create a `/resumen/por-activo/{activo}` endpoint that returns:

    Total purchases of that asset
    Total sales of that asset
    P&L specific to that asset
    Average purchase and sale prices

Improve the Project
Add these enhancements to your Trading API:
1. Advanced search endpoint
2. Endpoint export to CSV
3. Add simple authentication using an API key
"""

@router.get("/resumen/por-activo/{activo}")
def resumen_por_activo(activo: str):
    """Obtiene estadísticas de un activo específico."""

    trades = dao.obtener_trades_db(limit=1000)

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

# READ (obtener uno)
@router.get("/{trade_id}", response_model=TradeResponse)
def obtener_trade(trade_id: int):
    trade = dao.obtener_trade_db(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    return trade

# UPDATE (protegido)
@router.patch("/{trade_id}", response_model=TradeResponse)
def actualizar_trade(
    trade_id: int,
    trade_update: TradeUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Actualizar un trade (solo si es del usuario autenticado)"""
    trade = dao.obtener_trade_db(trade_id)
    
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    
    # Verificar que el trade pertenezca al usuario
    if trade["usuario_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="No autorizado")
    
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
        dao.actualizar_trade_db(trade_id, **campos_a_actualizar)
    
    return dao.obtener_trade_db(trade_id)

# DELETE (protegido)
@router.delete("/{trade_id}")
def eliminar_trade(
    trade_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Eliminar un trade (solo si es del usuario autenticado)"""
    trade = dao.obtener_trade_db(trade_id)
    
    if not trade:
        raise HTTPException(status_code=404, detail="Trade no encontrado")
    
    if trade["usuario_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    dao.eliminar_trade_db(trade_id)
    return {"mensaje": f"Trade {trade_id} eliminado"}
