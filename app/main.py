# app/main.py
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.routers.trades import router as trades_router
from app.routers.intensive_review import router as intensive_review_router
from app.routers.users import router as users_router
from app.connections.intensive_review_db_conn import IntensiveReviewConnection
from app.connections.trading_db_conn import TradingConnection

app = FastAPI(title="Trading API", version="1.0.0")

# Registrar router de trades
app.include_router(trades_router)

#Registrar router de intensive_review
app.include_router(intensive_review_router)

#Registrar router de usuarios
app.include_router(users_router)

# Diccionario para contar requests
request_counts = {}

# Manejador global de errores de validación
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):
    return JSONResponse(
        status_code=422,
        content={
            "error": "Datos inválidos",
            "detalles": exc.errors()
        }
    )


# Manejador global de errores inesperados
@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request,
    exc: Exception
):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error interno del servidor",
            "mensaje": str(exc)
        }
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware para loggear y contar todas las peticiones."""

    start_time = time.time()

    # Procesar la petición
    response = await call_next(request)

    # Calcular duración
    duration = time.time() - start_time

    # Obtener la ruta definida por FastAPI
    endpoint = request.scope.get("route")

    if endpoint:
        endpoint_path = endpoint.path
    else:
        endpoint_path = request.url.path

    # Incrementar contador
    request_counts[endpoint_path] = request_counts.get(endpoint_path, 0) + 1

    # Loggear
    print(
        f"{request.method} {request.url.path} "
        f"- {response.status_code} "
        f"- {duration:.3f}s"
    )

    # Agregar header con duración
    response.headers["X-Process-Time"] = str(duration)

    return response


@app.get("/stats")
def get_stats():
    """Devuelve la cantidad de requests por endpoint."""
    return {
        "requests": request_counts
    }

@app.get("/")
def raiz():
    return {"mensaje": "Trading API v2 - Con autenticación"}

TradingConnection().init_db()
IntensiveReviewConnection().init_db()