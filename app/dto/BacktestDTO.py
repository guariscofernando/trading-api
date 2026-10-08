# app/dto/BacktestDTO.py
from typing import Annotated, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from app.services.backtest import MAX_PUNTOS, MIN_PUNTOS

Positivo = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Porcentaje = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
NumeroFinito = Annotated[float, Field(allow_inf_nan=False)]


class BacktestRequest(BaseModel):
    """Indica EXACTAMENTE una fuente de precios: `precios` o `coin_id`."""
    estrategia: Literal["cruce_medias", "rsi"]
    parametros_estrategia: Dict[str, NumeroFinito] = Field(
        default_factory=dict, max_length=10,
        description="Ver GET /backtest/estrategias para los parámetros de cada estrategia",
    )

    # Fuente de datos
    precios: Optional[List[Positivo]] = Field(
        None, min_length=MIN_PUNTOS, max_length=MAX_PUNTOS,
        description="Precios de cierre en orden cronológico",
    )
    coin_id: Optional[str] = Field(
        None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
        description="ID de CoinGecko (ej: bitcoin); se descargan precios diarios",
    )
    moneda: str = Field("usd", pattern=r"^[a-z]{2,10}$")
    dias: int = Field(365, ge=MIN_PUNTOS, le=365, description="Días de historia (el plan gratuito de CoinGecko llega a 365)")

    # Simulación y riesgo
    capital_inicial: Positivo = 10_000.0
    riesgo_por_trade_pct: Porcentaje = 1.0
    stop_loss_pct: Annotated[float, Field(gt=0, lt=100, allow_inf_nan=False)] = 5.0
    take_profit_pct: Optional[Positivo] = None
    posicion_max_pct: Porcentaje = 25.0
    drawdown_max_pct: Porcentaje = 20.0
    comision_pct: Annotated[float, Field(ge=0, lt=10, allow_inf_nan=False)] = 0.1
    slippage_pct: Annotated[float, Field(ge=0, lt=10, allow_inf_nan=False)] = 0.05
    periodos_por_ano: Positivo = 365.0

    @model_validator(mode="after")
    def exactamente_una_fuente(self):
        if (self.precios is None) == (self.coin_id is None):
            raise ValueError("Indica exactamente una fuente de datos: 'precios' o 'coin_id'")
        return self
