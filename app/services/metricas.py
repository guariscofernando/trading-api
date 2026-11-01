# app/services/metricas.py
"""
Métricas en formato Prometheus. Son por proceso: con WEB_CONCURRENCY>1 cada scrape lee UN proceso (el que
atienda la petición), así que las tendencias valen pero los totales exactos no; para eso, una sola instancia
o agregar en el sistema de monitoreo (Grafana Cloud, Datadog...) por instancia.
"""
import hmac
import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

registro_metricas = CollectorRegistry()      # propio: no mezcla las métricas por defecto del intérprete

PETICIONES = Counter("http_peticiones_total", "Peticiones http", ["metodo", "ruta", "estado"],
                     registry=registro_metricas)
DURACION = Histogram("http_duracion_segundos", "Duración de las peticiones http", ["metodo", "ruta"],
                     buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10), registry=registro_metricas)
ORDENES = Counter("paper_ordenes_procesadas_total", "Órdenes pendientes procesadas por el motor", ["resultado"],
                  registry=registro_metricas)
CICLOS = Counter("paper_ciclos_total", "Ciclos del motor de órdenes", ["resultado"], registry=registro_metricas)
ULTIMO_CICLO_OK = Gauge("paper_ultimo_ciclo_ok_timestamp", "Unix time del último ciclo del motor sin excepción",
                        registry=registro_metricas)
COINGECKO = Counter("coingecko_peticiones_total", "Peticiones salientes a CoinGecko", ["resultado"],
                    registry=registro_metricas)
LOGIN_BLOQUEOS = Counter("login_bloqueos_total", "Veces que un cubo de fallos de login cruzó el umbral",
                         registry=registro_metricas)
SESIONES_REVOCADAS = Counter("sesiones_revocadas_total", "Cierres de sesión y cambios de contraseña",
                             registry=registro_metricas)

ULTIMO_CICLO_OK.set(time.time())      # arranque = "recién vivo": la alerta de motor parado cuenta desde aquí


def ruta_de(scope) -> str:
    """Plantilla de la ruta (/paper/ordenes/{orden_id}), nunca la URL real: evita series infinitas."""
    ruta = scope.get("route")
    return getattr(ruta, "path", None) or "no_encontrada"


def token_valido(cabecera: str, esperado: str) -> bool:
    """Comparación en tiempo constante del 'Authorization: Bearer ...'. Sin token configurado, nada entra."""
    if not esperado:
        return False
    esquema, _, valor = (cabecera or "").partition(" ")
    return esquema.lower() == "bearer" and hmac.compare_digest(valor.strip().encode(), esperado.encode())


def exportar() -> tuple:
    return generate_latest(registro_metricas), CONTENT_TYPE_LATEST
