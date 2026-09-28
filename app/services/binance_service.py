# app/services/binance_service.py
from binance.client import Client
from binance.exceptions import BinanceAPIException
from app.config import config
import logging

logger = logging.getLogger("binance-service")

class BinanceService:
    """Servicio para interactuar con Binance API"""
    
    def __init__(self):
        # Si estamos en testnet, usar la URL de testnet
        if config.BINANCE_TESTNET:
            self.client = Client(
                config.BINANCE_API_KEY,
                config.BINANCE_SECRET_KEY,
                testnet=True
            )
            logger.info("✓ Conectado a Binance TESTNET")
        else:
            self.client = Client(
                config.BINANCE_API_KEY,
                config.BINANCE_SECRET_KEY
            )
            logger.info("✓ Conectado a Binance PRODUCTION")
    
    def ping(self) -> bool:
        """Verifica conexión con Binance"""
        try:
            self.client.ping()
            return True
        except BinanceAPIException as e:
            logger.error(f"Error en ping: {e}")
            return False
    
    def get_server_time(self) -> dict:
        """Obtiene la hora del servidor de Binance"""
        try:
            return self.client.get_server_time()
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo server time: {e}")
            return None
    
    def get_account_balance(self) -> list:
        """Obtiene el balance de la cuenta"""
        try:
            account = self.client.get_account()
            balances = []
            
            for balance in account['balances']:
                free = float(balance['free'])
                locked = float(balance['locked'])
                
                if free > 0 or locked > 0:
                    balances.append({
                        "asset": balance['asset'],
                        "free": free,
                        "locked": locked,
                        "total": free + locked
                    })
            
            return balances
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo balance: {e}")
            return []
    
    def get_ticker_price(self, symbol: str) -> dict:
        """Obtiene el precio actual de un par"""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol.upper())
            return {
                "symbol": ticker['symbol'],
                "price": float(ticker['price'])
            }
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo ticker {symbol}: {e}")
            return None
    
    def get_all_tickers(self) -> list:
        """Obtiene precios de todos los pares"""
        try:
            tickers = self.client.get_all_tickers()
            return [
                {
                    "symbol": t['symbol'],
                    "price": float(t['price'])
                }
                for t in tickers[:20]  # Limitar a 20 para no sobrecargar
            ]
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo tickers: {e}")
            return []
    
    def get_symbol_info(self, symbol: str) -> dict:
        """Obtiene información detallada de un par"""
        try:
            info = self.client.get_symbol_info(symbol.upper())
            return {
                "symbol": info['symbol'],
                "status": info['status'],
                "baseAsset": info['baseAsset'],
                "quoteAsset": info['quoteAsset'],
                "minQty": info['filters'][2]['minQty'],
                "stepSize": info['filters'][2]['stepSize'],
                "minNotional": info['filters'][3]['minNotional'] if len(info['filters']) > 3 else None
            }
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo info de {symbol}: {e}")
            return None

# Instancia global
binance_service = BinanceService()