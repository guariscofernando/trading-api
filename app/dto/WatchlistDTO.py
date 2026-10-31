# app/dto/WatchlistDTO.py
import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from app.services.validacion import PATRON_COIN_ID

class WatchlistCreate(BaseModel):
    coin_id: str = Field(..., min_length=1, max_length=64, description="Id de CoinGecko, ej: 'bitcoin'")
    precio_alerta: float = Field(..., gt=0, description="Precio al que se quiere alertar")

    @field_validator("coin_id")
    @classmethod
    def validar_coin(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(PATRON_COIN_ID, v):
            raise ValueError("coin_id solo admite letras minúsculas, números y guiones")
        return v

class WatchlistResponse(BaseModel):
    id: int
    usuario_id: int
    coin_id: str
    precio_alerta: float
    creado_en: datetime