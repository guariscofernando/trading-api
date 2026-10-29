# app/services/bus.py
"""
Mensajería entre procesos (pub/sub) para el chat y las notificaciones por WebSocket.

Cada WebSocket vive en el proceso que lo aceptó. Con varios procesos (o instancias), un mensaje generado en
uno tiene que llegar a las conexiones de los demás. Todo mensaje pasa por el bus:

  * Sin REDIS_URL  -> BusLocal: se entrega directamente a las conexiones de este proceso (un solo proceso).
  * Con REDIS_URL  -> BusRedis: se publica en Redis y CADA proceso (el emisor incluido) lo recibe por su
    suscripción y lo entrega a sus conexiones locales. Una sola ruta de entrega: nunca hay mensajes duplicados.

Si Redis falla el servicio no se cae: `publicar` entrega a las conexiones locales (los otros procesos no lo
reciben hasta que Redis vuelva) y la suscripción se reintenta con espera creciente.
"""
import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, List

logger = logging.getLogger("trading-api")

Manejador = Callable[[dict], Awaitable[None]]


class BusLocal:
    """Entrega solo a este proceso."""
    conectado = True

    def __init__(self):
        self._manejadores: Dict[str, List[Manejador]] = {}

    def registrar(self, canal: str, manejador: Manejador) -> None:
        self._manejadores.setdefault(canal, []).append(manejador)

    async def _entregar(self, canal: str, mensaje: dict) -> None:
        for manejador in list(self._manejadores.get(canal, [])):
            try:
                await manejador(mensaje)
            except Exception:
                logger.exception("Bus: error entregando un mensaje del canal '%s'", canal)

    async def publicar(self, canal: str, mensaje: dict) -> None:
        await self._entregar(canal, mensaje)

    async def iniciar(self) -> None:
        pass

    async def detener(self) -> None:
        pass


class BusRedis(BusLocal):
    ESPERA_MAXIMA = 30

    def __init__(self, url: str, prefijo: str = "tradingapi:", espera_inicial: float = 1.0):
        super().__init__()
        import redis.asyncio as aioredis
        self._cliente = aioredis.from_url(url, socket_connect_timeout=2, health_check_interval=15)
        self._prefijo = prefijo
        self._espera_inicial = espera_inicial
        self._tarea = None
        self.conectado = False          # ¿está activa la suscripción de este proceso?

    async def publicar(self, canal: str, mensaje: dict) -> None:
        try:
            await asyncio.wait_for(
                self._cliente.publish(self._prefijo + canal, json.dumps(mensaje, default=str)), timeout=2)
        except Exception:
            logger.warning("Bus: no se pudo publicar en Redis; se entrega solo a este proceso", exc_info=True)
            await self._entregar(canal, mensaje)
            return
        if not self.conectado:
            # Este proceso aún no escucha (arrancando o reconectando): no recibirá su propio mensaje por Redis.
            await self._entregar(canal, mensaje)

    async def _escuchar(self) -> None:
        espera = self._espera_inicial
        while True:
            pubsub = self._cliente.pubsub()
            try:
                await pubsub.subscribe(*[self._prefijo + c for c in self._manejadores])
                self.conectado = True
                espera = self._espera_inicial
                async for m in pubsub.listen():
                    if m.get("type") != "message":
                        continue
                    try:
                        canal = m["channel"].decode() if isinstance(m["channel"], bytes) else m["channel"]
                        await self._entregar(canal[len(self._prefijo):], json.loads(m["data"]))
                    except Exception:
                        logger.exception("Bus: mensaje ilegible descartado")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Bus: suscripción a Redis perdida; reintento en %.0f s", espera, exc_info=True)
            finally:
                self.conectado = False
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            await asyncio.sleep(espera)
            espera = min(espera * 2, self.ESPERA_MAXIMA)

    async def iniciar(self) -> None:
        if self._tarea is None:
            self._tarea = asyncio.create_task(self._escuchar())

    async def detener(self) -> None:
        if self._tarea is not None:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass
            self._tarea = None
        try:
            await self._cliente.aclose()
        except Exception:
            pass


def crear_bus(url_redis: str = "") -> BusLocal:
    return BusRedis(url_redis) if url_redis else BusLocal()


def _bus_por_defecto() -> BusLocal:
    from app.config import config
    return crear_bus(config.REDIS_URL)


# Instancia compartida por los routers.
bus = _bus_por_defecto()
