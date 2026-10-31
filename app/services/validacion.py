# app/services/validacion.py
"""Formatos admitidos para los identificadores que acaban en llamadas a servicios externos (CoinGecko, Binance)."""
import re

# Patrones para Path(...) / Query(...) de FastAPI (si no coinciden: 422 sin tocar la red)
PATRON_COIN_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
PATRON_MONEDA = r"^[a-z]{2,10}$"
PATRON_SIMBOLO = r"^[A-Za-z0-9]{2,20}$"

MAX_MONEDAS_POR_CONSULTA = 20

_COIN_ID = re.compile(PATRON_COIN_ID)


def lista_de_coin_ids(texto: str) -> list:
    """'bitcoin, ethereum' -> ['bitcoin', 'ethereum']. Lanza ValueError si algo no es un id válido."""
    ids = [c.strip().lower() for c in texto.split(",") if c.strip()]
    if not ids:
        raise ValueError("Indica al menos una moneda")
    if len(ids) > MAX_MONEDAS_POR_CONSULTA:
        raise ValueError(f"Máximo {MAX_MONEDAS_POR_CONSULTA} monedas por consulta")
    for c in ids:
        if not _COIN_ID.match(c):
            raise ValueError("Identificador de moneda inválido (solo minúsculas, números y guiones)")
    return sorted(set(ids))
