#app/connections/trading_db_conn.py
from app.config import config
import psycopg2
class TradingConnection:
    
    def get_connection(self):
        """Obtiene conexión a PostgreSQL"""
        conn = psycopg2.connect(config.DATABASE_URL)
        return conn
