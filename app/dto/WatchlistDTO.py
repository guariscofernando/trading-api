# app/dto/WatchlistDTO.py
from datetime import datetime
from pydantic import BaseModel, Field

class WatchlistCreate(BaseModel):
    coin_id: str = Field(..., min_length=1, description="Id de CoinGecko, ej: 'bitcoin'")
    precio_alerta: float = Field(..., gt=0, description="Precio al que se quiere alertar")

class WatchlistResponse(BaseModel):
    id: int
    usuario_id: int
    coin_id: str
    precio_alerta: float
    creado_en: datetime