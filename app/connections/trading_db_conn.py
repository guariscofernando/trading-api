#app/connections/trading_db_conn.py
from app.config import config
import psycopg2
import psycopg2.extras
class TradingConnection:
    
    def get_connection(self):
        """Obtiene conexión a PostgreSQL"""
        conn = psycopg2.connect(config.DATABASE_URL)
        return conn

    def init_db(self):
        """Inicializa la base de datos (crea tablas)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Crear tabla de usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username VARCHAR(20) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Crear tabla de trades
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                tipo VARCHAR(10) NOT NULL CHECK(tipo IN ('compra', 'venta')),
                activo VARCHAR(10) NOT NULL,
                precio NUMERIC(18, 8) NOT NULL CHECK(precio > 0),
                cantidad NUMERIC(18, 8) NOT NULL CHECK(cantidad > 0),
                fecha TIMESTAMP NOT NULL
            )
        ''')

        # Tabla de watchlist con foreign key a usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                coin_id VARCHAR(10) NOT NULL,
                precio_alerta NUMERIC(18, 8) NOT NULL CHECK(precio_alerta > 0),
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                binance_order_id BIGINT,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL CHECK(side IN ('BUY', 'SELL')),
                order_type VARCHAR(20) NOT NULL CHECK(order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS')),
                status VARCHAR(30) NOT NULL DEFAULT 'NEW',
                quantity NUMERIC(18, 8) NOT NULL,
                price NUMERIC(18, 8),
                stop_price NUMERIC(18, 8),
                executed_qty NUMERIC(18, 8) DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Crear índices para mejorar rendimiento
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_trades_usuario_id 
            ON trades(usuario_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_trades_activo 
            ON trades(activo)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_trades_fecha 
            ON trades(fecha)
        ''')

        # Índice para búsquedas rápidas
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_orders_usuario 
            ON orders(usuario_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_orders_symbol 
            ON orders(symbol)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_orders_status 
            ON orders(status)
        ''')
        
        conn.commit()
        conn.close()
        print("Base de datos PostgreSQL inicializada")
