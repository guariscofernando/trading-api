# app/dto/OrdersDTO.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"

class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

class OrderCreate(BaseModel):
    symbol: str = Field(..., description="Par de trading, ej: BTCUSDT")
    side: OrderSide = Field(..., description="BUY o SELL")
    order_type: OrderType = Field(..., description="Tipo de orden")
    quantity: float = Field(..., gt=0, description="Cantidad del activo base")
    price: Optional[float] = Field(None, gt=0, description="Precio (solo para LIMIT)")
    stop_price: Optional[float] = Field(None, gt=0, description="Precio de activación (solo para STOP_LOSS)")
    
    @field_validator('symbol')
    @classmethod
    def validar_symbol(cls, v):
        v = v.upper()
        if not v.endswith("USDT"):
            v = f"{v}USDT"
        return v
    
    @field_validator('price')
    @classmethod
    def validar_price(cls, v, info):
        if info.data.get('order_type') == OrderType.LIMIT and v is None:
            raise ValueError("Las órdenes LIMIT requieren precio")
        return v
    
    @field_validator('stop_price')
    @classmethod
    def validar_stop_price(cls, v, info):
        if info.data.get('order_type') == OrderType.STOP_LOSS and v is None:
            raise ValueError("Las órdenes STOP_LOSS requieren stop_price")
        return v

class OrderResponse(BaseModel):
    order_id: int
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    price: Optional[float]
    stop_price: Optional[float]
    executed_qty: Optional[float] = 0
    created_at: str