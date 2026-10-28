# app/services/paper_trading.py
"""
Paper trading: operar con dinero SIMULADO (USDT) a precios reales.

Reglas de la versión 1 (deliberadamente simples):
  * Solo órdenes de mercado, al contado y solo largos: no hay ventas en corto ni apalancamiento.
  * Cada ejecución paga slippage en contra y comisión, con los mismos parámetros por defecto que el backtest.
  * Una posición por moneda; el precio medio INCLUYE las comisiones de compra, de modo que el P&L
    realizado de una venta es exactamente (lo cobrado - lo que costó lo vendido).
  * Todo el dinero es Decimal con 8 decimales. Los redondeos nunca favorecen al usuario:
    lo que paga se redondea hacia arriba y lo que cobra, hacia abajo.

Este módulo es lógica pura (sin base de datos ni FastAPI) salvo `precio_de_ejecucion`, que consulta
CoinGecko y es el único punto por donde entra un precio: el cliente nunca lo envía.
"""
import logging
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP
from typing import Dict, Iterable, List, Optional

from app.services.coingecko import obtener_precio

logger = logging.getLogger("trading-api")

OCHO_DECIMALES = Decimal("0.00000001")
VALOR_MAXIMO = Decimal("1000000000")    # tope de una orden: NUMERIC(18,8) admite hasta 10^10
CIEN = Decimal(100)


class PaperError(ValueError):
    """Orden inválida (422)."""


class SaldoInsuficiente(PaperError):
    """No alcanza el saldo para pagar la compra y su comisión (409)."""


class PosicionInsuficiente(PaperError):
    """Se intenta vender más de lo que se tiene (409)."""


class OrdenDuplicada(PaperError):
    """Mismo client_order_id usado con una orden distinta (409)."""


class LimiteDeOrdenes(PaperError):
    """Demasiadas órdenes pendientes abiertas (409)."""


class OrdenNoAbierta(PaperError):
    """La orden ya se ejecutó, se rechazó o se canceló (409)."""


class PrecioNoDisponible(Exception):
    """No se pudo obtener un precio fiable: la orden se rechaza en lugar de ejecutarse a ciegas (503)."""


class MonedaDesconocida(Exception):
    """CoinGecko no conoce esa moneda (404)."""


def _q(valor: Decimal, modo) -> Decimal:
    return valor.quantize(OCHO_DECIMALES, rounding=modo)


def validar_orden(cantidad: Decimal, precio_ref: Decimal) -> None:
    if not isinstance(cantidad, Decimal) or not cantidad.is_finite() or cantidad <= 0:
        raise PaperError("La cantidad debe ser un número mayor que 0")
    if cantidad != cantidad.quantize(OCHO_DECIMALES, rounding=ROUND_DOWN):
        raise PaperError("La cantidad admite como máximo 8 decimales")
    if not isinstance(precio_ref, Decimal) or not precio_ref.is_finite() or precio_ref <= 0:
        raise PaperError("Precio de referencia inválido")
    if cantidad * precio_ref > VALOR_MAXIMO:
        raise PaperError(f"El valor de la orden no puede superar {VALOR_MAXIMO} USDT")


def precio_ejecutado(precio_ref: Decimal, side: str, slippage_pct: Decimal) -> Decimal:
    """El slippage va siempre en contra: se compra más caro y se vende más barato."""
    if side == "BUY":
        precio = _q(precio_ref * (1 + slippage_pct / CIEN), ROUND_UP)
    else:
        precio = _q(precio_ref * (1 - slippage_pct / CIEN), ROUND_DOWN)
    if precio <= 0:
        raise PaperError("Precio demasiado bajo para operar")
    return precio


def se_dispara(tipo: str, side: str, precio_mercado: Decimal, precio_orden: Decimal) -> bool:
    """
    ¿El precio de mercado activa la orden pendiente?
      LIMIT  comprar a ese precio o MENOS / vender a ese precio o MÁS.
      STOP   comprar cuando el precio SUBE hasta ese nivel (entrada por ruptura) /
             vender cuando BAJA hasta ese nivel (stop-loss).
    """
    if tipo == "LIMIT":
        return precio_mercado <= precio_orden if side == "BUY" else precio_mercado >= precio_orden
    if tipo == "STOP":
        return precio_mercado >= precio_orden if side == "BUY" else precio_mercado <= precio_orden
    raise PaperError(f"Tipo de orden desconocido: {tipo}")


def parametros_de_relleno(tipo: str, precio_mercado: Decimal, precio_orden: Decimal, slippage_pct: Decimal):
    """
    (precio de referencia, slippage) con que se ejecuta una orden disparada.
      LIMIT  se rellena al precio límite, sin mejora de precio y sin slippage: nunca es mejor ni peor que lo pedido.
      STOP   se convierte en orden de mercado: precio de mercado del momento y con slippage en contra.
    """
    if tipo == "LIMIT":
        return precio_orden, Decimal(0)
    return precio_mercado, slippage_pct


def validar_stop_al_crear(side: str, precio_mercado: Decimal, precio_stop: Decimal) -> None:
    """Un stop que ya está disparado al crearlo se ejecutaría al instante: se rechaza, como hacen los brókers."""
    if se_dispara("STOP", side, precio_mercado, precio_stop):
        lado = "por encima" if side == "BUY" else "por debajo"
        raise PaperError(
            f"Un STOP de {'compra' if side == 'BUY' else 'venta'} debe fijarse {lado} del precio actual ({precio_mercado})")


