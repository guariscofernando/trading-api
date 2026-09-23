#app/connections/trading_db_conn.py
import os
import psycopg2
import psycopg2.extras

# Ruta de la base de datos
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trading_user:trading_password@localhost:5432/trading_db"
)
class TradingConnection:
    
    def get_connection(self):
        """Obtiene conexión a PostgreSQL"""
        conn = psycopg2.connect(DATABASE_URL)
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
        
        conn.commit()
        conn.close()
        print("Base de datos PostgreSQL inicializada")
