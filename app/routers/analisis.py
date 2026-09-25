# app/routers/analisis.py
from fastapi import APIRouter, Depends
from utils.authorization import get_current_user
from app.dao.TradeDAO import TradeDAO
from app.services.coingecko import obtener_precios_multiples
from app.services.cache import cache
from app.dao.WatchlistDAO import WatchlistDAO
from app.dto.WatchlistDTO import WatchlistCreate, WatchlistResponse

watchlist_dao = WatchlistDAO()
trade_dao = TradeDAO()

router = APIRouter(prefix="/analisis", tags=["Análisis"])



# Mapeo de símbolos a IDs de CoinGecko
COIN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot"
}


def _calcular_pnl_por_activo(trades: list, precios_actuales: dict) -> dict:
    """Calcula cantidad, costo, valor actual y P&L por activo.
    Función compartida por /pnl-en-vivo y /recomendaciones."""
    pnl_por_activo = {}

    for trade in trades:
        activo = trade["activo"]
        coin_id = COIN_MAP.get(activo, activo.lower())

        if coin_id not in precios_actuales:
            continue

        valor_costo = trade["precio"] * trade["cantidad"]

        if activo not in pnl_por_activo:
            pnl_por_activo[activo] = {
                "cantidad": 0,
                "costo_total": 0,
                "valor_actual": 0,
                "pnl": 0
            }

        if trade["tipo"] == "compra":
            pnl_por_activo[activo]["cantidad"] += trade["cantidad"]
            pnl_por_activo[activo]["costo_total"] += valor_costo
        else:
            pnl_por_activo[activo]["cantidad"] -= trade["cantidad"]
            pnl_por_activo[activo]["costo_total"] -= valor_costo

    for activo, datos in pnl_por_activo.items():
        coin_id = COIN_MAP.get(activo, activo.lower())
        precio_actual = precios_actuales.get(coin_id, {}).get("usd", 0)
        datos["valor_actual"] = round(datos["cantidad"] * precio_actual, 2)
        datos["pnl"] = round(datos["valor_actual"] - datos["costo_total"], 2)
        datos["pnl_porcentaje"] = round(
            (datos["pnl"] / datos["costo_total"] * 100) if datos["costo_total"] > 0 else 0, 2
        )

    return pnl_por_activo

@router.get("/pnl-en-vivo")
async def pnl_en_vivo(current_user: dict = Depends(get_current_user)):
    """Calcula el P&L usando precios actuales del mercado"""
    cache_key = f"pnl_en_vivo_{current_user['id']}"

    cached_data = cache.get(cache_key)
    if cached_data:
        return {**cached_data, "from_cache": True}

    trades = trade_dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)

    if not trades:
        return {"mensaje": "No hay trades registrados"}

    activos = list(set(t["activo"] for t in trades))
    coin_ids = [COIN_MAP.get(activo, activo.lower()) for activo in activos]

    precios_actuales = await obtener_precios_multiples(coin_ids)

    if not precios_actuales:
        return {"error": "No se pudieron obtener precios actuales"}

    pnl_por_activo = _calcular_pnl_por_activo(trades, precios_actuales)
    pnl_total = sum(d["pnl"] for d in pnl_por_activo.values())

    resultado = {
        "pnl_total": round(pnl_total, 2),
        "por_activo": pnl_por_activo,
        "precios_usados": {
            activo: precios_actuales.get(COIN_MAP.get(activo, activo.lower()), {}).get("usd", 0)
            for activo in activos
        },
        "from_cache": False
    }

    cache.set(cache_key, resultado, ttl_seconds=60)

    return resultado


@router.get("/recomendaciones")
async def recomendaciones(current_user: dict = Depends(get_current_user)):
    """Sugiere acciones según el P&L actual de cada activo en cartera"""
    trades = trade_dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)

    if not trades:
        return {"mensaje": "No hay trades registrados"}

    activos = list(set(t["activo"] for t in trades))
    coin_ids = [COIN_MAP.get(activo, activo.lower()) for activo in activos]

    precios_actuales = await obtener_precios_multiples(coin_ids)

    if not precios_actuales:
        return {"error": "No se pudieron obtener precios actuales"}

    pnl_por_activo = _calcular_pnl_por_activo(trades, precios_actuales)

    recomendaciones = []

    for activo, datos in pnl_por_activo.items():
        # Si ya no queda posición en ese activo, no tiene sentido recomendar nada
        if datos["cantidad"] <= 0:
            continue

        pnl_pct = datos["pnl_porcentaje"]

        if pnl_pct <= -10:
            sugerencia = "posible oportunidad de compra"
        elif pnl_pct >= 20:
            sugerencia = "considerar tomar ganancias"
        else:
            sugerencia = "sin recomendación"

        recomendaciones.append({
            "activo": activo,
            "pnl_porcentaje": pnl_pct,
            "cantidad": datos["cantidad"],
            "sugerencia": sugerencia
        })

    return {"recomendaciones": recomendaciones}

@router.get("/reporte-completo")
async def reporte_completo(current_user: dict = Depends(get_current_user)):
    """Genera un reporte completo del portfolio"""
    trades = trade_dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)

    if not trades:
        return {"mensaje": "No hay trades registrados"}

    activos = list(set(t["activo"] for t in trades))
    coin_ids = [COIN_MAP.get(activo, activo.lower()) for activo in activos]
    precios_actuales = await obtener_precios_multiples(coin_ids)

    if not precios_actuales:
        return {"error": "No se pudieron obtener precios actuales"}

    pnl_por_activo = _calcular_pnl_por_activo(trades, precios_actuales)
    pnl_total = sum(d["pnl"] for d in pnl_por_activo.values())

    compras = [t for t in trades if t["tipo"] == "compra"]
    ventas = [t for t in trades if t["tipo"] == "venta"]

    # Mejor y peor trade por P&L a nivel de activo (no por trade individual,
    # porque un trade suelto no tiene ganancia propia, solo el activo la tiene)
    if pnl_por_activo:
        mejor_activo = max(pnl_por_activo.items(), key=lambda x: x[1]["pnl"])
        peor_activo = min(pnl_por_activo.items(), key=lambda x: x[1]["pnl"])
    else:
        mejor_activo = peor_activo = None

    return {
        "estadisticas": {
            "total_trades": len(trades),
            "total_compras": len(compras),
            "total_ventas": len(ventas),
        },
        "pnl_total": round(pnl_total, 2),
        "por_activo": pnl_por_activo,
        "mejor_activo": {"activo": mejor_activo[0], **mejor_activo[1]} if mejor_activo else None,
        "peor_activo": {"activo": peor_activo[0], **peor_activo[1]} if peor_activo else None,
    }

@router.post("/watchlist", response_model=WatchlistResponse, status_code=201)
def agregar_a_watchlist(
    item: WatchlistCreate,
    current_user: dict = Depends(get_current_user)
):
    """Agrega una moneda a la watchlist con alerta de precio"""
    item_id = watchlist_dao.agregar_db(
        usuario_id=current_user["id"],
        coin_id=item.coin_id,
        precio_alerta=item.precio_alerta
    )

    items = watchlist_dao.obtener_por_usuario_db(current_user["id"])
    creado = next(i for i in items if i["id"] == item_id)
    return creado


@router.get("/watchlist", response_model=list[WatchlistResponse])
def ver_watchlist(current_user: dict = Depends(get_current_user)):
    """Muestra la watchlist del usuario autenticado"""
    return watchlist_dao.obtener_por_usuario_db(current_user["id"])