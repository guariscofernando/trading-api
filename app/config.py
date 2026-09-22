# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")

# Configuración basada en variables de entorno
class Config:
    # Si estamos en producción, usar la variable de entorno
    # Si no, usar el valor por defecto
    DB_PATH = os.getenv("DB_PATH", "data/trading.db")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    API_TITLE = "Trading API"
    API_VERSION = "1.0.0"