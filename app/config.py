# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()


def _entero(nombre: str, defecto: int) -> int:
    """Lee un entero del entorno; si no lo es, falla al arrancar diciendo cuál variable está mal."""
    crudo = os.getenv(nombre, str(defecto))
    try:
        return int(crudo)
    except ValueError:
        raise RuntimeError(f"{nombre} debe ser un número entero (recibido: '{crudo}')")


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
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    
    # DATABASE
    DATABASE_URL = os.getenv("DATABASE_URL")
    # Pool de conexiones por proceso. Total máximo hacia la base = (POOL_SIZE + MAX_OVERFLOW) x procesos.
    DB_POOL_SIZE = _entero("DB_POOL_SIZE", 5)
    DB_MAX_OVERFLOW = _entero("DB_MAX_OVERFLOW", 10)
    DB_POOL_TIMEOUT = _entero("DB_POOL_TIMEOUT", 10)     # segundos esperando una conexión libre
    DB_POOL_RECYCLE = _entero("DB_POOL_RECYCLE", 300)    # recicla conexiones inactivas (Neon las corta)

    # DEBUG
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def validate(self) -> None:
        """Falla al arrancar, con un mensaje claro, si la configuración es inválida."""
        requeridas = {
            "SECRET_KEY": self.SECRET_KEY,
            "ALGORITHM": self.ALGORITHM,
            "DATABASE_URL": self.DATABASE_URL,
            "APP_NAME": self.APP_NAME,
            "APP_VERSION": self.APP_VERSION,
            "APP_DESCRIPTION": self.APP_DESCRIPTION,
        }
        faltantes = [nombre for nombre, valor in requeridas.items() if not valor]
        if faltantes:
            raise RuntimeError(
                "Configuración incompleta. Faltan variables de entorno: "
                + ", ".join(faltantes)
                + ". Revisa tu .env (ver .env.example)."
            )

        for nombre in ("DB_POOL_SIZE", "DB_POOL_TIMEOUT", "DB_POOL_RECYCLE"):
            if getattr(self, nombre) < 1:
                raise RuntimeError(f"{nombre} debe ser mayor o igual que 1")
        if self.DB_MAX_OVERFLOW < 0:
            raise RuntimeError("DB_MAX_OVERFLOW no puede ser negativo")

        if self.ALGORITHM not in ("HS256", "HS384", "HS512"):
            raise RuntimeError(
                f"ALGORITHM='{self.ALGORITHM}' no es válido. Usa HS256, HS384 o HS512."
            )

        if self.is_production:
            if len(self.SECRET_KEY) < 32 or self.SECRET_KEY in SECRETS_DE_EJEMPLO:
                raise RuntimeError(
                    "SECRET_KEY insegura para producción: debe tener al menos 32 "
                    "caracteres y no puede ser el valor de ejemplo. "
                    "Genera una con: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            if not self.CORS_ORIGINS or "*" in self.CORS_ORIGINS:
                raise RuntimeError(
                    "En producción CORS_ORIGINS debe listar orígenes concretos (no vacío ni '*')."
                )

# Valores de ejemplo que nunca deben usarse en producción
SECRETS_DE_EJEMPLO = {
    "cambia-esto-en-produccion",
    "cambiar-por-una-clave-segura-en-produccion",
    "secret",
    "changeme",
}

config = Config()
config.validate()

# Validación: si estamos en testnet, debemos tener API keys
if config.BINANCE_TESTNET:
    if not config.BINANCE_API_KEY or not config.BINANCE_SECRET_KEY:
        print("⚠️  WARNING: Binance API keys not configured")