# app/models.py
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime

# Modelo para CREAR un trade (entrada)
class TradeCreate(BaseModel):
    tipo: str = Field(..., description="Tipo de trade: 'compra' o 'venta'")
    activo: str = Field(..., min_length=1, max_length=10, description="Símbolo del activo")
    precio: float = Field(..., gt=0, description="Precio del trade, debe ser > 0")
    cantidad: float = Field(..., gt=0, description="Cantidad del activo")
    
    # Validación personalizada
    @field_validator('tipo')
    @classmethod
    def validar_tipo(cls, v):
        if v.lower() not in ['compra', 'venta']:
            raise ValueError("El tipo debe ser 'compra' o 'venta'")
        return v.lower()

# Modelo para RESPONDER un trade (salida)
class TradeResponse(BaseModel):
    id: int
    tipo: str
    activo: str
    precio: float
    cantidad: float
    fecha: str

# Modelo para ACTUALIZAR un trade (parcial)
class TradeUpdate(BaseModel):
    tipo: Optional[str] = None
    activo: Optional[str] = None
    precio: Optional[float] = Field(None, gt=0)
    cantidad: Optional[float] = Field(None, gt=0)

"""
Exercise: Create Pydantic models for:
    Product (name, price, stock) with validation for stock >= 0
    User (name, email, age) with basic email validation and age >= 18
"""

class Product(BaseModel):
    name: str = Field(...,description="Product name")
    price: float = Field(..., gt=0, description="Product price must be > 0")
    stock: int = Field(..., ge=0, description="Stock quantity must be >= 0")

class User(BaseModel):
    name: str = Field(...,description="Username")
    email: EmailStr
    age: int = Field(..., ge=18, description="Age mus be >= 18")