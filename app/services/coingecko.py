# app/services/coingecko.py
import httpx
import asyncio
import logging

logger = logging.getLogger("trading-api")

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

async def obtener_precio(coin_id: str, moneda: str = "usd") -> dict:
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
            return response.json()
        
        logger.error(f"CoinGecko error {response.status_code}: {response.text}")
        return None

async def obtener_precios_multiples(coin_ids: list, moneda: str = "usd") -> dict:
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
            return response.json()
        
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