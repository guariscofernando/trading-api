# app/services/limites.py
"""
Límites por abuso para rutas que gastan una cuota externa o CPU. Son dependencias de FastAPI: se añaden a la
ruta con `dependencies=[Depends(...)]` (o como parámetro, si la ruta necesita el usuario).

  limitar_mercado   rutas PÚBLICAS de datos de mercado (CoinGecko/Binance): por IP, MARKET_RATE_LIMIT por minuto.
                    Cada consulta nueva gasta cuota del proveedor; sin tope, un script la agota para todos.
  limitar_informes  generación de PDF: por usuario, REPORT_RATE_LIMIT por minuto.

Comparten el limitador del resto de la app (memoria o Redis) y su política: si el limitador falla, se deja pasar.
"""
from fastapi import Depends, HTTPException, Request

from app.config import config
from app.services.ratelimit import golpear_sin_bloquear, ip_cliente
from utils.authorization import get_current_user


async def _aplicar(clave: str, limite: int) -> None:
    resultado = await golpear_sin_bloquear(clave, limite, 60)
    if resultado is not None and not resultado.permitido:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiadas consultas. Intenta de nuevo en {resultado.reinicia_en} segundos.",
            headers={"Retry-After": str(resultado.reinicia_en)})


async def limitar_mercado(request: Request) -> None:
    await _aplicar(f"mercado:{ip_cliente(request.scope)}", config.MARKET_RATE_LIMIT)


async def limitar_informes(current_user: dict = Depends(get_current_user)) -> dict:
    await _aplicar(f"informe:{current_user['id']}", config.REPORT_RATE_LIMIT)
    return current_user
