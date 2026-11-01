# app/services/ratelimit.py
"""
Limitación de peticiones (rate limit): lógica pura, sin dependencias de FastAPI.

Piezas
  * ip_cliente(): IP real del cliente, también detrás de proxies (Render, Railway, Cloudflare...).
  * AlmacenMemoria / AlmacenRedis / AlmacenConRespaldo: dónde se guardan los contadores.
  * Limitador: contador de "ventana fija" sobre un almacén.

Ventana fija: la ventana empieza con la primera petición de una clave y dura `ventana`
segundos; al terminar, el contador vuelve a 0. Es simple, idéntica en memoria y en Redis y
suficiente para frenar abusos (en el borde entre dos ventanas caben, como mucho, el doble).

Memoria o Redis
  * Sin REDIS_URL los contadores viven en el proceso: correcto con UNA instancia.
  * Con varias instancias (o varios workers) cada una contaría por su cuenta y el límite real
    se multiplicaría: ahí hace falta REDIS_URL para compartir los contadores.
  * Si Redis falla, se usa la memoria local durante unos segundos y se vuelve a intentar: la API
    no se cae por el limitador (con la protección degradada a "por instancia").
"""
import ipaddress
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from app.config import config

logger = logging.getLogger("trading-api")

PREFIJO_REDIS = "trading-api:rl:"
MAX_CLAVES_MEMORIA = 100_000      # tope de claves vivas en memoria (evita crecer sin límite)
INTERVALO_LIMPIEZA = 30.0         # segundos entre barridos de claves vencidas
PAUSA_TRAS_FALLO_REDIS = 5.0      # segundos usando la memoria local tras un error de Redis


# --------------------------------------------------------------------------- IP del cliente

def _parsear_ip(texto: str):
    """IPv4/IPv6 a partir de 'ip', 'ipv4:puerto' o '[ipv6]:puerto'. None si no es una IP."""
    t = texto.strip().strip('"')
    if not t:
        return None
    if t.startswith("["):                      # [2001:db8::1]:443
        fin = t.find("]")
        if fin == -1:
            return None
        t = t[1:fin]
    elif t.count(":") == 1:                    # 203.0.113.7:51234
        t = t.split(":")[0]
    try:
        return ipaddress.ip_address(t)
    except ValueError:
        return None


