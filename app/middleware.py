# app/middleware.py
import re
import time
import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import anyio
from app.config import config
from app.services.ratelimit import Limitador, Resultado, ip_cliente, limitador
from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trading-api")

_TOKEN_EN_URL = re.compile(r"([?&]token=)[^&\s\"]+")


class OcultarTokenEnLogs(logging.Filter):
    """Tapa el valor de ?token=... en los logs de uvicorn.

    Los WebSockets (/ws/chat, /ws/notificaciones) reciben el JWT en la URL y uvicorn escribe la
    URL completa: sin este filtro cualquiera que lea los logs podría usar los tokens (válidos 60 min).
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_TOKEN_EN_URL.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN_EN_URL.sub(r"\1***", record.msg)
        return True


def instalar_filtro_de_tokens() -> None:
    # Las peticiones http van a uvicorn.access, pero las conexiones WebSocket se registran en uvicorn.error.
    for nombre in ("uvicorn.access", "uvicorn.error"):
        registro = logging.getLogger(nombre)
        if not any(isinstance(x, OcultarTokenEnLogs) for x in registro.filters):
            registro.addFilter(OcultarTokenEnLogs())


from app.services.metricas import DURACION, PETICIONES, ruta_de


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log de la petición entrante (con la IP que usa el rate limit: permite comprobar TRUSTED_PROXY_COUNT)
        ip = ip_cliente(request.scope)
        logger.info(f"→ {request.method} {request.url.path} ip={ip}")
        
        # Procesar la petición
        response = await call_next(request)
        
        # Calcular duración
        duration = time.time() - start_time
        
        # Log de la respuesta
        logger.info(
            f"← {request.method} {request.url.path} "
            f"- {response.status_code} - {duration:.3f}s"
        )
        
        ruta = ruta_de(request.scope)
        PETICIONES.labels(request.method, ruta, str(response.status_code)).inc()
        DURACION.labels(request.method, ruta).observe(duration)

        # Agregar headers de diagnóstico
        response.headers["X-Process-Time"] = str(duration)
        response.headers["X-API-Version"] = config.APP_VERSION
        
        return response

@dataclass(frozen=True)
class Regla:
    """Un límite: `limite` peticiones por IP cada `ventana` segundos, para un método/ruta (o todos)."""
    nombre: str
    limite: int
    ventana: int
    metodo: Optional[str] = None
    ruta: Optional[str] = None

    def aplica(self, metodo: str, ruta: str) -> bool:
        return (self.metodo is None or self.metodo == metodo) and (self.ruta is None or self.ruta == ruta)


def reglas_por_defecto() -> List[Regla]:
    """El límite general y dos más estrictos para las rutas que se atacan con scripts."""
    return [
        Regla("global", config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW),
        Regla("login", config.LOGIN_RATE_LIMIT, 60, "POST", "/usuarios/login"),
        Regla("registro", config.REGISTER_RATE_LIMIT, 3600, "POST", "/usuarios/registro"),
        Regla("cambiar_password", config.LOGIN_RATE_LIMIT, 60, "POST", "/usuarios/cambiar-password"),
    ]


class SecurityHeadersMiddleware:
    """
    Cabeceras de seguridad en TODAS las respuestas http (también 429 y errores): va como capa más externa.

      X-Content-Type-Options: nosniff        el navegador no adivina tipos de contenido
      X-Frame-Options: DENY                  la API no se incrusta en iframes (clickjacking)
      Referrer-Policy: no-referrer           no filtra URLs (llevan ?token= en los WebSockets) a terceros
      Cache-Control: no-store                las respuestas con datos de usuario no se guardan en cachés compartidas
                                             (solo si la ruta no puso la suya; /static y la documentación quedan fuera)
      Content-Security-Policy                'default-src none; frame-ancestors none' para las respuestas de la API
      Strict-Transport-Security              solo en producción (la plataforma sirve HTTPS); un año
    """
    _SIN_CSP_NI_NO_STORE = ("/static", "/docs", "/redoc", "/openapi.json")

    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        es_api = not scope["path"].startswith(self._SIN_CSP_NI_NO_STORE)

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                h = MutableHeaders(scope=mensaje)
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                if es_api:
                    h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                    if "cache-control" not in h:
                        h["Cache-Control"] = "no-store"
                if self.hsts:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(mensaje)

        await self.app(scope, receive, enviar)


class RateLimitMiddleware:
    """
    Límite de peticiones por IP real del cliente (ver app/services/ratelimit.py).

    ASGI puro (no BaseHTTPMiddleware). Responde 429 con Retry-After y, en las respuestas
    normales, añade X-RateLimit-Limit / -Remaining / -Reset del límite general.
    Va POR DENTRO de CORS (ver main.py) para que el navegador pueda leer también los 429.
    """

    def __init__(self, app, reglas: Optional[Sequence[Regla]] = None, limitador_: Optional[Limitador] = None,
                 rutas_exentas: Sequence[str] = ("/health",)):
        self.app = app
        self._reglas = list(reglas) if reglas is not None else None   # None: se leen de config en cada petición
        self._limitador = limitador_
        self.rutas_exentas = frozenset(rutas_exentas)

    @property
    def limitador(self) -> Limitador:
        return self._limitador if self._limitador is not None else limitador

    @property
    def reglas(self) -> List[Regla]:
        return self._reglas if self._reglas is not None else reglas_por_defecto()

    def reiniciar(self) -> None:
        self.limitador.reiniciar()

    def _evaluar(self, ip: str, metodo: str, ruta: str) -> Tuple[Optional[Tuple[Regla, Resultado]], Optional[Resultado]]:
        """Aplica las reglas en orden. Devuelve (regla que bloquea y su resultado, resultado del límite general)."""
        general = None
        for regla in self.reglas:
            if not regla.aplica(metodo, ruta):
                continue
            resultado = self.limitador.golpear(f"{regla.nombre}:{ip}", regla.limite, regla.ventana)
            if general is None:
                general = resultado
            if not resultado.permitido:
                return (regla, resultado), general
        return None, general

    async def __call__(self, scope, receive, send):
        tipo = scope["type"]
        # Los WebSockets también cuentan: cada conexión nueva (el "handshake") gasta cupo del límite general.
        # Sin esto, /ws/chat y /ws/precios-reales (públicos) quedaban fuera de cualquier límite.
        metodo = "WS" if tipo == "websocket" else scope.get("method")
        if tipo not in ("http", "websocket") or metodo == "OPTIONS" or scope["path"] in self.rutas_exentas:
            await self.app(scope, receive, send)
            return

        ip = ip_cliente(scope)
        try:
            if self.limitador.bloqueante:       # Redis: la entrada/salida de red no debe frenar el bucle de eventos
                bloqueo, general = await anyio.to_thread.run_sync(self._evaluar, ip, metodo, scope["path"])
            else:
                bloqueo, general = self._evaluar(ip, metodo, scope["path"])
        except Exception:
            # Un fallo del limitador no debe tumbar la API: se deja pasar y se registra.
            logger.exception("Rate limit: error al evaluar la petición; se deja pasar")
            await self.app(scope, receive, send)
            return

        if bloqueo is not None and tipo == "websocket":
            # Se rechaza el handshake sin aceptarlo (el servidor responde 403 al cliente).
            logger.warning("Rate limit: conexión WebSocket rechazada ip=%s ruta=%s", ip, scope["path"])
            await receive()                                        # websocket.connect
            await send({"type": "websocket.close", "code": 1013})  # 1013 = "intenta más tarde"
            return

        if bloqueo is not None:
            regla, resultado = bloqueo
            espera = str(resultado.reinicia_en)
            respuesta = JSONResponse(
                status_code=429,
                content={"detail": f"Demasiadas peticiones. Intenta de nuevo en {resultado.reinicia_en} segundos."},
                headers={"Retry-After": espera, "X-RateLimit-Limit": str(resultado.limite),
                         "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": espera},
            )
            await respuesta(scope, receive, send)
            return

        async def enviar_con_cabeceras(mensaje):
            if mensaje["type"] == "http.response.start" and general is not None:
                cabeceras = MutableHeaders(scope=mensaje)
                cabeceras["X-RateLimit-Limit"] = str(general.limite)
                cabeceras["X-RateLimit-Remaining"] = str(general.restante)
                cabeceras["X-RateLimit-Reset"] = str(general.reinicia_en)
            await send(mensaje)

        await self.app(scope, receive, enviar_con_cabeceras)
