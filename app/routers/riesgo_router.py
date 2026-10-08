# app/routers/riesgo_router.py
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dao.TradeDAO import TradeDAO
from app.dto.RiesgoDTO import (
    EvaluarTradeRequest,
    NivelesSalidaRequest,
    TamanoPosicionRequest,
)
from app.services import risk
from utils.authorization import get_current_user

router = APIRouter(prefix="/riesgo", tags=["Riesgo"])
dao = TradeDAO()


def _limites(dto) -> risk.LimitesRiesgo:
    """Aplica sobre los valores por defecto solo los límites que el cliente indicó."""
    if dto is None:
        return risk.LimitesRiesgo()
    cambios = {k: v for k, v in dto.model_dump().items() if v is not None}
    return replace(risk.LimitesRiesgo(), **cambios)


def _o_422(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/limites")
def limites_por_defecto(current_user: dict = Depends(get_current_user)):
    """Límites de riesgo que se aplican si no se indican otros."""
    return risk.LimitesRiesgo().a_dict()


@router.post("/tamano-posicion")
def tamano_posicion(datos: TamanoPosicionRequest, current_user: dict = Depends(get_current_user)):
    """Cuántas unidades comprar para arriesgar, como máximo, `riesgo_pct` del capital si salta el stop."""
    return _o_422(risk.calcular_tamano_posicion, **datos.model_dump())


@router.post("/niveles-salida")
def niveles_salida(datos: NivelesSalidaRequest, current_user: dict = Depends(get_current_user)):
    """Precios de stop-loss y take-profit a partir de porcentajes o de un ratio riesgo/beneficio."""
    return _o_422(risk.niveles_salida, **datos.model_dump())


@router.post("/evaluar-trade")
def evaluar_trade(datos: EvaluarTradeRequest, current_user: dict = Depends(get_current_user)):
    """Comprueba una operación propuesta contra los límites de riesgo. No ejecuta ni registra nada."""
    cuerpo = datos.model_dump(exclude={"limites"})
    return _o_422(risk.evaluar_trade, limites=_limites(datos.limites), **cuerpo)


@router.get("/portafolio")
def riesgo_portafolio(
    capital: Optional[float] = Query(None, gt=0, allow_inf_nan=False, description="Patrimonio total (opcional)"),
    current_user: dict = Depends(get_current_user),
):
    """Exposición, concentración y resultados realizados de TUS trades registrados (a costo, sin precios de mercado)."""
    trades = dao.obtener_trades_db(usuario_id=current_user["id"], limit=10000)
    return _o_422(risk.analizar_portafolio, trades, capital=capital)