def calcular_compra(saldo: Decimal, cantidad: Decimal, precio_ref: Decimal, comision_pct: Decimal,
                    slippage_pct: Decimal, pos_cantidad: Decimal = Decimal(0),
                    pos_precio_medio: Decimal = Decimal(0)) -> dict:
    validar_orden(cantidad, precio_ref)
    precio = precio_ejecutado(precio_ref, "BUY", slippage_pct)
    valor = _q(cantidad * precio, ROUND_UP)
    comision = _q(valor * comision_pct / CIEN, ROUND_UP)
    costo = valor + comision
    if costo > saldo:
        raise SaldoInsuficiente(f"Saldo insuficiente: la compra cuesta {costo} USDT (comisión incluida) y tienes {saldo}")
    nueva_cantidad = pos_cantidad + cantidad
    nuevo_medio = _q((pos_cantidad * pos_precio_medio + costo) / nueva_cantidad, ROUND_UP)
    return {
        "precio": precio, "valor": valor, "comision": comision, "pnl_realizado": None,
        "saldo": saldo - costo, "pos_cantidad": nueva_cantidad, "pos_precio_medio": nuevo_medio,
    }


def calcular_venta(cantidad: Decimal, precio_ref: Decimal, comision_pct: Decimal, slippage_pct: Decimal,
                   pos_cantidad: Decimal, pos_precio_medio: Decimal, saldo: Decimal) -> dict:
    validar_orden(cantidad, precio_ref)
    if cantidad > pos_cantidad:
        raise PosicionInsuficiente(f"No puedes vender {cantidad}: solo tienes {pos_cantidad}")
    precio = precio_ejecutado(precio_ref, "SELL", slippage_pct)
    valor = _q(cantidad * precio, ROUND_DOWN)
    comision = _q(valor * comision_pct / CIEN, ROUND_UP)
    ingreso = valor - comision
    costo_base = _q(cantidad * pos_precio_medio, ROUND_HALF_EVEN)
    return {
        "precio": precio, "valor": valor, "comision": comision, "pnl_realizado": ingreso - costo_base,
        "saldo": saldo + ingreso, "pos_cantidad": pos_cantidad - cantidad, "pos_precio_medio": pos_precio_medio,
    }


def valorar_posiciones(posiciones: Iterable[dict], precios: Dict[str, Optional[Decimal]]) -> dict:
    """
    Valor de mercado y P&L no realizado de cada posición (sin descontar la comisión de salida).
    Si no hay precio para una moneda, sus valores quedan en None y se excluye de los totales,
    avisando con `completo=False` para no presentar un total parcial como si fuera el real.
    """
    filas: List[dict] = []
    valor_total = Decimal(0)
    pnl_total = Decimal(0)
    completo = True
    for p in posiciones:
        precio = precios.get(p["coin_id"])
        fila = {"coin_id": p["coin_id"], "cantidad": p["cantidad"], "precio_medio": p["precio_medio"],
                "precio_actual": precio, "valor_actual": None, "pnl_no_realizado": None, "pnl_pct": None}
        if precio is not None:
            valor = _q(p["cantidad"] * precio, ROUND_DOWN)
            costo = _q(p["cantidad"] * p["precio_medio"], ROUND_HALF_EVEN)
            fila["valor_actual"] = valor
            fila["pnl_no_realizado"] = valor - costo
            fila["pnl_pct"] = (valor - costo) / costo * CIEN if costo > 0 else None
            valor_total += valor
            pnl_total += valor - costo
        else:
            completo = False
        filas.append(fila)
    return {"posiciones": filas, "valor_posiciones": valor_total, "pnl_no_realizado": pnl_total, "completo": completo}


def _a_decimal_positivo(valor) -> Optional[Decimal]:
    try:
        d = Decimal(str(valor))
    except Exception:
        return None
    return d if d.is_finite() and d > 0 else None


async def precio_de_ejecucion(coin_id: str) -> Decimal:
    """Precio actual en USD de CoinGecko (con la caché de 60 s del servicio). Sin precio fiable no hay orden."""
    try:
        datos = await obtener_precio(coin_id, "usd")
    except Exception:
        logger.exception("Paper trading: error consultando el precio de %s", coin_id)
        raise PrecioNoDisponible("No se pudo consultar el precio")
    if datos is None:
        raise PrecioNoDisponible("No se pudo consultar el precio")
    info = datos.get(coin_id) if isinstance(datos, dict) else None
    if not info or "usd" not in info:
        raise MonedaDesconocida(f"Moneda desconocida: {coin_id}")
    precio = _a_decimal_positivo(info["usd"])
    if precio is None:
        raise PrecioNoDisponible("CoinGecko devolvió un precio inválido")
    return precio


async def precios_de_mercado(coin_ids: List[str]) -> Dict[str, Optional[Decimal]]:
    """Precios actuales para valorar posiciones. Si falla, devuelve {} (se informa como valoración incompleta)."""
    if not coin_ids:
        return {}
    from app.services.coingecko import obtener_precios_multiples
    try:
        datos = await obtener_precios_multiples(coin_ids, "usd")
    except Exception:
        logger.exception("Paper trading: error consultando precios para valorar posiciones")
        return {}
    if not isinstance(datos, dict):
        return {}
    return {c: _a_decimal_positivo((datos.get(c) or {}).get("usd")) for c in coin_ids}
