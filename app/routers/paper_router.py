# app/routers/paper_router.py
"""Paper trading: operar con dinero simulado a precios reales. Cada usuario solo ve y mueve lo suyo."""
from decimal import Decimal
from functools import partial
from typing import Optional

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.config import config
from app.dao.PaperDAO import PaperDAO
from app.dto.PaperDTO import OrdenPaper
from app.services import paper_trading as pt
from app.services.ratelimit import golpear_sin_bloquear
from utils.authorization import get_current_user

router = APIRouter(prefix="/paper", tags=["Paper trading"])
dao = PaperDAO()


def _n(valor: Optional[Decimal]) -> Optional[float]:
    """Decimal (8 decimales) -> número JSON."""
    return None if valor is None else float(valor)


def _trade_json(t: dict) -> dict:
    return {
        "id": t["id"], "coin_id": t["coin_id"], "side": t["side"], "cantidad": _n(t["cantidad"]),
        "precio": _n(t["precio"]), "valor": _n(t["valor"]), "comision": _n(t["comision"]),
        "pnl_realizado": _n(t["pnl_realizado"]), "client_order_id": t["client_order_id"],
        "ejecutado_en": t["ejecutado_en"].strftime("%Y-%m-%d %H:%M:%S") if t["ejecutado_en"] else None,
    }


def _posicion_json(f: dict) -> dict:
    return {
        "coin_id": f["coin_id"], "cantidad": _n(f["cantidad"]), "precio_medio": _n(f["precio_medio"]),
        "precio_actual": _n(f["precio_actual"]), "valor_actual": _n(f["valor_actual"]),
        "pnl_no_realizado": _n(f["pnl_no_realizado"]), "pnl_pct": _n(f["pnl_pct"]),
    }


async def _limitar(clave: str, limite: int, ventana: int) -> None:
    resultado = await golpear_sin_bloquear(clave, limite, ventana)
    if resultado is not None and not resultado.permitido:
        raise HTTPException(
            status_code=429, detail=f"Demasiadas operaciones. Intenta de nuevo en {resultado.reinicia_en} segundos.",
            headers={"Retry-After": str(resultado.reinicia_en)})


async def _en_hilo(funcion, *args, **kwargs):
    """Los DAOs son síncronos: se ejecutan en un hilo para no bloquear el bucle de eventos."""
    return await anyio.to_thread.run_sync(partial(funcion, *args, **kwargs))


@router.post("/orden")
async def crear_orden(orden: OrdenPaper, response: Response, current_user: dict = Depends(get_current_user)):
    """
    Orden de mercado simulada (compra o venta al contado). El precio lo pone el servidor
    (CoinGecko, hasta 60 s de antigüedad por la caché), nunca el cliente, y se aplican slippage y comisión.
    Con `client_order_id` un reintento devuelve la misma orden (200) en vez de ejecutarla otra vez.
    """
    usuario_id = current_user["id"]
    await _limitar(f"paper:orden:{usuario_id}", config.PAPER_ORDERS_PER_MINUTE, 60)
    try:
        precio_ref = await pt.precio_de_ejecucion(orden.coin_id)
        trade = await _en_hilo(
            dao.ejecutar_orden, usuario_id, orden.coin_id, orden.side, orden.cantidad, precio_ref,
            config.PAPER_INITIAL_BALANCE, config.PAPER_COMMISSION_PCT, config.PAPER_SLIPPAGE_PCT,
            orden.client_order_id)
    except pt.MonedaDesconocida as e:
        raise HTTPException(status_code=404, detail=str(e))
    except pt.PrecioNoDisponible as e:
        raise HTTPException(status_code=503, detail=f"{e}. Reintenta en unos segundos.")
    except (pt.SaldoInsuficiente, pt.PosicionInsuficiente, pt.OrdenDuplicada) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except pt.PaperError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if trade["repetida"]:
        response.status_code = 200
    else:
        response.status_code = 201
    return {**_trade_json(trade), "saldo_usdt": _n(trade["saldo"]), "repetida": trade["repetida"]}


async def _valoracion(usuario_id: int) -> dict:
    posiciones = await _en_hilo(dao.obtener_posiciones, usuario_id)
    precios = await pt.precios_de_mercado([p["coin_id"] for p in posiciones])
    return pt.valorar_posiciones(posiciones, precios)


@router.get("/billetera")
async def billetera(current_user: dict = Depends(get_current_user)):
    """Saldo, posiciones valoradas a precio de mercado, equity y P&L."""
    uid = current_user["id"]
    cuenta = await _en_hilo(dao.obtener_billetera, uid, config.PAPER_INITIAL_BALANCE)
    pnl_realizado = await _en_hilo(dao.pnl_realizado_total, uid)
    val = await _valoracion(uid)
    equity = cuenta["balance_usdt"] + val["valor_posiciones"]
    return {
        "saldo_usdt": _n(cuenta["balance_usdt"]),
        "saldo_inicial": _n(cuenta["saldo_inicial"]),
        "valor_posiciones": _n(val["valor_posiciones"]),
        "equity": _n(equity),
        "pnl_total": _n(equity - cuenta["saldo_inicial"]),
        "pnl_realizado": _n(pnl_realizado),
        "pnl_no_realizado": _n(val["pnl_no_realizado"]),
        # False: faltó el precio de alguna moneda y equity/pnl_no_realizado NO incluyen esa posición
        "valoracion_completa": val["completo"],
        "posiciones": [_posicion_json(f) for f in val["posiciones"]],
    }


@router.get("/posiciones")
async def posiciones(current_user: dict = Depends(get_current_user)):
    val = await _valoracion(current_user["id"])
    return {"valoracion_completa": val["completo"], "posiciones": [_posicion_json(f) for f in val["posiciones"]]}


@router.get("/historial")
async def historial(skip: int = Query(0, ge=0, le=1_000_000), limit: int = Query(50, ge=1, le=100),
                    current_user: dict = Depends(get_current_user)):
    """Órdenes ejecutadas, de la más reciente a la más antigua."""
    trades = await _en_hilo(dao.obtener_historial, current_user["id"], skip, limit)
    return [_trade_json(t) for t in trades]


@router.post("/reiniciar")
async def reiniciar(current_user: dict = Depends(get_current_user)):
    """Borra posiciones e historial y devuelve el saldo al inicial. Limitado por hora."""
    uid = current_user["id"]
    await _limitar(f"paper:reinicio:{uid}", config.PAPER_RESETS_PER_HOUR, 3600)
    cuenta = await _en_hilo(dao.reiniciar, uid, config.PAPER_INITIAL_BALANCE)
    return {"saldo_usdt": _n(cuenta["balance_usdt"]), "mensaje": "Cuenta de paper trading reiniciada"}
