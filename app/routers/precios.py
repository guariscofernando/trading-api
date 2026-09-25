# app/routers/precios.py
from fastapi import APIRouter, HTTPException, Depends
from app.services.cache import cache
from app.services.coingecko import (
    obtener_precio,
    obtener_precios_multiples,
    buscar_moneda
)

router = APIRouter(prefix="/precios", tags=["Precios"])

@router.get("/multiples")
async def get_precios_multiples(coins: str, moneda: str = "usd"):
    """Obtiene precios de múltiples monedas (separadas por coma)"""
    coin_list = [c.strip() for c in coins.split(",")]
    
    datos = await obtener_precios_multiples(coin_list, moneda)
    
    if not datos:
        raise HTTPException(status_code=500, detail="Error al obtener precios")
    
    return datos

@router.get("/buscar/{query}")
async def buscar(query: str):
    """Busca monedas por nombre"""
    resultados = await buscar_moneda(query)
    
    if not resultados:
        raise HTTPException(status_code=500, detail="Error en la búsqueda")
    
    return resultados.get("coins", [])[:10]  # Limitar a 10 resultados

@router.get("/{coin_id}")
async def get_precio(coin_id: str, moneda: str = "usd", use_cache: bool = True):
    """Obtiene el precio actual con caché opcional"""
    cache_key = f"precio_{coin_id}_{moneda}"
    
    # Verificar caché
    if use_cache:
        cached_data = cache.get(cache_key)
        if cached_data:
            return {**cached_data, "from_cache": True}
    
    # Obtener de la API
    datos = await obtener_precio(coin_id, moneda)
    
    if not datos or coin_id not in datos:
        raise HTTPException(status_code=404, detail="Moneda no encontrada")
    
    precio_data = datos[coin_id]
    resultado = {
        "moneda": coin_id,
        "precio": precio_data.get(moneda, 0),
        "cambio_24h": round(precio_data.get(f"{moneda}_24h_change", 0), 2),
        "vs_currency": moneda,
        "from_cache": False
    }
    
    # Guardar en caché por 30 segundos
    cache.set(cache_key, resultado, ttl_seconds=30)
    
    return resultado

@router.get("/cache/stats")
def cache_stats():
    """Estadísticas del caché"""
    return cache.stats()

@router.delete("/cache/clear")
def clear_cache():
    """Limpiar el caché"""
    cache.clear()
    return {"mensaje": "Caché limpiado"}