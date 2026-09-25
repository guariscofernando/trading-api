# app/main.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.routers import trades, intensive_review, users, precios, analisis, websocket
from app.connections.intensive_review_db_conn import IntensiveReviewConnection
from app.connections.trading_db_conn import TradingConnection
from app.config import config
from app.middleware import LoggingMiddleware, RateLimitMiddleware

app = FastAPI(
    title="Trading API",
    version="3.0.0",
    description="API completa para gestión de trades con autenticación JWT"
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
app.include_router(intensive_review.router)


# Manejador global de errores de validación
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errores = []
    for error in exc.errors():
        error_limpio = dict(error)
        if "ctx" in error_limpio and "error" in error_limpio["ctx"]:
            error_limpio["ctx"] = {"error": str(error_limpio["ctx"]["error"])}
        errores.append(error_limpio)
    return JSONResponse(status_code=422, content={"detail": errores})


# Manejador global de errores inesperados
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error interno del servidor",
            "mensaje": str(exc)
        }
    )


@app.get("/")
def raiz():
    return {
        "mensaje": "Trading API v3",
        "version": "3.0.0",
        "docs": "/docs",
        "endpoints": {
            "usuarios": "/usuarios",
            "trades": "/trades",
            "precios": "/precios",
            "analisis": "/analisis",
            "websocket": "/websocket"
        }
    }

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "3.0.0"}

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

TradingConnection().init_db()
IntensiveReviewConnection().init_db()