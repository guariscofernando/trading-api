# app/database.py
import sqlite3
import os

# Ruta de la base de datos
DB_PATH = "data/trading.db"

# Crear carpeta data si no existe
if not os.path.exists("data"):
    os.makedirs("data")

def get_connection():
    """Obtiene una conexión a la base de datos"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre
    return conn

def init_db():
    """Inicializa la base de datos (crea tablas)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL CHECK(tipo IN ('compra', 'venta')),
            activo TEXT NOT NULL,
            precio REAL NOT NULL CHECK(precio > 0),
            cantidad REAL NOT NULL CHECK(cantidad > 0),
            fecha TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Base de datos inicializada")

# app/database.py (continuar)

def crear_trade_db(tipo, activo, precio, cantidad, fecha):
    """Inserta un trade en la base de datos"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO trades (tipo, activo, precio, cantidad, fecha)
        VALUES (?, ?, ?, ?, ?)
    ''', (tipo, activo, precio, cantidad, fecha))
    
    trade_id = cursor.lastrowid  # ID del trade recién insertado
    conn.commit()
    conn.close()
    
    return trade_id

def obtener_trades_db(skip=0, limit=10, tipo=None, activo=None):
    """Obtiene trades de la base de datos con filtros"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    
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

def obtener_trade_db(trade_id):
    """Obtiene un trade específico"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def actualizar_trade_db(trade_id, **kwargs):
    """Actualiza campos de un trade"""
    conn = get_connection()
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

def eliminar_trade_db(trade_id):
    """Elimina un trade"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    
    return filas_afectadas > 0

# Llamar init_db al importar el módulo
init_db()

