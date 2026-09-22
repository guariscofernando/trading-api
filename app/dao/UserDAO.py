#app/dao/UserDAO.py
import sqlite3
from app.connections.trading_db_conn import TradingConnection

class UserDAO:

    def crear_usuario_db(self, username, email, password_hash):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO usuarios (username, email, password_hash)
                VALUES (?, ?, ?)
            ''', (username, email, password_hash))
            
            user_id = cursor.lastrowid
            conn.commit()
            return user_id
        except sqlite3.IntegrityError:
            return None  # Username o email ya existe
        finally:
            conn.close()

    def obtener_usuario_por_username(self, username):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def obtener_usuario_por_email(self, email):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def obtener_usuario_por_id(self, user_id):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None