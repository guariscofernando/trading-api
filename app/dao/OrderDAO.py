# app/dao/OrderDAO.py
from typing import Optional
import psycopg2
import psycopg2.extras
from app.connections.trading_db_conn import TradingConnection

class OrderDAO:

    def crear_order_db(self, usuario_id, binance_order_id, symbol, side, order_type, 
                    status, quantity, price=None, stop_price=None):
        """Inserta una orden en la base de datos"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO orders (
                usuario_id, binance_order_id, symbol, side, order_type,
                status, quantity, price, stop_price
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (usuario_id, binance_order_id, symbol, side, order_type,
            status, quantity, price, stop_price))
        
        order_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return order_id

    def obtener_orders_db(self, usuario_id=None, status=None, symbol=None, skip=0, limit=50):
        """Obtiene órdenes con filtros"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        query = "SELECT * FROM orders WHERE 1=1"
        params = []
        
        if usuario_id:
            query += " AND usuario_id = %s"
            params.append(usuario_id)
        
        if status:
            query += " AND status = %s"
            params.append(status)
        
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)
        
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, skip])
        
        cursor.execute(query, params)
        orders = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return orders

    def actualizar_order_status_db(self, binance_order_id, status, executed_qty=None):
        """Actualiza el estado de una orden"""
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        if executed_qty is not None:
            cursor.execute('''
                UPDATE orders 
                SET status = %s, executed_qty = %s, updated_at = CURRENT_TIMESTAMP
                WHERE binance_order_id = %s
            ''', (status, executed_qty, binance_order_id))
        else:
            cursor.execute('''
                UPDATE orders 
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE binance_order_id = %s
            ''', (status, binance_order_id))
        
        conn.commit()
        filas = cursor.rowcount
        conn.close()
        return filas > 0