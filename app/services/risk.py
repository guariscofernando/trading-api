# app/services/risk.py
"""
Gestión de riesgo: lógica pura (sin base de datos ni red), fácil de probar.

Mercado spot, solo posiciones largas y sin apalancamiento.
Convenciones: los porcentajes se expresan en "puntos" (1.0 = 1 %).
"""
import math
from dataclasses import dataclass, asdict
from typing import Optional

EPS = 1e-9
_DECIMALES_CANTIDAD = 8  # precisión de cantidad típica de exchanges cripto


@dataclass(frozen=True)
class LimitesRiesgo:
    """Límites de riesgo. Los valores por defecto son prácticas habituales, no una recomendación."""
    riesgo_max_por_trade_pct: float = 1.0    # pérdida máxima si salta el stop, sobre el capital
    posicion_max_pct: float = 25.0           # valor máximo de una posición sobre el capital
    perdida_diaria_max_pct: float = 3.0      # al alcanzarla no se abren más operaciones ese día
    drawdown_max_pct: float = 20.0           # al alcanzarlo se detiene la operativa
    posiciones_abiertas_max: int = 5

    def a_dict(self) -> dict:
        return asdict(self)


def _exigir_finitos(**valores) -> None:
    """NaN e infinito pasan las comparaciones (NaN <= 0 es False) y envenenan los cálculos."""
    for nombre, valor in valores.items():
        if valor is not None and not math.isfinite(valor):
            raise ValueError(f"{nombre} debe ser un número finito")


def _truncar_cantidad(cantidad: float) -> float:
    """Trunca (no redondea) para no superar nunca el límite que originó la cantidad."""
    factor = 10 ** _DECIMALES_CANTIDAD
    return math.floor(cantidad * factor + EPS) / factor


def calcular_tamano_posicion(
    capital: float,
    entrada: float,
    stop: float,
    riesgo_pct: float,
    posicion_max_pct: float = 100.0,
    saldo_disponible: Optional[float] = None,
) -> dict:
    """
    Tamaño de posición por riesgo fijo ("fixed fractional"):

        cantidad = (capital * riesgo_pct / 100) / (entrada - stop)

    es decir, si salta el stop se pierde como máximo `riesgo_pct` del capital.
    El resultado se limita además por el tamaño máximo de posición y por el saldo
    disponible; `limitado_por` indica cuál de los tres fue el que mandó.
    """
    _exigir_finitos(capital=capital, entrada=entrada, stop=stop, riesgo_pct=riesgo_pct,
                    posicion_max_pct=posicion_max_pct, saldo_disponible=saldo_disponible)
    if capital <= 0:
        raise ValueError("El capital debe ser mayor que 0")
    if entrada <= 0 or stop <= 0:
        raise ValueError("Entrada y stop deben ser mayores que 0")
    if stop >= entrada:
        raise ValueError("El stop debe estar por debajo de la entrada (solo posiciones largas)")
    if not 0 < riesgo_pct <= 100:
        raise ValueError("riesgo_pct debe estar entre 0 (excluido) y 100")
    if not 0 < posicion_max_pct <= 100:
        raise ValueError("posicion_max_pct debe estar entre 0 (excluido) y 100 (sin apalancamiento)")
    if saldo_disponible is not None and saldo_disponible < 0:
        raise ValueError("saldo_disponible no puede ser negativo")

    riesgo_por_unidad = entrada - stop
    candidatos = [
        ("riesgo", capital * riesgo_pct / 100 / riesgo_por_unidad),
        ("posicion_max", capital * posicion_max_pct / 100 / entrada),
    ]
    if saldo_disponible is not None:
        candidatos.append(("saldo", saldo_disponible / entrada))

    limitado_por, cantidad = min(candidatos, key=lambda c: c[1])  # empate: gana el primero
    cantidad = _truncar_cantidad(cantidad)

    valor = cantidad * entrada
    riesgo_monetario = cantidad * riesgo_por_unidad
    return {
        "cantidad": cantidad,
        "valor_posicion": round(valor, 2),
        "posicion_pct": round(valor / capital * 100, 4),
        "riesgo_monetario": round(riesgo_monetario, 2),
        "riesgo_pct_real": round(riesgo_monetario / capital * 100, 4),
        "distancia_stop_pct": round(riesgo_por_unidad / entrada * 100, 4),
        "limitado_por": limitado_por,
    }


