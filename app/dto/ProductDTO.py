from pydantic import BaseModel, Field

"""
Intensive Review
    Create a Pydantic model for a Product with price validation (price > 0).
"""

# Modelo para CREAR un trade (entrada)
class ProductCreate(BaseModel):
    name: str = Field(...,description="Product name")
    price: float = Field(..., gt=0, description="Product price must be > 0")

class ProductDTO(BaseModel):
    id: int
    name: str = Field(...,description="Product name")
    price: float = Field(..., gt=0, description="Product price must be > 0")