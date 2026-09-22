# app/routers/analisis.py
from fastapi import APIRouter, Depends
from utils.authorization import get_current_user
from app.dao.TradeDAO import TradeDAO
from app.services.coingecko import obtener_precios_multiples

router = APIRouter(prefix="/analisis", tags=["Análisis"])

dao = TradeDAO()

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
    trades = dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)

    if not trades:
        return {"mensaje": "No hay trades registrados"}

    activos = list(set(t["activo"] for t in trades))
    coin_ids = [COIN_MAP.get(activo, activo.lower()) for activo in activos]

    precios_actuales = await obtener_precios_multiples(coin_ids)

    if not precios_actuales:
        return {"error": "No se pudieron obtener precios actuales"}

    pnl_por_activo = _calcular_pnl_por_activo(trades, precios_actuales)
    pnl_total = sum(d["pnl"] for d in pnl_por_activo.values())

    return {
        "pnl_total": round(pnl_total, 2),
        "por_activo": pnl_por_activo,
        "precios_usados": {
            activo: precios_actuales.get(COIN_MAP.get(activo, activo.lower()), {}).get("usd", 0)
            for activo in activos
        }
    }


@router.get("/recomendaciones")
async def recomendaciones(current_user: dict = Depends(get_current_user)):
    """Sugiere acciones según el P&L actual de cada activo en cartera"""
    trades = dao.obtener_trades_db(usuario_id=current_user["id"], limit=1000)

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