def niveles_salida(
    entrada: float,
    stop_loss_pct: float,
    take_profit_pct: Optional[float] = None,
    ratio_riesgo_beneficio: Optional[float] = None,
) -> dict:
    """Precios de stop-loss y take-profit para una entrada larga."""
    _exigir_finitos(entrada=entrada, stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct, ratio_riesgo_beneficio=ratio_riesgo_beneficio)
    if entrada <= 0:
        raise ValueError("La entrada debe ser mayor que 0")
    if not 0 < stop_loss_pct < 100:
        raise ValueError("stop_loss_pct debe estar entre 0 y 100 (ambos excluidos)")
    if take_profit_pct is not None and ratio_riesgo_beneficio is not None:
        raise ValueError("Indica take_profit_pct o ratio_riesgo_beneficio, no ambos")
    if take_profit_pct is not None and take_profit_pct <= 0:
        raise ValueError("take_profit_pct debe ser mayor que 0")
    if ratio_riesgo_beneficio is not None and ratio_riesgo_beneficio <= 0:
        raise ValueError("ratio_riesgo_beneficio debe ser mayor que 0")

    stop = entrada * (1 - stop_loss_pct / 100)
    riesgo = entrada - stop
    if take_profit_pct is not None:
        take_profit = entrada * (1 + take_profit_pct / 100)
    elif ratio_riesgo_beneficio is not None:
        take_profit = entrada + ratio_riesgo_beneficio * riesgo
    else:
        take_profit = None

    return {
        "entrada": entrada,
        "stop_loss": round(stop, 8),
        "take_profit": round(take_profit, 8) if take_profit is not None else None,
        "ratio_riesgo_beneficio": (
            round((take_profit - entrada) / riesgo, 4) if take_profit is not None else None
        ),
    }


def evaluar_trade(
    capital: float,
    entrada: float,
    stop: float,
    cantidad: float,
    limites: LimitesRiesgo = LimitesRiesgo(),
    saldo_disponible: Optional[float] = None,
    perdida_diaria_pct: float = 0.0,
    drawdown_actual_pct: float = 0.0,
    posiciones_abiertas: int = 0,
) -> dict:
    """Comprueba una operación propuesta contra los límites. No ejecuta nada."""
    _exigir_finitos(capital=capital, entrada=entrada, stop=stop, cantidad=cantidad,
                    saldo_disponible=saldo_disponible, perdida_diaria_pct=perdida_diaria_pct,
                    drawdown_actual_pct=drawdown_actual_pct)
    if capital <= 0:
        raise ValueError("El capital debe ser mayor que 0")
    if entrada <= 0 or stop <= 0 or cantidad <= 0:
        raise ValueError("Entrada, stop y cantidad deben ser mayores que 0")
    if stop >= entrada:
        raise ValueError("El stop debe estar por debajo de la entrada (solo posiciones largas)")

    valor = cantidad * entrada
    riesgo_monetario = cantidad * (entrada - stop)
    riesgo_pct = riesgo_monetario / capital * 100
    posicion_pct = valor / capital * 100

    violaciones = []

    def violar(codigo: str, mensaje: str):
        violaciones.append({"codigo": codigo, "mensaje": mensaje})

    if riesgo_pct > limites.riesgo_max_por_trade_pct + EPS:
        violar("riesgo_por_trade",
               f"El riesgo es {riesgo_pct:.2f}% del capital (máximo {limites.riesgo_max_por_trade_pct}%)")
    if posicion_pct > limites.posicion_max_pct + EPS:
        violar("tamano_posicion",
               f"La posición es {posicion_pct:.2f}% del capital (máximo {limites.posicion_max_pct}%)")
    if saldo_disponible is not None and valor > saldo_disponible + EPS:
        violar("saldo_insuficiente",
               f"La posición vale {valor:.2f} y el saldo disponible es {saldo_disponible:.2f}")
    if perdida_diaria_pct >= limites.perdida_diaria_max_pct - EPS:
        violar("perdida_diaria",
               f"Pérdida del día {perdida_diaria_pct:.2f}% ha alcanzado el límite de {limites.perdida_diaria_max_pct}%")
    if drawdown_actual_pct >= limites.drawdown_max_pct - EPS:
        violar("drawdown_maximo",
               f"Drawdown {drawdown_actual_pct:.2f}% ha alcanzado el límite de {limites.drawdown_max_pct}%")
    if posiciones_abiertas >= limites.posiciones_abiertas_max:
        violar("max_posiciones",
               f"Ya hay {posiciones_abiertas} posiciones abiertas (máximo {limites.posiciones_abiertas_max})")

    advertencias = []
    if riesgo_pct > 2 and not any(v["codigo"] == "riesgo_por_trade" for v in violaciones):
        advertencias.append(f"Arriesgar más de 2% del capital por operación ({riesgo_pct:.2f}%) es agresivo")

    return {
        "permitido": not violaciones,
        "violaciones": violaciones,
        "advertencias": advertencias,
        "metricas": {
            "valor_posicion": round(valor, 2),
            "posicion_pct": round(posicion_pct, 4),
            "riesgo_monetario": round(riesgo_monetario, 2),
            "riesgo_pct": round(riesgo_pct, 4),
        },
        "limites_aplicados": limites.a_dict(),
    }


