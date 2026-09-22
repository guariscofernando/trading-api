
from fastapi import APIRouter, Depends, Query
from app.dto.ProductDTO import ProductCreate, ProductDTO
from app.dao.ProductDAO import ProductDAO
from utils.authorization import get_current_user
"""
Intensive Review
    Create a GET endpoint that accepts a `name` query parameter and returns a greeting.
    Create a POST endpoint that receives JSON data and saves it to the database.
"""

router = APIRouter(prefix="/intensive_review", tags=["Intensive Review"])
dao = ProductDAO()

@router.get("/")
def greetings(name: str = Query("")):
    return f"Hi {name}"

@router.post("/", response_model=ProductDTO, status_code=201, dependencies=[Depends(get_current_user)])
def crear_product(product: ProductCreate):
    product_id = dao.save_product_db(
        name=product.name,
        price=product.price
    )
    
    return {
        "id": product_id,
        "name": product.name,
        "price": product.price
    }


