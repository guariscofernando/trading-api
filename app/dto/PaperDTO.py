# app/dto/PaperDTO.py
import re
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# max_digits/decimal_places: lo que no cabe en NUMERIC(18,8) se rechaza con 422 en vez de fallar en la base
Cantidad = Annotated[Decimal, Field(gt=0, le=Decimal("1000000000"), decimal_places=8, allow_inf_nan=False)]


class OrdenPaper(BaseModel):
    coin_id: str = Field(..., min_length=1, max_length=64, description="ID de CoinGecko (p. ej. bitcoin)")
    side: Literal["BUY", "SELL"]
    cantidad: Cantidad
    client_order_id: Optional[str] = Field(
        None, min_length=1, max_length=64,
        description="Identificador único elegido por el cliente: reintentar con el mismo no duplica la orden")

    @field_validator("coin_id")
    @classmethod
    def validar_coin(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", v):
            raise ValueError("coin_id solo admite letras minúsculas, números y guiones")
        return v

    @field_validator("client_order_id")
    @classmethod
    def validar_cliente(cls, v):
        if v is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", v):
            raise ValueError("client_order_id solo admite letras, números y _ . : -")
        return v


class OrdenPendientePaper(BaseModel):
    """Orden LIMIT o STOP: `precio` es el precio límite (LIMIT) o el de disparo (STOP)."""
    coin_id: str = Field(..., min_length=1, max_length=64, description="ID de CoinGecko (p. ej. bitcoin)")
    side: Literal["BUY", "SELL"]
    tipo: Literal["LIMIT", "STOP"]
    cantidad: Cantidad
    precio: Annotated[Decimal, Field(gt=0, le=Decimal("1000000000"), decimal_places=8, allow_inf_nan=False)]
    client_order_id: Optional[str] = Field(None, min_length=1, max_length=64)

    @field_validator("coin_id")
    @classmethod
    def validar_coin(cls, v):
        return OrdenPaper.validar_coin.__func__(cls, v)

    @field_validator("client_order_id")
    @classmethod
    def validar_cliente(cls, v):
        return OrdenPaper.validar_cliente.__func__(cls, v)
