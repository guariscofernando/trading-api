# app/services/cache.py
from datetime import datetime, timedelta
from typing import Any, Optional
import json
import threading

MAX_ENTRADAS = 5000


class SimpleCache:
    """
    Caché simple en memoria, ACOTADO: varias rutas públicas lo llenan con claves que elige el visitante
    (monedas, símbolos...), así que sin tope un script podía agotar la memoria del proceso.
    Al llegar al tope se descartan primero las entradas vencidas y, si no basta, las más antiguas.
    """

    def __init__(self, max_entradas: int = MAX_ENTRADAS):
        self.cache = {}
        self.max_entradas = max_entradas
        self._cerrojo = threading.Lock()      # lo usan rutas async y rutas síncronas (hilos)
    
    def get(self, key: str) -> Optional[Any]:
        """Obtiene un valor del caché si no está expirado"""
        entrada = self.cache.get(key)
        if entrada is None:
            return None
        valor, expiracion = entrada
        if datetime.now() < expiracion:
            return valor
        self.cache.pop(key, None)
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: int = 60):
        """Guarda un valor en caché con tiempo de vida"""
        ahora = datetime.now()
        expiracion = ahora + timedelta(seconds=ttl_seconds)
        with self._cerrojo:
            self.cache.pop(key, None)             # al reinsertar la clave pasa a ser la más reciente
            if len(self.cache) >= self.max_entradas:
                for k in [k for k, (_, exp) in self.cache.items() if exp <= ahora]:
                    del self.cache[k]
                exceso = len(self.cache) - self.max_entradas + 1
                for k in list(self.cache)[:max(exceso, 0)]:
                    del self.cache[k]
            self.cache[key] = (value, expiracion)
    
    def delete(self, key: str):
        """Elimina un valor del caché"""
        self.cache.pop(key, None)
    
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


async def _vaciar_por_bus(_datos: dict) -> None:
    cache.clear()


# Vaciar el caché debe llegar a todos los procesos: cada uno tiene el suyo.
from app.services.bus import bus  # noqa: E402

bus.registrar("cache_clear", _vaciar_por_bus)
