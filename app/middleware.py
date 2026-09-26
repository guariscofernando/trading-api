# app/middleware.py
import time
import logging
from app.config import config
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trading-api")

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log de la petición entrante
        logger.info(f"→ {request.method} {request.url.path}")
        
        # Procesar la petición
        response = await call_next(request)
        
        # Calcular duración
        duration = time.time() - start_time
        
        # Log de la respuesta
        logger.info(
            f"← {request.method} {request.url.path} "
            f"- {response.status_code} - {duration:.3f}s"
        )
        
        # Agregar headers de diagnóstico
        response.headers["X-Process-Time"] = str(duration)
        response.headers["X-API-Version"] = config.APP_VERSION
        
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting simple por IP"""
    
    def __init__(self, app, max_requests=100, window_seconds=60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = {}
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        now = time.time()
        
        # Limpiar peticiones viejas
        if client_ip in self.requests:
            self.requests[client_ip] = [
                t for t in self.requests[client_ip]
                if now - t < self.window_seconds
            ]
        else:
            self.requests[client_ip] = []
        
        # Verificar límite
        if len(self.requests[client_ip]) >= self.max_requests:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Demasiadas peticiones. Intenta más tarde."}
            )
        
        self.requests[client_ip].append(now)
        return await call_next(request)