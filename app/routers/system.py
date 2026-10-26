# app/routers/system.py
from fastapi import APIRouter, Depends
from collections import defaultdict
import psutil
import os
from utils.authorization import require_admin

router = APIRouter(prefix="/system", tags=["System"])

# Contador de peticiones por endpoint
endpoint_counts = defaultdict(int)

@router.get("/metrics")
def get_metrics(admin: dict = Depends(require_admin)):
    """Métricas del sistema (solo administradores)"""
    return {
        "peticiones_por_endpoint": dict(endpoint_counts),
        "memoria_usada_mb": round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 2),
        "cpu_percent": psutil.cpu_percent(interval=0.1)
    }

@router.get("/endpoints")
def list_endpoints(admin: dict = Depends(require_admin)):
    """Lista todos los endpoints registrados (solo administradores)"""
    from app.main import app
    
    endpoints = []
    for route in app.routes:
        if hasattr(route, "methods"):
            for method in route.methods:
                if method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
                    endpoints.append({
                        "path": route.path,
                        "method": method,
                        "name": route.name
                    })
    
    return endpoints