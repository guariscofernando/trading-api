# app/dao/WatchlistDAO.py
from sqlalchemy import select

from app.database import session_scope
from app.models import WatchlistItem, a_dict


class WatchlistDAO:

    def agregar_db(self, usuario_id, coin_id, precio_alerta):
        with session_scope() as sesion:
            item = WatchlistItem(usuario_id=usuario_id, coin_id=coin_id, precio_alerta=precio_alerta)
            sesion.add(item)
            sesion.flush()
            return item.id

    def obtener_por_usuario_db(self, usuario_id):
        with session_scope() as sesion:
            filas = sesion.execute(
                select(WatchlistItem)
                .where(WatchlistItem.usuario_id == usuario_id)
                .order_by(WatchlistItem.creado_en.desc(), WatchlistItem.id.desc())
            ).scalars()
            return [a_dict(f) for f in filas]
