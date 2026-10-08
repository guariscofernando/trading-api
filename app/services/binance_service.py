# app/services/binance_service.py
import logging
from app.config import config
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_LOSS,
    TIME_IN_FORCE_GTC
)

logger = logging.getLogger("binance-service")

class BinanceService:
    """Servicio para interactuar con Binance API"""
    
    def __init__(self):
        # Si estamos en testnet, usar la URL de testnet
        if config.BINANCE_TESTNET:
            # ping=False: no tocar la red al crear el cliente. Si Binance no responde
            # (caída o región restringida) la API arranca igual y solo fallan los
            # endpoints de Binance cuando se usan.
            self.client = Client(
                config.BINANCE_API_KEY,
                config.BINANCE_SECRET_KEY,
                testnet=True,
                ping=False
            )
            logger.info("✓ Cliente Binance TESTNET configurado")
        else:
            self.client = Client(
                config.BINANCE_API_KEY,
                config.BINANCE_SECRET_KEY,
                ping=False
            )
            logger.info("✓ Cliente Binance PRODUCTION configurado")
    
    def ping(self) -> bool:
        """Verifica conexión con Binance"""
        try:
            self.client.ping()
            return True
        except Exception as e:  # incluye errores de red, no solo errores de la API
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
    
    def get_symbol_info(self, symbol: str) -> dict | None:
        """Obtiene información detallada de un par"""
        try:
            info = self.client.get_symbol_info(symbol.upper())
            if not info:
                logger.warning(f"Símbolo no encontrado: {symbol}")
                return None

            filters = {f["filterType"]: f for f in info.get("filters", [])}
            lot_size = filters.get("LOT_SIZE", {})
            price_filter = filters.get("PRICE_FILTER", {})
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL", {})

            return {
                "symbol": info["symbol"],
                "status": info["status"],
                "baseAsset": info["baseAsset"],
                "quoteAsset": info["quoteAsset"],
                "minQty": lot_size.get("minQty"),
                "maxQty": lot_size.get("maxQty"),
                "stepSize": lot_size.get("stepSize"),
                "tickSize": price_filter.get("tickSize"),
                "minNotional": notional.get("minNotional"),
            }
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo info de {symbol}: {e}")
            return None

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Coloca una orden de mercado"""
        try:
            order_side = SIDE_BUY if side == "BUY" else SIDE_SELL
            
            order = self.client.order_market(
                symbol=symbol.upper(),
                side=order_side,
                quantity=quantity
            )
            
            return {
                "orderId": order['orderId'],
                "symbol": order['symbol'],
                "side": order['side'],
                "type": order['type'],
                "status": order['status'],
                "executedQty": order['executedQty'],
                "fills": order.get('fills', [])
            }
        except BinanceAPIException as e:
            logger.error(f"Error colocando market order: {e}")
            raise

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> dict:
        """Coloca una orden limitada"""
        try:
            order_side = SIDE_BUY if side == "BUY" else SIDE_SELL
            
            order = self.client.order_limit(
                symbol=symbol.upper(),
                side=order_side,
                quantity=quantity,
                price=str(price),
                timeInForce=TIME_IN_FORCE_GTC  # Good Till Cancel
            )
            
            return {
                "orderId": order['orderId'],
                "symbol": order['symbol'],
                "side": order['side'],
                "type": order['type'],
                "status": order['status'],
                "price": order['price'],
                "origQty": order['origQty']
            }
        except BinanceAPIException as e:
            logger.error(f"Error colocando limit order: {e}")
            raise

    def place_stop_loss_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> dict:
        """Coloca una orden stop-loss"""
        try:
            order_side = SIDE_BUY if side == "BUY" else SIDE_SELL
            
            order = self.client.create_order(
                symbol=symbol.upper(),
                side=order_side,
                type=ORDER_TYPE_STOP_LOSS,
                quantity=quantity,
                stopPrice=str(stop_price)
            )
            
            return {
                "orderId": order['orderId'],
                "symbol": order['symbol'],
                "side": order['side'],
                "type": order['type'],
                "status": order['status'],
                "stopPrice": order['stopPrice']
            }
        except BinanceAPIException as e:
            logger.error(f"Error colocando stop loss: {e}")
            raise

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancela una orden"""
        try:
            result = self.client.cancel_order(
                symbol=symbol.upper(),
                orderId=order_id
            )
            return result
        except BinanceAPIException as e:
            logger.error(f"Error cancelando orden {order_id}: {e}")
            raise

    def get_open_orders(self, symbol: str = None) -> list:
        """Obtiene órdenes abiertas"""
        try:
            if symbol:
                orders = self.client.get_open_orders(symbol=symbol.upper())
            else:
                orders = self.client.get_open_orders()
            
            return [
                {
                    "orderId": o['orderId'],
                    "symbol": o['symbol'],
                    "side": o['side'],
                    "type": o['type'],
                    "price": o['price'],
                    "origQty": o['origQty'],
                    "status": o['status']
                }
                for o in orders
            ]
        except BinanceAPIException as e:
            logger.error(f"Error obteniendo órdenes abiertas: {e}")
            return []

# Instancia global
binance_service = BinanceService()