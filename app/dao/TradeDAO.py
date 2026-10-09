# app/dao/TradeDAO.py
from datetime import date, datetime, time
from typing import Optional, Union

from sqlalchemy import delete, func, select, update

from app.database import session_scope
from app.models import Trade, Usuario, a_dict

FORMATO_FECHA = "%Y-%m-%d %H:%M"
CAMPOS_ACTUALIZABLES = {"tipo", "activo", "precio", "cantidad"}
COLUMNAS_ORDENABLES = {"id", "tipo", "activo", "precio", "cantidad", "fecha"}


def _trade_a_dict(trade) -> dict:
    """Misma forma que antes: precio y cantidad como float, fecha como datetime."""
    d = a_dict(trade)
    d["precio"] = float(d["precio"])
    d["cantidad"] = float(d["cantidad"])
    return d


def _a_datetime(valor: Union[str, date, datetime], fin_de_dia: bool = False) -> datetime:
    """
    Acepta 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD' (formato ISO), date o datetime.
    Una fecha sin hora es el inicio del día o, con fin_de_dia, el último instante de ese día.
    Lanza ValueError si el texto no es una fecha.
    """
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime.combine(valor, time.max if fin_de_dia else time.min)
    texto = str(valor).strip()
    try:
        return datetime.strptime(texto, FORMATO_FECHA)
    except ValueError:
        pass
    try:                                     # solo fecha ('2026-01-31')
        return _a_datetime(date.fromisoformat(texto), fin_de_dia)
    except ValueError:
        raise ValueError(f"Fecha inválida: '{texto}'. Usa YYYY-MM-DD")


class TradeDAO:

    def crear_trade_db(self, usuario_id, tipo, activo, precio, cantidad, fecha):
        with session_scope() as sesion:
            trade = Trade(
                usuario_id=usuario_id, tipo=tipo, activo=activo,
                precio=precio, cantidad=cantidad, fecha=_a_datetime(fecha),
            )
            sesion.add(trade)
            sesion.flush()
            return trade.id

    def obtener_trades_db(self, usuario_id=None, skip=0, limit=10, tipo=None, activo=None):
        consulta = select(Trade)
        if usuario_id is not None:
            consulta = consulta.where(Trade.usuario_id == usuario_id)
        if tipo:
            consulta = consulta.where(Trade.tipo == tipo)
        if activo:
            consulta = consulta.where(Trade.activo == activo.upper())
        consulta = consulta.order_by(Trade.fecha.desc(), Trade.id.desc()).limit(limit).offset(skip)

        with session_scope() as sesion:
            return [_trade_a_dict(t) for t in sesion.execute(consulta).scalars()]

    def buscar_trades_db(self, usuario_id, activo=None, tipo=None, precio_min=None, precio_max=None,
                         fecha_desde=None, fecha_hasta=None, limit=10000):
        """Búsqueda con todos los filtros resueltos en SQL (nada se filtra en memoria)."""
        consulta = select(Trade).where(Trade.usuario_id == usuario_id)
        if activo:
            consulta = consulta.where(Trade.activo == activo.upper())
        if tipo:
            consulta = consulta.where(Trade.tipo == tipo.lower())
        if precio_min is not None:
            consulta = consulta.where(Trade.precio >= precio_min)
        if precio_max is not None:
            consulta = consulta.where(Trade.precio <= precio_max)
        if fecha_desde is not None:
            consulta = consulta.where(Trade.fecha >= _a_datetime(fecha_desde))
        if fecha_hasta is not None:
            consulta = consulta.where(Trade.fecha <= _a_datetime(fecha_hasta, fin_de_dia=True))
        consulta = consulta.order_by(Trade.fecha.desc(), Trade.id.desc()).limit(limit)

        with session_scope() as sesion:
            return [_trade_a_dict(t) for t in sesion.execute(consulta).scalars()]

    def obtener_trades_con_usuario_db(self, usuario_id=None, skip=0, limit=10):
        """Obtiene trades junto con la info del usuario"""
        consulta = select(Trade, Usuario.username, Usuario.email).join(Usuario, Trade.usuario_id == Usuario.id)
        if usuario_id is not None:
            consulta = consulta.where(Trade.usuario_id == usuario_id)
        consulta = consulta.order_by(Trade.fecha.desc(), Trade.id.desc()).limit(limit).offset(skip)

        with session_scope() as sesion:
            return [
                {**_trade_a_dict(trade), "username": username, "email": email}
                for trade, username, email in sesion.execute(consulta).all()
            ]

    def obtener_trade_db(self, trade_id):
        """Obtiene un trade específico"""
        with session_scope() as sesion:
            trade = sesion.get(Trade, trade_id)
            return _trade_a_dict(trade) if trade else None

    def actualizar_trade_db(self, trade_id, **kwargs):
        """Actualiza campos de un trade. Solo se aceptan tipo, activo, precio y cantidad."""
        desconocidos = set(kwargs) - CAMPOS_ACTUALIZABLES
        if desconocidos:
            raise ValueError(f"Campos no actualizables: {', '.join(sorted(desconocidos))}")
        valores = {k: v for k, v in kwargs.items() if v is not None}
        if not valores:
            return False

        with session_scope() as sesion:
            resultado = sesion.execute(update(Trade).where(Trade.id == trade_id).values(**valores))
            return resultado.rowcount > 0

    def eliminar_trade_db(self, trade_id):
        """Elimina un trade"""
        with session_scope() as sesion:
            resultado = sesion.execute(delete(Trade).where(Trade.id == trade_id))
            return resultado.rowcount > 0

    def trades_por_fecha_db(self, desde: Optional[Union[str, date]] = None,
                            hasta: Optional[Union[str, date]] = None,
                            usuario_id: Optional[int] = None):
        """Trades en un rango de fechas (inclusive), opcionalmente de un solo usuario."""
        consulta = select(Trade)
        if usuario_id is not None:
            consulta = consulta.where(Trade.usuario_id == usuario_id)
        if desde:
            consulta = consulta.where(Trade.fecha >= _a_datetime(desde))
        if hasta:
            consulta = consulta.where(Trade.fecha <= _a_datetime(hasta, fin_de_dia=True))
        consulta = consulta.order_by(Trade.fecha.desc(), Trade.id.desc())

        with session_scope() as sesion:
            return [_trade_a_dict(t) for t in sesion.execute(consulta).scalars()]

    def obtener_trades_paginado_db(self, usuario_id, page=1, per_page=20, orden="fecha", direccion="desc"):
        """Trades paginados y ordenados. Devuelve (trades, total)."""
        if orden not in COLUMNAS_ORDENABLES:
            orden = "fecha"
        columna = getattr(Trade, orden)
        criterio = columna.asc() if direccion.lower() == "asc" else columna.desc()
        offset = (page - 1) * per_page

        with session_scope() as sesion:
            total = sesion.execute(
                select(func.count()).select_from(Trade).where(Trade.usuario_id == usuario_id)
            ).scalar_one()
            filas = sesion.execute(
                select(Trade).where(Trade.usuario_id == usuario_id)
                .order_by(criterio, Trade.id.desc()).limit(per_page).offset(offset)
            ).scalars()
            return [_trade_a_dict(t) for t in filas], total
