#app/dao/UserDAO.py
import psycopg2
import psycopg2.extras
from app.connections.trading_db_conn import TradingConnection

class UserDAO:

    def crear_usuario_db(self, username, email, password_hash):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO usuarios (username, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id
            ''', (username, email, password_hash))
            
            user_id = cursor.fetchone()[0]
            conn.commit()
            return user_id
        except psycopg2.IntegrityError:
            return None  # Username o email ya existe
        finally:
            conn.close()

    def obtener_usuario_por_username(self, username):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def obtener_usuario_por_email(self, email):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def obtener_usuario_por_id(self, user_id):
        conn = TradingConnection().get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None