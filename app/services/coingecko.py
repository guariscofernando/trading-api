# app/services/coingecko.py
import httpx
import logging
from app.services.cache import cache

logger = logging.getLogger("trading-api")

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

async def obtener_precio(coin_id: str, moneda: str = "usd") -> dict:
    cache_key = f"coingecko_precio_{coin_id}_{moneda}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": moneda,
                "include_24hr_change": "true"
            },
            timeout=10.0
        )

        if response.status_code == 200:
            datos = response.json()
            cache.set(cache_key, datos, ttl_seconds=60)
            return datos

        logger.error(f"CoinGecko error {response.status_code}: {response.text}")
        return None


async def obtener_precios_multiples(coin_ids: list, moneda: str = "usd") -> dict:
    # Ordenamos para que la key sea consistente sin importar el orden de la lista
    cache_key = f"coingecko_multiples_{'_'.join(sorted(coin_ids))}_{moneda}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/simple/price",
            params={
                "ids": ",".join(coin_ids),
                "vs_currencies": moneda,
                "include_24hr_change": "true",
                "include_market_cap": "true"
            },
            timeout=10.0
        )

        if response.status_code == 200:
            datos = response.json()
            cache.set(cache_key, datos, ttl_seconds=60)
            return datos

        logger.error(f"CoinGecko error {response.status_code}: {response.text}")
        return None


async def buscar_moneda(query: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{COINGECKO_BASE_URL}/search",
            params={"query": query},
            timeout=10.0
        )

        if response.status_code == 200:
            return response.json()

        logger.error(f"CoinGecko error {response.status_code}: {response.text}")
        return None