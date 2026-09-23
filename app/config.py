# app/config.py
import os

class Config:
    # Base de datos
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "sqlite:///./data/trading.db"
    )
    
    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    
    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    
    # Debug
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # App
    APP_NAME = "Trading API"
    APP_VERSION = "3.0.0"

config = Config()