def normalizar_ip(ip) -> str:
    """
    Clave estable para una IP. Una IPv6 se agrupa por /64: un solo cliente suele controlar un /64
    entero (2^64 direcciones) y, contando direcciones sueltas, eludiría cualquier límite.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        red = ipaddress.ip_network((ip, 64), strict=False)
        return f"{red.network_address}/64"
    return str(ip)


def ip_cliente(scope: dict, proxies_confiables: Optional[int] = None) -> str:
    """
    IP del cliente de una petición ASGI.

    Con `proxies_confiables = N` (TRUSTED_PROXY_COUNT) hay exactamente N proxies de confianza entre
    el cliente y esta aplicación. Cada uno añade a X-Forwarded-For la dirección de quien le habló,
    así que la del cliente real es la N-ésima empezando por la DERECHA. Lo que haya a la izquierda
    lo escribió el propio cliente y no es de fiar (por eso nunca se usa la primera entrada).

    Si hay menos entradas que proxies, o la entrada no es una IP, se usa la dirección del socket:
    es el caso seguro (como mucho, varios clientes comparten un cupo; nunca se puede falsificar).
    Con N = 0 (por defecto) X-Forwarded-For se ignora por completo.
    """
    n = config.TRUSTED_PROXY_COUNT if proxies_confiables is None else proxies_confiables
    cliente = scope.get("client")
    direccion = cliente[0] if cliente else None

    if n > 0:
        valores = [v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-forwarded-for"]
        entradas = [e for e in ",".join(valores).split(",") if e.strip()]
        if len(entradas) >= n:
            ip = _parsear_ip(entradas[-n])
            if ip is not None:
                return normalizar_ip(ip)

    if not direccion:
        return "desconocida"
    ip = _parsear_ip(direccion)
    return normalizar_ip(ip) if ip is not None else direccion[:64]


# --------------------------------------------------------------------------- almacenes

def _segundos_restantes(resta: float) -> int:
    """
    Segundos enteros (redondeo hacia arriba, mínimo 1) hasta el vencimiento. Se redondea antes a milisegundos: con
    relojes flotantes (a + 60) - a puede dar 60.000000000000014 cuando a + 60 cruza una potencia de dos, y el techo
    daba 61 en una ventana de 60 s.
    """
    return max(1, math.ceil(round(resta, 3)))


class AlmacenMemoria:
    """Contadores en el proceso, con tope de tamaño y limpieza de claves vencidas."""

    bloqueante = False   # no hace entrada/salida de red: se puede llamar desde el bucle de eventos

    def __init__(self, max_claves: int = MAX_CLAVES_MEMORIA, reloj: Callable[[], float] = time.monotonic):
        self._datos: Dict[str, list] = {}          # clave -> [contador, instante_de_vencimiento]
        self._cerrojo = threading.Lock()           # las rutas síncronas corren en hilos
        self._reloj = reloj
        self._max = max_claves
        self._proxima_limpieza = reloj() + INTERVALO_LIMPIEZA

    def _limpiar(self, ahora: float) -> None:
        if ahora < self._proxima_limpieza and len(self._datos) < self._max:
            return
        self._proxima_limpieza = ahora + INTERVALO_LIMPIEZA
        for clave in [c for c, (_, vence) in self._datos.items() if vence <= ahora]:
            del self._datos[clave]
        if len(self._datos) >= self._max:
            # Todo son claves vivas: se descarta el 10 % al que menos le queda (el daño mínimo).
            candidatas = sorted(self._datos.items(), key=lambda kv: kv[1][1])
            for clave, _ in candidatas[: max(1, self._max // 10)]:
                del self._datos[clave]

    def incrementar(self, clave: str, ventana: int) -> Tuple[int, int]:
        """Suma 1. Devuelve (contador, segundos hasta que la ventana se reinicia)."""
        with self._cerrojo:
            ahora = self._reloj()
            self._limpiar(ahora)
            registro = self._datos.get(clave)
            if registro is None or registro[1] <= ahora:
                registro = [0, ahora + ventana]
                self._datos[clave] = registro
            registro[0] += 1
            return registro[0], _segundos_restantes(registro[1] - ahora)

    def consultar(self, clave: str) -> Tuple[int, int]:
        """Lee sin sumar. (0, 0) si la clave no existe o ya venció."""
        with self._cerrojo:
            ahora = self._reloj()
            registro = self._datos.get(clave)
            if registro is None or registro[1] <= ahora:
                return 0, 0
            return registro[0], _segundos_restantes(registro[1] - ahora)

    def borrar(self, clave: str) -> None:
        with self._cerrojo:
            self._datos.pop(clave, None)

    def vaciar(self) -> None:
        with self._cerrojo:
            self._datos.clear()

    def __len__(self) -> int:
        return len(self._datos)


class AlmacenRedis:
    """Contadores compartidos entre instancias. Cada operación es atómica (MULTI/EXEC)."""

    bloqueante = True    # cada llamada es una ida y vuelta de red

    def __init__(self, cliente):
        self._r = cliente

    @classmethod
    def desde_url(cls, url: str) -> "AlmacenRedis":
        import redis
        # No conecta hasta la primera orden. Tiempos cortos: un Redis lento no debe frenar la API.
        return cls(redis.Redis.from_url(url, socket_timeout=0.3, socket_connect_timeout=0.3,
                                        health_check_interval=30))

    def incrementar(self, clave: str, ventana: int) -> Tuple[int, int]:
        k = PREFIJO_REDIS + clave
        pipe = self._r.pipeline(transaction=True)
        pipe.set(k, 0, ex=ventana, nx=True)      # crea la clave con caducidad solo si no existe
        pipe.incr(k)
        pipe.pttl(k)
        _, contador, pttl = pipe.execute()
        if pttl < 0:                             # sin caducidad: no debería ocurrir, pero no puede
            self._r.expire(k, ventana)           # quedar una clave que bloquee para siempre
            pttl = ventana * 1000
        return int(contador), max(1, math.ceil(pttl / 1000))

    def consultar(self, clave: str) -> Tuple[int, int]:
        k = PREFIJO_REDIS + clave
        pipe = self._r.pipeline(transaction=True)
        pipe.get(k)
        pipe.pttl(k)
        valor, pttl = pipe.execute()
        if valor is None or pttl < 0:
            return 0, 0
        return int(valor), max(1, math.ceil(pttl / 1000))

    def borrar(self, clave: str) -> None:
        self._r.delete(PREFIJO_REDIS + clave)

    def vaciar(self) -> None:
        for k in self._r.scan_iter(match=PREFIJO_REDIS + "*", count=500):
            self._r.delete(k)


class AlmacenConRespaldo:
    """Usa `principal` (Redis) y, si falla, `respaldo` (memoria) durante unos segundos."""

    def __init__(self, principal, respaldo, pausa: float = PAUSA_TRAS_FALLO_REDIS,
                 reloj: Callable[[], float] = time.monotonic):
        self.principal, self.respaldo = principal, respaldo
        self._pausa, self._reloj = pausa, reloj
        self._reintentar_desde = 0.0
        self._degradado = False

    @property
    def bloqueante(self) -> bool:
        return self.principal.bloqueante

    @property
    def degradado(self) -> bool:
        return self._degradado

    def _llamar(self, nombre: str, *args):
        if self._reloj() >= self._reintentar_desde:
            try:
                resultado = getattr(self.principal, nombre)(*args)
                if self._degradado:
                    self._degradado = False
                    logger.info("Rate limit: Redis disponible de nuevo; contadores compartidos restablecidos")
                return resultado
            except Exception as e:
                self._reintentar_desde = self._reloj() + self._pausa
                if not self._degradado:
                    self._degradado = True
                    logger.warning("Rate limit: Redis no responde (%s: %s); se usan contadores locales "
                                   "por instancia hasta que se recupere", type(e).__name__, e)
        return getattr(self.respaldo, nombre)(*args)

    def incrementar(self, clave: str, ventana: int) -> Tuple[int, int]:
        return self._llamar("incrementar", clave, ventana)

    def consultar(self, clave: str) -> Tuple[int, int]:
        return self._llamar("consultar", clave)

    def borrar(self, clave: str) -> None:
        # El respaldo también: si el contador se creó mientras Redis estaba caído, debe olvidarse igual.
        self.respaldo.borrar(clave)
        self._llamar("borrar", clave)

    def vaciar(self) -> None:
        self.respaldo.vaciar()
        self._llamar("vaciar")


# --------------------------------------------------------------------------- limitador

@dataclass(frozen=True)
class Resultado:
    permitido: bool
    contador: int
    limite: int
    restante: int       # peticiones que aún caben en la ventana (0 si se superó)
    reinicia_en: int    # segundos hasta que la ventana se reinicia


class Limitador:
    """Contador de ventana fija sobre un almacén."""

    def __init__(self, almacen):
        self.almacen = almacen

    @property
    def bloqueante(self) -> bool:
        return self.almacen.bloqueante

    def golpear(self, clave: str, limite: int, ventana: int) -> Resultado:
        """Registra una petición y dice si cabe (las rechazadas también cuentan hasta que reinicie)."""
        contador, reinicia = self.almacen.incrementar(clave, ventana)
        return Resultado(contador <= limite, contador, limite, max(0, limite - contador), reinicia)

    def contar(self, clave: str, ventana: int) -> Tuple[int, int]:
        return self.almacen.incrementar(clave, ventana)

    def leer(self, clave: str) -> Tuple[int, int]:
        return self.almacen.consultar(clave)

    def olvidar(self, clave: str) -> None:
        self.almacen.borrar(clave)

    def reiniciar(self) -> None:
        self.almacen.vaciar()


def crear_limitador(url_redis: str = "") -> Limitador:
    memoria = AlmacenMemoria()
    if not url_redis:
        return Limitador(memoria)
    try:
        principal = AlmacenRedis.desde_url(url_redis)
    except Exception as e:   # URL mal formada o paquete ausente: se sigue con memoria local
        logger.error("Rate limit: no se pudo configurar Redis (%s: %s); se usa memoria local", type(e).__name__, e)
        return Limitador(memoria)
    return Limitador(AlmacenConRespaldo(principal, memoria))


# Instancia compartida por el middleware y por la protección del login.
limitador = crear_limitador(config.REDIS_URL)


async def golpear_sin_bloquear(clave: str, limite: int, ventana: int) -> Optional[Resultado]:
    """
    `limitador.golpear` para código async: con Redis la llamada es una ida y vuelta de red y se hace
    en un hilo para no frenar el bucle de eventos. Si el limitador falla devuelve None (se deja pasar
    y se registra), la misma política que el middleware: un fallo del limitador no tumba la API.
    """
    import anyio
    try:
        if limitador.bloqueante:
            return await anyio.to_thread.run_sync(limitador.golpear, clave, limite, ventana)
        return limitador.golpear(clave, limite, ventana)
    except Exception:
        logger.exception("Rate limit: error al evaluar '%s'; se deja pasar", clave.split(":")[0])
        return None
