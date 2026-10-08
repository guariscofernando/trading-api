# app/main.py
import asyncio
import json
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.routers import trades, users, precios, analisis, websocket, dashboard, binance_router, orders_router, system, riesgo_router, backtest_router
from app.config import config
from app.middleware import LoggingMiddleware, RateLimitMiddleware
from app.routers.websocket import verificar_alertas
from app.migrations.create_trading import TradingCreate

logger = logging.getLogger("trading-api")

app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description=config.APP_DESCRIPTION,
    docs_url="/docs" if not config.is_production else None,
    redoc_url="/redoc" if not config.is_production else None,
    openapi_url="/openapi.json" if not config.is_production else None,
)

# Agregar rutas html estaticas
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración CORS (leída desde variables de entorno via config.py)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Agregar middlewares (el orden importa)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=100, window_seconds=60)

# Incluir routers
app.include_router(users.router)
app.include_router(trades.router)
app.include_router(precios.router)
app.include_router(analisis.router)
app.include_router(websocket.router)
app.include_router(dashboard.router)
app.include_router(binance_router.router)
app.include_router(orders_router.router)
app.include_router(system.router)
app.include_router(riesgo_router.router)
app.include_router(backtest_router.router)

def _json_seguro(valor):
    """
    Deja el valor apto para devolverlo en un error de validación.
    - NaN / Infinity (que Python acepta al leer JSON) no se pueden volver a serializar:
      sin esto un simple {"x": Infinity} inválido provocaba un 500 en vez de un 422.
    - Las listas/dicts grandes se resumen para no devolver al cliente miles de elementos.
    """
    try:
        json.dumps(valor, allow_nan=False)
    except (TypeError, ValueError):
        return str(valor)[:200]
    if isinstance(valor, (list, dict)) and len(valor) > 20:
        return f"<{type(valor).__name__} de {len(valor)} elementos>"
    return valor


# Manejador global de errores de validación
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errores = []
    for error in exc.errors():
        error_limpio = dict(error)
        if "ctx" in error_limpio and "error" in error_limpio["ctx"]:
            error_limpio["ctx"] = {"error": str(error_limpio["ctx"]["error"])}
        if "input" in error_limpio:
            error_limpio["input"] = _json_seguro(error_limpio["input"])
        errores.append(error_limpio)
    return JSONResponse(status_code=422, content={"detail": errores})


# Manejador global de errores inesperados
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # El detalle va al log; al cliente solo en desarrollo (en producción
    # podría filtrar SQL, rutas internas u otros datos sensibles).
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    content = {"error": "Error interno del servidor"}
    if not config.is_production:
        content["mensaje"] = str(exc)
    return JSONResponse(status_code=500, content=content)


@app.get("/")
def raiz():
    return {
        "mensaje": f"{config.APP_NAME} v{config.APP_VERSION}",
        "version": config.APP_VERSION,
        "docs": "/docs" if not config.is_production else None,
        "endpoints": {
            "usuarios": "/usuarios",
            "trades": "/trades",
            "precios": "/precios",
            "analisis": "/analisis",
            "dashboard": "/dashboard",
            "websocket": "/websocket"
        }
    }

@app.get("/health")
def health_check():
    return {"status": "ok", "version": config.APP_VERSION}

@app.get("/info")
def api_info():
    """Información detallada de la API"""
    return {
        "nombre": config.APP_NAME,
        "version": config.APP_VERSION,
        "endpoints_publicos": [
            "GET /health",
            "GET /info",
            "POST /usuarios/registro",
            "POST /usuarios/login",
            "GET /precios/{coin_id}",
            "GET /precios/multiples",
            "GET /precios/buscar/{query}"
        ],
        "endpoints_protegidos": [
            "POST /trades/",
            "GET /trades/",
            "GET /trades/{id}",
            "PATCH /trades/{id}",
            "DELETE /trades/{id}",
            "GET /analisis/pnl-en-vivo"
        ],
        "autenticacion": "Bearer Token (JWT)"
    }

TradingCreate().init_db()

@app.on_event("startup")
async def iniciar_tareas_background():
    asyncio.create_task(verificar_alertas())