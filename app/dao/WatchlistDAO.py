# app/dao/WatchlistDAO.py
import psycopg2
import psycopg2.extras
from app.connections.trading_db_conn import TradingConnection

class WatchlistDAO:

    def agregar_db(self, usuario_id, coin_id, precio_alerta):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO watchlist (usuario_id, coin_id, precio_alerta)
            VALUES (%s, %s, %s)
            RETURNING id
        ''', (usuario_id, coin_id, precio_alerta))

        item_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return item_id

    def obtener_por_usuario_db(self, usuario_id):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute(
            "SELECT * FROM watchlist WHERE usuario_id = %s ORDER BY creado_en DESC",
            (usuario_id,)
        )
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items