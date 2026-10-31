# app/dao/WatchlistDAO.py
from sqlalchemy import delete, func, select

from app.database import session_scope
from app.models import Usuario, WatchlistItem, a_dict


class WatchlistLlena(Exception):
    """El usuario ya tiene el máximo de monedas en su watchlist."""


class WatchlistDAO:

    def agregar_db(self, usuario_id, coin_id, precio_alerta, max_items=None):
        """Con `max_items`, comprueba el tope dentro de la misma transacción y bloqueando al usuario: dos altas
        simultáneas no pueden pasarse del máximo."""
        with session_scope() as sesion:
            if max_items is not None:
                sesion.execute(select(Usuario.id).where(Usuario.id == usuario_id).with_for_update())
                actuales = sesion.execute(
                    select(func.count()).select_from(WatchlistItem).where(WatchlistItem.usuario_id == usuario_id)
                ).scalar_one()
                if actuales >= max_items:
                    raise WatchlistLlena(f"Tu watchlist ya tiene {actuales} monedas (máximo {max_items}).")
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

    def eliminar_db(self, usuario_id, item_id) -> bool:
        """Borra una moneda de la watchlist del usuario. False si no existe o es de otro usuario."""
        with session_scope() as sesion:
            borradas = sesion.execute(
                delete(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.usuario_id == usuario_id)
            ).rowcount
            return borradas > 0
