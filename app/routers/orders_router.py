# app/routers/orders_router.py
from fastapi import APIRouter, HTTPException, Depends
from app.dao.OrderDAO import OrderDAO
from app.dto.OrdersDTO import OrderCreate, OrderResponse
from app.services.binance_service import binance_service
from utils.authorization import get_current_user
from datetime import datetime

router = APIRouter(prefix="/orders", tags=["Orders"])
dao = OrderDAO()

@router.post("/", dependencies=[Depends(get_current_user)])
def place_order(order: OrderCreate, current_user: dict = Depends(get_current_user)):
    """Coloca una orden y la guarda en la base de datos"""
    try:
        # Colocar orden en Binance
        if order.order_type == "MARKET":
            result = binance_service.place_market_order(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity
            )
        elif order.order_type == "LIMIT":
            result = binance_service.place_limit_order(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price
            )
        elif order.order_type == "STOP_LOSS":
            result = binance_service.place_stop_loss_order(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                stop_price=order.stop_price
            )
        
        # Guardar en nuestra base de datos
        order_db_id = dao.crear_order_db(
            usuario_id=current_user["id"],
            binance_order_id=result.get('orderId'),
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            status=result.get('status', 'NEW'),
            quantity=order.quantity,
            price=order.price,
            stop_price=order.stop_price
        )
        
        return {
            "success": True,
            "message": "Orden colocada y registrada",
            "order_id_db": order_db_id,
            "binance_order": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/history", dependencies=[Depends(get_current_user)])
def get_orders_history(
    status: str = None,
    symbol: str = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Obtiene historial de órdenes del usuario"""
    orders = dao.obtener_orders_db(
        usuario_id=current_user["id"],
        status=status,
        symbol=symbol,
        skip=skip,
        limit=limit
    )
    return {
        "orders": orders,
        "count": len(orders)
    }

@router.post("/sync", dependencies=[Depends(get_current_user)])
def sync_orders():
    """Sincroniza el estado de órdenes con Binance"""
    from app.services.order_sync import sincronizar_ordenes
    return sincronizar_ordenes()

@router.get("/open", dependencies=[Depends(get_current_user)])
def get_open_orders(symbol: str = None):
    """Obtiene órdenes abiertas"""
    orders = binance_service.get_open_orders(symbol)
    return {
        "orders": orders,
        "count": len(orders)
    }

@router.delete("/{order_id}", dependencies=[Depends(get_current_user)])
def cancel_order(order_id: int, symbol: str):
    """Cancela una orden"""
    try:
        result = binance_service.cancel_order(symbol, order_id)
        return {
            "success": True,
            "message": f"Orden {order_id} cancelada",
            "result": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))