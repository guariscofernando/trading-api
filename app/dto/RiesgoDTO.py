# app/dto/RiesgoDTO.py
from typing import Annotated, Optional
from pydantic import BaseModel, Field

# allow_inf_nan=False: el JSON de Python acepta NaN/Infinity y pasarían las comparaciones numéricas
Positivo = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Porcentaje = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
NoNegativo = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class LimitesDTO(BaseModel):
    """Límites de riesgo. Los campos omitidos usan el valor por defecto de la API."""
    riesgo_max_por_trade_pct: Optional[Porcentaje] = None
    posicion_max_pct: Optional[Porcentaje] = None
    perdida_diaria_max_pct: Optional[Porcentaje] = None
    drawdown_max_pct: Optional[Porcentaje] = None
    posiciones_abiertas_max: Optional[int] = Field(None, ge=1, le=1000)


class TamanoPosicionRequest(BaseModel):
    capital: Positivo = Field(..., description="Capital total de la cuenta")
    entrada: Positivo = Field(..., description="Precio de entrada previsto")
    stop: Positivo = Field(..., description="Precio del stop-loss (por debajo de la entrada)")
    riesgo_pct: Porcentaje = Field(1.0, description="% del capital que se acepta perder si salta el stop")
    posicion_max_pct: Porcentaje = Field(100.0, description="Tope del valor de la posición sobre el capital")
    saldo_disponible: Optional[NoNegativo] = Field(None, description="Efectivo disponible para comprar")


class NivelesSalidaRequest(BaseModel):
    entrada: Positivo
    stop_loss_pct: Annotated[float, Field(gt=0, lt=100, allow_inf_nan=False)]
    take_profit_pct: Optional[Positivo] = None
    ratio_riesgo_beneficio: Optional[Positivo] = None


class EvaluarTradeRequest(BaseModel):
    capital: Positivo
    entrada: Positivo
    stop: Positivo
    cantidad: Positivo
    saldo_disponible: Optional[NoNegativo] = None
    perdida_diaria_pct: NoNegativo = Field(0.0, description="Pérdida acumulada hoy, en % del capital")
    drawdown_actual_pct: NoNegativo = Field(0.0, description="Drawdown actual de la cuenta, en %")
    posiciones_abiertas: int = Field(0, ge=0, le=100000)
    limites: Optional[LimitesDTO] = None
