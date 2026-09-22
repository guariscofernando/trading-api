# app/database.py
from typing import Optional
from app.connections.trading_db_conn import TradingConnection

class TradeDAO:

    def crear_trade_db(self, usuario_id, tipo, activo, precio, cantidad, fecha):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (usuario_id, tipo, activo, precio, cantidad, fecha)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (usuario_id, tipo, activo, precio, cantidad, fecha))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return trade_id

    def obtener_trades_db(self, usuario_id=None, skip=0, limit=10, tipo=None, activo=None):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if usuario_id:
            query += " AND usuario_id = ?"
            params.append(usuario_id)
        
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)
        
        if activo:
            query += " AND activo = ?"
            params.append(activo.upper())
        
        query += " ORDER BY fecha DESC LIMIT ? OFFSET ?"
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

    def obtener_trades_con_usuario_db(self, usuario_id=None, skip=0, limit=10):
        """Obtiene trades junto con la info del usuario"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT trades.*, usuarios.username, usuarios.email
            FROM trades
            JOIN usuarios ON trades.usuario_id = usuarios.id
            WHERE 1=1
        '''
        params = []
        
        if usuario_id:
            query += " AND trades.usuario_id = ?"
            params.append(usuario_id)
        
        query += " ORDER BY trades.fecha DESC LIMIT ? OFFSET ?"
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades


    def obtener_trade_db(self, trade_id):
        """Obtiene un trade específico"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
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
                campos.append(f"{campo} = ?")
                valores.append(valor)
        
        if not campos:
            return False
        
        query = f"UPDATE trades SET {', '.join(campos)} WHERE id = ?"
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
        
        cursor.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
        filas_afectadas = cursor.rowcount
        conn.close()
        
        return filas_afectadas > 0

    def trades_por_fecha_db(self, desde: Optional[str] = None, hasta: Optional[str] = None):
        """Obtiene trades en un rango de fechas"""
        # Formato de fecha: YYYY-MM-DD
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if desde:
            query += " AND fecha >= ?"
            params.append(desde)
        
        if hasta:
            query += " AND fecha <= ?"
            params.append(hasta + " 23:59")
        
        query += " ORDER BY fecha DESC"
        
        cursor.execute(query, params)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return trades