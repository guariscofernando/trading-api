import os
import sqlite3

class IntensiveReviewConnection:
    __DB_PATH = "data/intensive_review.db"

    def get_connection(self):
        """Obtiene una conexión a la base de datos"""
        conn = sqlite3.connect(self.__DB_PATH)
        conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre
        return conn

    def init_db(self):
        # Crear carpeta data si no existe
        if not os.path.exists("data"):
            os.makedirs("data")

        """Inicializa la base de datos (crea tablas)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Product (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL ,
                precio REAL NOT NULL CHECK(precio > 0)
            )
        ''')
        
        conn.commit()
        conn.close()
        print("Base de datos IntensiveReview inicializada")