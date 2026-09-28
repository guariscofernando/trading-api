# app/routers/binance_router.py
from fastapi import APIRouter, HTTPException, Depends
from app.services.binance_service import binance_service
from utils.authorization import get_current_user

router = APIRouter(prefix="/binance", tags=["Binance"])

@router.get("/ping")
def ping():
    """Verifica conexión con Binance"""
    if binance_service.ping():
        return {"status": "connected", "testnet": True}
    raise HTTPException(status_code=500, detail="No se pudo conectar a Binance")

@router.get("/server-time")
def server_time():
    """Obtiene la hora del servidor de Binance"""
    result = binance_service.get_server_time()
    if result:
        return result
    raise HTTPException(status_code=500, detail="Error obteniendo server time")

@router.get("/balance", dependencies=[Depends(get_current_user)])
def get_balance():
    """Obtiene el balance de la cuenta (requiere autenticación)"""
    balances = binance_service.get_account_balance()
    return {
        "testnet": True,
        "balances": balances,
        "total_assets": len(balances)
    }

@router.get("/price/{symbol}")
def get_price(symbol: str):
    """Obtiene el precio actual de un par"""
    # Normalizar el símbolo (btc -> BTCUSDT)
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    ticker = binance_service.get_ticker_price(symbol)
    if ticker:
        return ticker
    raise HTTPException(status_code=404, detail=f"Símbolo {symbol} no encontrado")

@router.get("/prices")
def get_all_prices():
    """Obtiene precios de varios pares"""
    return {"tickers": binance_service.get_all_tickers()}

@router.get("/symbol-info/{symbol}")
def get_symbol_info(symbol: str):
    """Obtiene información de un par"""
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    
    info = binance_service.get_symbol_info(symbol)
    if info:
        return info
    raise HTTPException(status_code=404, detail=f"Símbolo {symbol} no encontrado")