# app/routers/backtest_router.py
from dataclasses import fields

from fastapi import APIRouter, Depends, HTTPException

from app.dto.BacktestDTO import BacktestRequest
from app.services import backtest
from app.services.coingecko import obtener_historico
from utils.authorization import get_current_user

router = APIRouter(prefix="/backtest", tags=["Backtest"])

_CAMPOS_SIMULACION = {f.name for f in fields(backtest.ParametrosBacktest)}


@router.get("/estrategias")
def estrategias(current_user: dict = Depends(get_current_user)):
    """Estrategias disponibles y sus parámetros por defecto."""
    return backtest.listar_estrategias()


@router.post("/")
async def ejecutar(datos: BacktestRequest, current_user: dict = Depends(get_current_user)):
    """
    Simula una estrategia sobre precios de cierre aplicando comisiones, slippage y
    gestión de riesgo (tamaño por riesgo fijo, stop-loss y límite de drawdown).
    """
    if datos.precios is not None:
        precios, origen = datos.precios, "precios_enviados"
    else:
        precios = await obtener_historico(datos.coin_id, datos.moneda, datos.dias)
        if not precios:
            raise HTTPException(status_code=502, detail="No se pudieron obtener los precios históricos de CoinGecko")
        origen = f"coingecko:{datos.coin_id}"

    params = backtest.ParametrosBacktest(
        **{k: v for k, v in datos.model_dump().items() if k in _CAMPOS_SIMULACION}
    )
    try:
        resultado = backtest.ejecutar_backtest(
            datos.estrategia, precios, datos.parametros_estrategia, params
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    resultado["origen_datos"] = origen
    return resultado
