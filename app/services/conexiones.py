# app/services/conexiones.py
"""
Registro de conexiones abiertas por usuario (para topar cuántas puede tener a la vez, sumando TODOS los procesos).

  * Sin REDIS_URL: se cuenta en la memoria del proceso (correcto con un solo proceso).
  * Con REDIS_URL: un conjunto ordenado por usuario en Redis, donde cada conexión es un "alquiler" que caduca
    (`ttl` s) y se renueva mientras la conexión vive. Si un proceso muere sin liberar sus conexiones, los
    alquileres vencen solos: no quedan cupos "fantasma" para siempre, que es lo que pasaría con un contador
    que solo se incrementa al abrir y decrementa al cerrar.
  * Si Redis falla se usa el conteo local (por proceso) y se registra el aviso: un fallo de Redis no impide chatear.
"""
import logging
import time
from typing import Dict

logger = logging.getLogger("trading-api")

# KEYS[1] = conjunto del usuario; ARGV = ttl, id de conexión, máximo. Atómico: dos conexiones simultáneas no
# pueden colarse por encima del tope. Si la conexión ya está registrada solo se renueva (no cuenta dos veces).
_SCRIPT = """
local t = redis.call('TIME')
local ahora = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ahora)
local ttl = tonumber(ARGV[1])
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then
  redis.call('ZADD', KEYS[1], ahora + ttl, ARGV[2])
  return 1
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  return 0
end
redis.call('ZADD', KEYS[1], ahora + ttl, ARGV[2])
redis.call('EXPIRE', KEYS[1], ttl * 2)
return 1
"""
SIN_TOPE = 10 ** 9


class RegistroLocal:
    def __init__(self, reloj=time.monotonic):
        self._datos: Dict[int, Dict[str, float]] = {}
        self._reloj = reloj

    async def registrar(self, usuario_id: int, conn_id: str, maximo: int, ttl: float) -> bool:
        ahora = self._reloj()
        conexiones = self._datos.setdefault(usuario_id, {})
        for c in [c for c, vence in conexiones.items() if vence <= ahora]:
            del conexiones[c]
        if conn_id not in conexiones and len(conexiones) >= maximo:
            if not conexiones:
                del self._datos[usuario_id]
            return False
        conexiones[conn_id] = ahora + ttl
        return True

    async def renovar(self, usuario_id: int, conn_id: str, ttl: float) -> None:
        await self.registrar(usuario_id, conn_id, SIN_TOPE, ttl)

    async def liberar(self, usuario_id: int, conn_id: str) -> None:
        conexiones = self._datos.get(usuario_id)
        if conexiones is not None:
            conexiones.pop(conn_id, None)
            if not conexiones:
                del self._datos[usuario_id]

    def abiertas(self, usuario_id: int) -> int:
        return len(self._datos.get(usuario_id, {}))

    async def cerrar(self) -> None:
        pass


class RegistroRedis(RegistroLocal):
    def __init__(self, url: str, prefijo: str = "tradingapi:", reloj=time.monotonic):
        super().__init__(reloj)
        import redis.asyncio as aioredis
        self._cliente = aioredis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        self._script = self._cliente.register_script(_SCRIPT)
        self._prefijo = prefijo
        self._en_redis: Dict[str, int] = {}      # conexiones registradas en Redis (para liberarlas allí)

    def _clave(self, usuario_id: int) -> str:
        return f"{self._prefijo}chatconn:{usuario_id}"

    async def registrar(self, usuario_id: int, conn_id: str, maximo: int, ttl: float) -> bool:
        try:
            ok = bool(await self._script(keys=[self._clave(usuario_id)], args=[ttl, conn_id, maximo]))
        except Exception:
            logger.warning("Conexiones: Redis no responde; se cuenta solo en este proceso", exc_info=True)
            return await super().registrar(usuario_id, conn_id, maximo, ttl)
        if ok:
            self._en_redis[conn_id] = usuario_id
        return ok

    async def renovar(self, usuario_id: int, conn_id: str, ttl: float) -> None:
        if conn_id in self._en_redis:
            await self.registrar(usuario_id, conn_id, SIN_TOPE, ttl)
        else:
            await super().renovar(usuario_id, conn_id, ttl)

    async def liberar(self, usuario_id: int, conn_id: str) -> None:
        await super().liberar(usuario_id, conn_id)
        if self._en_redis.pop(conn_id, None) is not None:
            try:
                await self._cliente.zrem(self._clave(usuario_id), conn_id)
            except Exception:
                logger.warning("Conexiones: no se pudo liberar en Redis (vencerá sola)", exc_info=True)

    async def cerrar(self) -> None:
        try:
            await self._cliente.aclose()
        except Exception:
            pass


def crear_registro(url_redis: str = "") -> RegistroLocal:
    return RegistroRedis(url_redis) if url_redis else RegistroLocal()


def _registro_por_defecto() -> RegistroLocal:
    from app.config import config
    return crear_registro(config.REDIS_URL)


# Instancia compartida por el chat.
registro = _registro_por_defecto()
