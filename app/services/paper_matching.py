# app/services/paper_matching.py
"""
Motor de órdenes pendientes del paper trading: cada PAPER_MATCH_INTERVAL_SECONDS mira el precio de las
monedas con órdenes abiertas y ejecuta las que ese precio dispara.

Es seguro con varios procesos a la vez (ver PaperDAO._procesar_una: SKIP LOCKED + estado dentro del bloqueo),
así que no depende de `--workers 1`. Con PAPER_MATCHING_ENABLED=false un proceso no lo ejecuta.

Límites que conviene conocer: el precio viene de CoinGecko (con hasta 60 s de caché) y se consulta por
intervalos, así que una orden puede ejecutarse con retraso y un pico más corto que el intervalo no la dispara.
"""
import asyncio
import logging

import anyio

from app.config import config
from app.dao.PaperDAO import PaperDAO
from app.services import paper_trading as pt

from app.services.metricas import CICLOS, ORDENES, ULTIMO_CICLO_OK

logger = logging.getLogger("trading-api")


async def un_ciclo(dao: PaperDAO = None) -> dict:
    """Una pasada: precios de las monedas con órdenes abiertas y ejecución de las disparadas."""
    dao = dao or PaperDAO()
    monedas = await anyio.to_thread.run_sync(dao.monedas_con_ordenes_abiertas)
    if not monedas:
        return {"ejecutadas": 0, "rechazadas": 0, "errores": 0}
    precios = {c: p for c, p in (await pt.precios_de_mercado(monedas)).items() if p is not None}
    if not precios:
        logger.warning("Paper trading: sin precios para %d moneda(s) con órdenes abiertas", len(monedas))
        return {"ejecutadas": 0, "rechazadas": 0, "errores": 0}
    resumen = await anyio.to_thread.run_sync(
        dao.procesar_pendientes, precios, config.PAPER_COMMISSION_PCT, config.PAPER_SLIPPAGE_PCT,
        config.PAPER_INITIAL_BALANCE)
    for resultado, n in resumen.items():
        if n:
            ORDENES.labels(resultado).inc(n)
    return resumen


async def bucle_de_casamiento() -> None:
    """Tarea en segundo plano: un fallo en una pasada se registra y no la detiene."""
    while True:
        try:
            await un_ciclo()
            CICLOS.labels("ok").inc()
            ULTIMO_CICLO_OK.set_to_current_time()
        except asyncio.CancelledError:
            raise
        except Exception:
            CICLOS.labels("error").inc()
            logger.exception("Paper trading: error en el motor de órdenes pendientes")
        await asyncio.sleep(config.PAPER_MATCH_INTERVAL_SECONDS)
