#app/connections/trading_db_conn.py
import os
import sqlite3

class TradingConnection:
    # Ruta de la base de datos
    DB_PATH = "data/trading.db"

    def get_connection(self):
        """Obtiene una conexión a la base de datos"""
        conn = sqlite3.connect(self.DB_PATH)
        conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre
        conn.execute("PRAGMA foreign_keys = ON")  # Activar foreign keys
        return conn

    def init_db(self):
        # Crear carpeta data si no existe
        if not os.path.exists("data"):
            os.makedirs("data")

        """Inicializa la base de datos (crea tablas)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabla de usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT (datetime('now'))
            )
        ''')
        
        # Tabla de trades con foreign key a usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                tipo TEXT NOT NULL CHECK(tipo IN ('compra', 'venta')),
                activo TEXT NOT NULL,
                precio REAL NOT NULL CHECK(precio > 0),
                cantidad REAL NOT NULL CHECK(cantidad > 0),
                fecha TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        conn.close()
        print("Base de datos TradingConnection inicializada con relaciones")