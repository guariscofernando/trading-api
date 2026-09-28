# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:

    # ENTORNO
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

    # APP
    APP_NAME = os.getenv("APP_NAME")
    APP_VERSION = os.getenv("APP_VERSION")
    APP_DESCRIPTION = os.getenv("APP_DESCRIPTION")

    # AUTH
    ENCODE = os.getenv("ENCODE", "utf-8")

    # BINANCE
    BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

    # COINGECKO
    COINGECKO_BASE_URL = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
    COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS","").split(",")
    
    # DATABASE
    DATABASE_URL = os.getenv("DATABASE_URL")

    # DEBUG
    DEBUG = os.getenv("DEBUG").lower() == "true"
    
    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

config = Config()

# Validación: si estamos en testnet, debemos tener API keys
if config.BINANCE_TESTNET:
    if not config.BINANCE_API_KEY or not config.BINANCE_SECRET_KEY:
        print("⚠️  WARNING: Binance API keys not configured")