def analizar_portafolio(
    trades: list,
    capital: Optional[float] = None,
    limites: LimitesRiesgo = LimitesRiesgo(),
) -> dict:
    """
    Riesgo del portafolio a partir de los trades registrados (compra/venta), con
    costo promedio ponderado. No usa precios de mercado: mide lo ya realizado y la
    exposición medida a costo.

    `capital` (opcional) es el patrimonio total; con él la concentración y los
    drawdowns se expresan sobre el capital, y sin él la concentración es relativa a
    lo invertido.
    """
    _exigir_finitos(capital=capital)
    if capital is not None and capital <= 0:
        raise ValueError("El capital debe ser mayor que 0")
    ordenados = sorted(trades, key=lambda t: (str(t.get("fecha", "")), t.get("id", 0)))

    posiciones = {}          # activo -> {"cantidad", "costo_promedio", "realizado"}
    ventas_cerradas = []     # pnl de cada venta
    pnl_diario = {}          # "YYYY-MM-DD" -> pnl realizado
    advertencias = []

    for t in ordenados:
        activo = t["activo"]
        pos = posiciones.setdefault(activo, {"cantidad": 0.0, "costo_promedio": 0.0, "realizado": 0.0})
        precio, cantidad = float(t["precio"]), float(t["cantidad"])

        if t["tipo"] == "compra":
            nuevo_costo = pos["cantidad"] * pos["costo_promedio"] + cantidad * precio
            pos["cantidad"] += cantidad
            pos["costo_promedio"] = nuevo_costo / pos["cantidad"]
        else:  # venta
            vendible = min(cantidad, pos["cantidad"])
            if cantidad > pos["cantidad"] + EPS:
                advertencias.append(
                    f"{activo}: venta de {cantidad:g} mayor que la posición registrada "
                    f"({pos['cantidad']:g}); solo se computa lo cubierto por compras previas"
                )
            if vendible <= EPS:
                continue
            pnl = (precio - pos["costo_promedio"]) * vendible
            pos["cantidad"] -= vendible
            pos["realizado"] += pnl
            if pos["cantidad"] <= EPS:
                pos["cantidad"], pos["costo_promedio"] = 0.0, 0.0
            ventas_cerradas.append(pnl)
            dia = str(t.get("fecha", ""))[:10]
            pnl_diario[dia] = pnl_diario.get(dia, 0.0) + pnl

    # --- exposición actual (a costo)
    abiertas = {a: p for a, p in posiciones.items() if p["cantidad"] > EPS}
    costo_total = sum(p["cantidad"] * p["costo_promedio"] for p in abiertas.values())
    base_pct = capital if capital else costo_total

    por_activo = {}
    alertas = []
    for activo, p in sorted(abiertas.items()):
        costo_base = p["cantidad"] * p["costo_promedio"]
        peso = costo_base / base_pct * 100 if base_pct > 0 else 0.0
        por_activo[activo] = {
            "cantidad": round(p["cantidad"], 8),
            "costo_promedio": round(p["costo_promedio"], 8),
            "costo_base": round(costo_base, 2),
            "peso_pct": round(peso, 2),
            "pnl_realizado": round(p["realizado"], 2),
        }
        if peso > limites.posicion_max_pct + EPS and (capital or len(abiertas) > 1):
            referencia = "del capital" if capital else "de lo invertido"
            alertas.append({
                "codigo": "concentracion",
                "mensaje": f"{activo} pesa {peso:.2f}% {referencia} (máximo {limites.posicion_max_pct}%)",
            })

    if len(abiertas) > limites.posiciones_abiertas_max:
        alertas.append({
            "codigo": "max_posiciones",
            "mensaje": f"Hay {len(abiertas)} posiciones abiertas (máximo {limites.posiciones_abiertas_max})",
        })

    # --- resultados realizados
    ganancias = [p for p in ventas_cerradas if p > 0]
    perdidas = [p for p in ventas_cerradas if p < 0]
    total_realizado = sum(ventas_cerradas)
    suma_ganancias, suma_perdidas = sum(ganancias), -sum(perdidas)

    # drawdown de la curva de P&L realizado acumulado (parte de 0)
    acumulado = pico = max_dd = 0.0
    for pnl in ventas_cerradas:
        acumulado += pnl
        pico = max(pico, acumulado)
        max_dd = max(max_dd, pico - acumulado)

    peor_dia = min(pnl_diario.items(), key=lambda kv: kv[1]) if pnl_diario else None
    if capital:
        if peor_dia and peor_dia[1] < 0 and -peor_dia[1] / capital * 100 >= limites.perdida_diaria_max_pct - EPS:
            alertas.append({
                "codigo": "perdida_diaria",
                "mensaje": f"El {peor_dia[0]} se perdió {-peor_dia[1] / capital * 100:.2f}% del capital "
                           f"(límite {limites.perdida_diaria_max_pct}%)",
            })
        if max_dd / capital * 100 >= limites.drawdown_max_pct - EPS:
            alertas.append({
                "codigo": "drawdown_maximo",
                "mensaje": f"El drawdown realizado llegó a {max_dd / capital * 100:.2f}% del capital "
                           f"(límite {limites.drawdown_max_pct}%)",
            })

    n = len(ventas_cerradas)
    return {
        "capital_referencia": capital,
        "exposicion": {
            "costo_total_invertido": round(costo_total, 2),
            "exposicion_pct_capital": round(costo_total / capital * 100, 2) if capital else None,
            "por_activo": por_activo,
        },
        "realizado": {
            "ventas_cerradas": n,
            "ganadoras": len(ganancias),
            "perdedoras": len(perdidas),
            "win_rate_pct": round(len(ganancias) / n * 100, 2) if n else None,
            "pnl_total": round(total_realizado, 2),
            "expectativa_por_venta": round(total_realizado / n, 2) if n else None,
            "profit_factor": round(suma_ganancias / suma_perdidas, 4) if suma_perdidas > 0 else None,
            "max_drawdown_realizado": round(max_dd, 2),
            "max_drawdown_realizado_pct_capital": round(max_dd / capital * 100, 2) if capital else None,
            "peor_dia": {"fecha": peor_dia[0], "pnl": round(peor_dia[1], 2)} if peor_dia else None,
        },
        "alertas": alertas,
        "advertencias": advertencias,
        "limites_aplicados": limites.a_dict(),
    }
