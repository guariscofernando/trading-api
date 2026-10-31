# app/dao/PaperDAO.py
"""
Acceso a datos del paper trading.

Concurrencia: toda orden se ejecuta en UNA transacción que primero bloquea la fila de la billetera
del usuario (SELECT ... FOR UPDATE). Dos órdenes simultáneas del mismo usuario se ejecutan una detrás
de otra, así que no pueden gastar el mismo saldo ni vender la misma cantidad dos veces; y la
comprobación de client_order_id también queda dentro del bloqueo.
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import session_scope
from app.models import PaperOrder, PaperPosition, PaperTrade, PaperWallet, a_dict
from app.services import paper_trading as pt

logger = logging.getLogger("trading-api")


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

    @staticmethod
    def _aplicar(sesion, billetera, usuario_id, coin_id, side, cantidad, precio_ref, comision_pct, slippage_pct,
                 client_order_id=None) -> dict:
        """Mueve saldo, posición y registra el trade. Debe llamarse con la billetera YA bloqueada."""
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

            return self._aplicar(sesion, billetera, usuario_id, coin_id, side, cantidad, precio_ref,
                                 comision_pct, slippage_pct, client_order_id)

    # ------------------------------------------------------------------ órdenes pendientes (LIMIT / STOP)

    def crear_pendiente(self, usuario_id: int, coin_id: str, side: str, tipo: str, cantidad: Decimal, precio: Decimal,
                        saldo_inicial: Decimal, max_abiertas: int, client_order_id: Optional[str] = None) -> dict:
        """Registra una orden pendiente (idempotente por client_order_id). Devuelve la orden y `repetida`."""
        with session_scope() as sesion:
            _asegurar_billetera(sesion, usuario_id, saldo_inicial)       # serializa las altas del mismo usuario
            if client_order_id:
                previa = sesion.execute(
                    select(PaperOrder).where(PaperOrder.usuario_id == usuario_id,
                                             PaperOrder.client_order_id == client_order_id)
                ).scalar_one_or_none()
                if previa is not None:
                    if (previa.coin_id, previa.side, previa.tipo, previa.cantidad, previa.precio) != \
                            (coin_id, side, tipo, cantidad, precio):
                        raise pt.OrdenDuplicada("client_order_id ya usado con una orden distinta")
                    return {**a_dict(previa), "repetida": True}
            abiertas = sesion.execute(
                select(func.count()).select_from(PaperOrder)
                .where(PaperOrder.usuario_id == usuario_id, PaperOrder.estado == "ABIERTA")
            ).scalar_one()
            if abiertas >= max_abiertas:
                raise pt.LimiteDeOrdenes(f"Ya tienes {abiertas} órdenes abiertas (máximo {max_abiertas}). Cancela alguna.")
            orden = PaperOrder(usuario_id=usuario_id, coin_id=coin_id, side=side, tipo=tipo, cantidad=cantidad,
                               precio=precio, client_order_id=client_order_id)
            sesion.add(orden)
            sesion.flush()
            sesion.refresh(orden)
            return {**a_dict(orden), "repetida": False}

    def listar_pendientes(self, usuario_id: int, estado: Optional[str] = None, skip: int = 0, limit: int = 50) -> List[dict]:
        with session_scope() as sesion:
            consulta = select(PaperOrder).where(PaperOrder.usuario_id == usuario_id)
            if estado:
                consulta = consulta.where(PaperOrder.estado == estado)
            filas = sesion.execute(consulta.order_by(PaperOrder.id.desc()).offset(skip).limit(limit)).scalars().all()
            return [a_dict(f) for f in filas]

    def cancelar_pendiente(self, usuario_id: int, orden_id: int) -> Optional[dict]:
        """Cancela una orden ABIERTA propia. None si no existe (o es de otro); PaperError si ya no estaba abierta."""
        with session_scope() as sesion:
            orden = sesion.execute(
                select(PaperOrder).where(PaperOrder.id == orden_id, PaperOrder.usuario_id == usuario_id).with_for_update()
            ).scalar_one_or_none()
            if orden is None:
                return None
            if orden.estado != "ABIERTA":
                raise pt.OrdenNoAbierta(f"La orden ya está {orden.estado}")
            orden.estado = "CANCELADA"
            orden.cerrada_en = func.current_timestamp()
            sesion.flush()
            sesion.refresh(orden)
            return a_dict(orden)

    def monedas_con_ordenes_abiertas(self) -> List[str]:
        with session_scope() as sesion:
            return list(sesion.execute(
                select(PaperOrder.coin_id).where(PaperOrder.estado == "ABIERTA").distinct()).scalars().all())

    def procesar_pendientes(self, precios: Dict[str, Decimal], comision_pct: Decimal, slippage_pct: Decimal,
                            saldo_inicial: Decimal, max_ordenes: int = 500) -> dict:
        """
        Ejecuta las órdenes abiertas que el precio de mercado dispara. Cada una va en SU transacción: un fallo
        no afecta a las demás. Seguro con varios procesos a la vez (ver _procesar_una).
        """
        resumen = {"ejecutadas": 0, "rechazadas": 0, "errores": 0}
        with session_scope() as sesion:
            candidatas = sesion.execute(
                select(PaperOrder.id, PaperOrder.usuario_id, PaperOrder.coin_id, PaperOrder.side, PaperOrder.tipo,
                       PaperOrder.precio)
                .where(PaperOrder.estado == "ABIERTA", PaperOrder.coin_id.in_(list(precios) or [""]))
                .order_by(PaperOrder.id).limit(max_ordenes * 4)
            ).all()
        procesadas = 0
        for orden_id, usuario_id, coin_id, side, tipo, precio in candidatas:
            if procesadas >= max_ordenes:
                break
            mercado = precios.get(coin_id)
            if mercado is None or not pt.se_dispara(tipo, side, mercado, precio):
                continue
            procesadas += 1
            try:
                resultado = self._procesar_una(orden_id, usuario_id, mercado, comision_pct, slippage_pct, saldo_inicial)
            except Exception:
                logger.exception("Paper trading: error procesando la orden pendiente %s", orden_id)
                resumen["errores"] += 1
                if self._anotar_fallo(orden_id):
                    resumen["rechazadas"] += 1
                continue
            self._fallos.pop(orden_id, None)
            if resultado:
                resumen[resultado] += 1
        return resumen

    # Orden "venenosa": si falla con una excepción inesperada MAX_FALLOS ciclos seguidos se rechaza, en vez de
    # reintentarse (y llenar el log) para siempre. El contador es por proceso: basta, porque solo busca cortar el bucle.
    MAX_FALLOS = 5
    _fallos: Dict[int, int] = {}

    def _anotar_fallo(self, orden_id) -> bool:
        """Cuenta el fallo; al llegar al tope cierra la orden como RECHAZADA. Devuelve si la cerró."""
        self._fallos[orden_id] = self._fallos.get(orden_id, 0) + 1
        if self._fallos[orden_id] < self.MAX_FALLOS:
            return False
        self._fallos.pop(orden_id, None)
        try:
            with session_scope() as sesion:
                cerradas = sesion.execute(
                    update(PaperOrder).where(PaperOrder.id == orden_id, PaperOrder.estado == "ABIERTA")
                    .values(estado="RECHAZADA", motivo="Error interno al procesar la orden", cerrada_en=func.current_timestamp())
                ).rowcount
        except Exception:
            logger.exception("Paper trading: no se pudo cerrar la orden venenosa %s", orden_id)
            return False
        logger.error("Paper trading: orden %s rechazada tras %d fallos internos seguidos", orden_id, self.MAX_FALLOS)
        return bool(cerradas)

    @staticmethod
    def _procesar_una(orden_id, usuario_id, mercado, comision_pct, slippage_pct, saldo_inicial) -> Optional[str]:
        """
        Devuelve 'ejecutadas', 'rechazadas' o None (otro proceso se la llevó o ya no está abierta).
        Orden de bloqueos: SIEMPRE billetera primero y orden después (igual que reiniciar): así no hay interbloqueos.
        SKIP LOCKED: si otro proceso está ejecutando esta misma orden, se salta en vez de esperar, y la
        comprobación de estado dentro del bloqueo garantiza que nadie la ejecuta dos veces.
        """
        with session_scope() as sesion:
            billetera = _asegurar_billetera(sesion, usuario_id, saldo_inicial)
            orden = sesion.execute(
                select(PaperOrder).where(PaperOrder.id == orden_id, PaperOrder.estado == "ABIERTA")
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if orden is None or not pt.se_dispara(orden.tipo, orden.side, mercado, orden.precio):
                return None
            precio_ref, slippage = pt.parametros_de_relleno(orden.tipo, mercado, orden.precio, slippage_pct)
            try:
                with sesion.begin_nested():       # si la ejecución falla se deshace solo ella, no el rechazo
                    trade = PaperDAO._aplicar(sesion, billetera, usuario_id, orden.coin_id, orden.side, orden.cantidad,
                                              precio_ref, comision_pct, slippage)
            except pt.PaperError as e:
                orden.estado, orden.motivo = "RECHAZADA", str(e)[:200]
                orden.cerrada_en = func.current_timestamp()
                logger.info("Paper trading: orden %s rechazada: %s", orden_id, e)
                return "rechazadas"
            orden.estado, orden.trade_id = "EJECUTADA", trade["id"]
            orden.cerrada_en = func.current_timestamp()
            logger.info("Paper trading: orden %s (%s %s %s) ejecutada a %s", orden_id, orden.tipo, orden.side,
                        orden.coin_id, trade["precio"])
            return "ejecutadas"

    def reiniciar(self, usuario_id: int, saldo_inicial: Decimal) -> dict:
        """Borra posiciones, órdenes pendientes e historial y devuelve el saldo al inicial, todo en una transacción."""
        with session_scope() as sesion:
            billetera = _asegurar_billetera(sesion, usuario_id, saldo_inicial)
            sesion.execute(delete(PaperPosition).where(PaperPosition.usuario_id == usuario_id))
            sesion.execute(delete(PaperOrder).where(PaperOrder.usuario_id == usuario_id))
            sesion.execute(delete(PaperTrade).where(PaperTrade.usuario_id == usuario_id))
            billetera.balance_usdt = saldo_inicial
            billetera.saldo_inicial = saldo_inicial
            return a_dict(billetera)
