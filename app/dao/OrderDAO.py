# app/dao/OrderDAO.py
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update

from app.database import session_scope
from app.models import Order, a_dict


class OrderDAO:

    def crear_order_db(self, usuario_id, binance_order_id, symbol, side, order_type,
                       status, quantity, price=None, stop_price=None):
        """Inserta una orden en la base de datos"""
        with session_scope() as sesion:
            orden = Order(
                usuario_id=usuario_id, binance_order_id=binance_order_id, symbol=symbol,
                side=side, order_type=order_type, status=status,
                quantity=quantity, price=price, stop_price=stop_price,
            )
            sesion.add(orden)
            sesion.flush()
            return orden.id

    def obtener_orders_db(self, usuario_id=None, status=None, symbol=None, skip=0, limit=50):
        """Obtiene órdenes con filtros"""
        consulta = select(Order)
        if usuario_id is not None:
            consulta = consulta.where(Order.usuario_id == usuario_id)
        if status:
            consulta = consulta.where(Order.status == status)
        if symbol:
            consulta = consulta.where(Order.symbol == symbol)
        consulta = consulta.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(skip)

        with session_scope() as sesion:
            return [a_dict(o) for o in sesion.execute(consulta).scalars()]

    def actualizar_order_status_db(self, binance_order_id, status, executed_qty: Optional[object] = None):
        """Actualiza el estado de una orden"""
        valores = {"status": status, "updated_at": func.current_timestamp()}
        if executed_qty is not None:
            valores["executed_qty"] = Decimal(str(executed_qty))   # Binance lo envía como texto

        with session_scope() as sesion:
            resultado = sesion.execute(
                update(Order).where(Order.binance_order_id == binance_order_id).values(**valores)
            )
            return resultado.rowcount > 0
