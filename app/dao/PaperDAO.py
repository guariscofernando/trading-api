# app/dao/PaperDAO.py
"""
Acceso a datos del paper trading.

Concurrencia: toda orden se ejecuta en UNA transacción que primero bloquea la fila de la billetera
del usuario (SELECT ... FOR UPDATE). Dos órdenes simultáneas del mismo usuario se ejecutan una detrás
de otra, así que no pueden gastar el mismo saldo ni vender la misma cantidad dos veces; y la
comprobación de client_order_id también queda dentro del bloqueo.
"""
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import session_scope
from app.models import PaperPosition, PaperTrade, PaperWallet, a_dict
from app.services import paper_trading as pt


def _asegurar_billetera(sesion, usuario_id: int, saldo_inicial: Decimal) -> PaperWallet:
    """Crea la billetera si no existe (sin error si dos peticiones la crean a la vez) y la devuelve bloqueada."""
    sesion.execute(
        pg_insert(PaperWallet)
        .values(usuario_id=usuario_id, balance_usdt=saldo_inicial, saldo_inicial=saldo_inicial)
        .on_conflict_do_nothing(index_elements=["usuario_id"])
    )
    return sesion.execute(
        select(PaperWallet).where(PaperWallet.usuario_id == usuario_id).with_for_update()
    ).scalar_one()


class PaperDAO:

    def obtener_billetera(self, usuario_id: int, saldo_inicial: Decimal) -> dict:
        with session_scope() as sesion:
            return a_dict(_asegurar_billetera(sesion, usuario_id, saldo_inicial))

    def obtener_posiciones(self, usuario_id: int) -> List[dict]:
        with session_scope() as sesion:
            filas = sesion.execute(
                select(PaperPosition).where(PaperPosition.usuario_id == usuario_id).order_by(PaperPosition.coin_id)
            ).scalars().all()
            return [a_dict(f) for f in filas]

    def obtener_historial(self, usuario_id: int, skip: int = 0, limit: int = 50) -> List[dict]:
        with session_scope() as sesion:
            filas = sesion.execute(
                select(PaperTrade).where(PaperTrade.usuario_id == usuario_id)
                .order_by(PaperTrade.id.desc()).offset(skip).limit(limit)
            ).scalars().all()
            return [a_dict(f) for f in filas]

    def pnl_realizado_total(self, usuario_id: int) -> Decimal:
        with session_scope() as sesion:
            total = sesion.execute(
                select(func.coalesce(func.sum(PaperTrade.pnl_realizado), 0)).where(PaperTrade.usuario_id == usuario_id)
            ).scalar_one()
            return Decimal(total)

    def ejecutar_orden(self, usuario_id: int, coin_id: str, side: str, cantidad: Decimal, precio_ref: Decimal,
                       saldo_inicial: Decimal, comision_pct: Decimal, slippage_pct: Decimal,
                       client_order_id: Optional[str] = None) -> dict:
        """Ejecuta la orden de forma atómica. Devuelve el trade, el saldo resultante y `repetida`."""
        with session_scope() as sesion:
            billetera = _asegurar_billetera(sesion, usuario_id, saldo_inicial)

            if client_order_id:
                previo = sesion.execute(
                    select(PaperTrade).where(PaperTrade.usuario_id == usuario_id,
                                             PaperTrade.client_order_id == client_order_id)
                ).scalar_one_or_none()
                if previo is not None:
                    if (previo.coin_id, previo.side, previo.cantidad) != (coin_id, side, cantidad):
                        raise pt.OrdenDuplicada("client_order_id ya usado con una orden distinta")
                    return {**a_dict(previo), "saldo": billetera.balance_usdt, "repetida": True}

            posicion = sesion.execute(
                select(PaperPosition).where(PaperPosition.usuario_id == usuario_id, PaperPosition.coin_id == coin_id)
            ).scalar_one_or_none()
            pos_cantidad = posicion.cantidad if posicion else Decimal(0)
            pos_medio = posicion.precio_medio if posicion else Decimal(0)

            if side == "BUY":
                r = pt.calcular_compra(billetera.balance_usdt, cantidad, precio_ref, comision_pct, slippage_pct,
                                       pos_cantidad, pos_medio)
            else:
                r = pt.calcular_venta(cantidad, precio_ref, comision_pct, slippage_pct,
                                      pos_cantidad, pos_medio, billetera.balance_usdt)

            billetera.balance_usdt = r["saldo"]
            if r["pos_cantidad"] > 0:
                if posicion is None:
                    sesion.add(PaperPosition(usuario_id=usuario_id, coin_id=coin_id,
                                             cantidad=r["pos_cantidad"], precio_medio=r["pos_precio_medio"]))
                else:
                    posicion.cantidad = r["pos_cantidad"]
                    posicion.precio_medio = r["pos_precio_medio"]
                    posicion.actualizado_en = func.current_timestamp()
            elif posicion is not None:
                sesion.delete(posicion)

            trade = PaperTrade(usuario_id=usuario_id, coin_id=coin_id, side=side, cantidad=cantidad,
                               precio=r["precio"], valor=r["valor"], comision=r["comision"],
                               pnl_realizado=r["pnl_realizado"], client_order_id=client_order_id)
            sesion.add(trade)
            sesion.flush()
            sesion.refresh(trade)
            return {**a_dict(trade), "saldo": r["saldo"], "repetida": False}

    def reiniciar(self, usuario_id: int, saldo_inicial: Decimal) -> dict:
        """Borra posiciones e historial y devuelve el saldo al inicial, todo en una transacción."""
        with session_scope() as sesion:
            billetera = _asegurar_billetera(sesion, usuario_id, saldo_inicial)
            sesion.execute(delete(PaperPosition).where(PaperPosition.usuario_id == usuario_id))
            sesion.execute(delete(PaperTrade).where(PaperTrade.usuario_id == usuario_id))
            billetera.balance_usdt = saldo_inicial
            billetera.saldo_inicial = saldo_inicial
            return a_dict(billetera)
