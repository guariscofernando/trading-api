# app/services/cache.py
from datetime import datetime, timedelta
from typing import Any, Optional
import json

class SimpleCache:
    """Caché simple en memoria"""
    
    def __init__(self):
        self.cache = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Obtiene un valor del caché si no está expirado"""
        if key in self.cache:
            valor, expiracion = self.cache[key]
            if datetime.now() < expiracion:
                return valor
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: int = 60):
        """Guarda un valor en caché con tiempo de vida"""
        expiracion = datetime.now() + timedelta(seconds=ttl_seconds)
        self.cache[key] = (value, expiracion)
    
    def delete(self, key: str):
        """Elimina un valor del caché"""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """Limpia todo el caché"""
        self.cache.clear()
    
    def stats(self):
        """Estadísticas del caché"""
        return {
            "entradas": len(self.cache),
            "claves": list(self.cache.keys())[:10]  # Primeras 10 claves
        }

# Instancia global
cache = SimpleCache()