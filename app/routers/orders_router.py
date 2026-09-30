# app/routers/orders_router.py
from fastapi import APIRouter, HTTPException, Depends
from app.dto.OrdersDTO import OrderCreate, OrderResponse
from app.services.binance_service import binance_service
from utils.authorization import get_current_user
from datetime import datetime

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.post("/", dependencies=[Depends(get_current_user)])
def place_order(order: OrderCreate):
    """Coloca una orden en Binance Testnet"""
    try:
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
        
        return {
            "success": True,
            "message": "Orden colocada exitosamente",
            "order": result,
            "testnet": True
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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