# app/services/coingecko.py
import httpx
import logging
from app.services.cache import cache
from app.config import config

logger = logging.getLogger("trading-api")

async def obtener_precio(coin_id: str, moneda: str = "usd") -> dict:
    cache_key = f"coingecko_precio_{coin_id}_{moneda}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    headers = {"x-cg-demo-api-key": config.COINGECKO_API_KEY} if config.COINGECKO_API_KEY else {}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{config.COINGECKO_BASE_URL}/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": moneda,
                "include_24hr_change": "true",
            },
            headers=headers,
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
    headers = {"x-cg-demo-api-key": config.COINGECKO_API_KEY} if config.COINGECKO_API_KEY else {}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{config.COINGECKO_BASE_URL}/simple/price",
            params={
                "ids": ",".join(coin_ids),
                "vs_currencies": moneda,
                "include_24hr_change": "true",
                "include_market_cap": "true"
            },
            headers=headers,
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
            f"{config.COINGECKO_BASE_URL}/search",
            params={"query": query},
            timeout=10.0
        )

        if response.status_code == 200:
            return response.json()

        logger.error(f"CoinGecko error {response.status_code}: {response.text}")
        return None

async def obtener_historico(coin_id: str, moneda: str = "usd", dias: int = 365) -> list:
    """
    Precios de cierre diarios (lista de floats, del más antiguo al más reciente) o None si falla.
    `coin_id` y `moneda` deben venir ya validados: `coin_id` forma parte de la URL.
    """
    cache_key = f"coingecko_historico_{coin_id}_{moneda}_{dias}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    headers = {"x-cg-demo-api-key": config.COINGECKO_API_KEY} if config.COINGECKO_API_KEY else {}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config.COINGECKO_BASE_URL}/coins/{coin_id}/market_chart",
                params={"vs_currency": moneda, "days": dias, "interval": "daily"},
                headers=headers,
                timeout=15.0,
            )
        if response.status_code != 200:
            logger.error(f"CoinGecko historico error {response.status_code}: {response.text[:200]}")
            return None
        precios = [float(punto[1]) for punto in response.json().get("prices", [])]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        logger.error(f"CoinGecko historico fallo para {coin_id}: {e}")
        return None

    if precios:
        cache.set(cache_key, precios, ttl_seconds=300)
    return precios or None
