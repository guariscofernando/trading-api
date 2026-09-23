# app/database.py
from typing import Optional
import psycopg2
import psycopg2.extras
from app.connections.trading_db_conn import TradingConnection

class TradeDAO:

    def crear_trade_db(self, usuario_id, tipo, activo, precio, cantidad, fecha):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (usuario_id, tipo, activo, precio, cantidad, fecha)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (usuario_id, tipo, activo, precio, cantidad, fecha))
        
        trade_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return trade_id

    def obtener_trades_db(self, usuario_id=None, skip=0, limit=10, tipo=None, activo=None):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if usuario_id:
            query += " AND usuario_id = %s"
            params.append(usuario_id)
        
        if tipo:
            query += " AND tipo = %s"
            params.append(tipo)
        
        if activo:
            query += " AND activo = %s"
            params.append(activo.upper())
        
        query += " ORDER BY fecha DESC LIMIT %s OFFSET %s"
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

    def obtener_trades_con_usuario_db(self, usuario_id=None, skip=0, limit=10):
        """Obtiene trades junto con la info del usuario"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        query = '''
            SELECT trades.*, usuarios.username, usuarios.email
            FROM trades
            JOIN usuarios ON trades.usuario_id = usuarios.id
            WHERE 1=1
        '''
        params = []
        
        if usuario_id:
            query += " AND trades.usuario_id = %s"
            params.append(usuario_id)
        
        query += " ORDER BY trades.fecha DESC LIMIT %s OFFSET %s"
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades


    def obtener_trade_db(self, trade_id):
        """Obtiene un trade específico"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("SELECT * FROM trades WHERE id = %s", (trade_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None

    def actualizar_trade_db(self, trade_id, **kwargs):
        """Actualiza campos de un trade"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        # Construir la query dinámicamente
        campos = []
        valores = []
        for campo, valor in kwargs.items():
            if valor is not None:
                campos.append(f"{campo} = %s")
                valores.append(valor)
        
        if not campos:
            return False
        
        query = f"UPDATE trades SET {', '.join(campos)} WHERE id = %s"
        valores.append(trade_id)
        
        cursor.execute(query, valores)
        conn.commit()
        filas_afectadas = cursor.rowcount
        conn.close()
        
        return filas_afectadas > 0

    def eliminar_trade_db(self, trade_id):
        """Elimina un trade"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM trades WHERE id = %s", (trade_id,))
        conn.commit()
        filas_afectadas = cursor.rowcount
        conn.close()
        
        return filas_afectadas > 0

    def trades_por_fecha_db(self, desde: Optional[str] = None, hasta: Optional[str] = None):
        """Obtiene trades en un rango de fechas"""
        # Formato de fecha: YYYY-MM-DD
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if desde:
            query += " AND fecha >= %s"
            params.append(desde)
        
        if hasta:
            query += " AND fecha <= %s"
            params.append(hasta + " 23:59")
        
        query += " ORDER BY fecha DESC"
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return trades