# app/services/backtest.py
"""
Backtesting sobre series de precios de cierre. Lógica pura: sin base de datos ni red.

Reglas del simulador (pensadas para no producir resultados mejores que la realidad):
  * Sin mirar el futuro: la señal calculada con datos hasta la barra i se ejecuta
    al precio de la barra i+1. Una señal en la última barra no se ejecuta.
  * Solo posiciones largas, una a la vez, sin apalancamiento (spot).
  * Comisión por lado y slippage en contra en cada ejecución.
  * El tamaño de cada operación sale de `risk.calcular_tamano_posicion`
    (riesgo fijo por operación, tope de posición y saldo disponible).
  * Stop-loss y take-profit se evalúan al CIERRE de cada barra (solo hay cierres):
    si el precio ya saltó el nivel, se sale al cierre, que puede ser peor que el stop.
  * Tras salir por stop/take-profit no se vuelve a entrar hasta que la señal se
    apague y se vuelva a encender (evita reentrar en bucle dentro de la misma tendencia).
  * Si el drawdown de la cuenta alcanza el límite, se cierra la posición y se
    detiene la operativa hasta el final.
  * Una posición abierta al terminar los datos se cierra a precio de la última barra.

Un buen resultado en el pasado NO garantiza resultados futuros: todo backtest sobre
los mismos datos con los que se eligieron los parámetros está sobreajustado (in-sample).
"""
import math
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence

from app.services.risk import calcular_tamano_posicion

MAX_PUNTOS = 5000
MIN_PUNTOS = 30
MAX_PUNTOS_CURVA = 200       # la curva de equity devuelta se reduce a este tamaño
POCAS_OPERACIONES = 30       # por debajo, las estadísticas no son fiables


# --------------------------------------------------------------------------- indicadores

def sma(valores: Sequence[float], ventana: int) -> List[Optional[float]]:
    """Media móvil simple. Los primeros `ventana - 1` valores son None."""
    n = len(valores)
    salida: List[Optional[float]] = [None] * n
    if ventana < 1 or n < ventana:
        return salida
    suma = sum(valores[:ventana])
    salida[ventana - 1] = suma / ventana
    for i in range(ventana, n):
        suma += valores[i] - valores[i - ventana]
        salida[i] = suma / ventana
    return salida


def _rsi_valor(media_ganancia: float, media_perdida: float) -> float:
    if media_perdida == 0:
        return 100.0 if media_ganancia > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + media_ganancia / media_perdida)


def rsi(cierres: Sequence[float], periodo: int = 14) -> List[Optional[float]]:
    """RSI con suavizado de Wilder. Los primeros `periodo` valores son None."""
    n = len(cierres)
    salida: List[Optional[float]] = [None] * n
    if periodo < 2 or n <= periodo:
        return salida

    ganancias = perdidas = 0.0
    for i in range(1, periodo + 1):
        cambio = cierres[i] - cierres[i - 1]
        ganancias += max(cambio, 0.0)
        perdidas += max(-cambio, 0.0)
    media_g, media_p = ganancias / periodo, perdidas / periodo
    salida[periodo] = _rsi_valor(media_g, media_p)

    for i in range(periodo + 1, n):
        cambio = cierres[i] - cierres[i - 1]
        media_g = (media_g * (periodo - 1) + max(cambio, 0.0)) / periodo
        media_p = (media_p * (periodo - 1) + max(-cambio, 0.0)) / periodo
        salida[i] = _rsi_valor(media_g, media_p)
    return salida


# --------------------------------------------------------------------------- estrategias
# Una estrategia devuelve, para cada barra, si QUIERE estar en el mercado (True/False)
# usando solo datos hasta esa barra. El motor decide cuándo y a qué precio se ejecuta.

def _objetivo_cruce_medias(cierres: Sequence[float], rapida: int, lenta: int) -> List[bool]:
    ma_rapida, ma_lenta = sma(cierres, rapida), sma(cierres, lenta)
    return [
        f is not None and l is not None and f > l
        for f, l in zip(ma_rapida, ma_lenta)
    ]


def _objetivo_rsi(cierres: Sequence[float], periodo: int, sobreventa: float, sobrecompra: float) -> List[bool]:
    """Entra con RSI <= sobreventa y sale con RSI >= sobrecompra; en medio mantiene lo anterior."""
    objetivo, dentro = [], False
    for valor in rsi(cierres, periodo):
        if valor is not None:
            if valor <= sobreventa:
                dentro = True
            elif valor >= sobrecompra:
                dentro = False
        objetivo.append(dentro)
    return objetivo


def _validar_cruce(p: Dict[str, float], n: int) -> Dict[str, float]:
    rapida, lenta = int(p["rapida"]), int(p["lenta"])
    if rapida < 1 or lenta < 2 or rapida >= lenta:
        raise ValueError("cruce_medias: se requiere 1 <= rapida < lenta")
    if lenta > 400:
        raise ValueError("cruce_medias: lenta no puede superar 400")
    if n < lenta + 2:
        raise ValueError(f"cruce_medias: con lenta={lenta} se necesitan al menos {lenta + 2} precios")
    return {"rapida": rapida, "lenta": lenta}


def _validar_rsi(p: Dict[str, float], n: int) -> Dict[str, float]:
    periodo = int(p["periodo"])
    sobreventa, sobrecompra = float(p["sobreventa"]), float(p["sobrecompra"])
    if periodo < 2 or periodo > 200:
        raise ValueError("rsi: periodo debe estar entre 2 y 200")
    if not 0 < sobreventa < sobrecompra < 100:
        raise ValueError("rsi: se requiere 0 < sobreventa < sobrecompra < 100")
    if n < periodo + 2:
        raise ValueError(f"rsi: con periodo={periodo} se necesitan al menos {periodo + 2} precios")
    return {"periodo": periodo, "sobreventa": sobreventa, "sobrecompra": sobrecompra}


ESTRATEGIAS: Dict[str, dict] = {
    "cruce_medias": {
        "descripcion": "Largo mientras la media móvil rápida esté por encima de la lenta (seguimiento de tendencia).",
        "parametros": {"rapida": 10, "lenta": 30},
        "validar": _validar_cruce,
        "objetivo": lambda c, p: _objetivo_cruce_medias(c, p["rapida"], p["lenta"]),
    },
    "rsi": {
        "descripcion": "Compra en sobreventa y vende en sobrecompra (reversión a la media).",
        "parametros": {"periodo": 14, "sobreventa": 30, "sobrecompra": 70},
        "validar": _validar_rsi,
        "objetivo": lambda c, p: _objetivo_rsi(c, p["periodo"], p["sobreventa"], p["sobrecompra"]),
    },
}


def listar_estrategias() -> dict:
    return {
        nombre: {"descripcion": e["descripcion"], "parametros_por_defecto": dict(e["parametros"])}
        for nombre, e in ESTRATEGIAS.items()
    }


# --------------------------------------------------------------------------- parámetros

@dataclass(frozen=True)
class ParametrosBacktest:
    capital_inicial: float = 10_000.0
    riesgo_por_trade_pct: float = 1.0
    stop_loss_pct: float = 5.0
    take_profit_pct: Optional[float] = None
    posicion_max_pct: float = 25.0
    drawdown_max_pct: float = 20.0
    comision_pct: float = 0.1       # por lado, sobre el valor de la operación
    slippage_pct: float = 0.05      # en contra, por lado
    periodos_por_ano: float = 365.0  # para anualizar el Sharpe (cripto opera todos los días)

    def validar(self) -> None:
        for nombre, valor in asdict(self).items():
            if valor is not None and not math.isfinite(valor):
                raise ValueError(f"{nombre} debe ser un número finito")
        if self.capital_inicial <= 0:
            raise ValueError("capital_inicial debe ser mayor que 0")
        if not 0 < self.riesgo_por_trade_pct <= 100:
            raise ValueError("riesgo_por_trade_pct debe estar entre 0 (excluido) y 100")
        if not 0 < self.stop_loss_pct < 100:
            raise ValueError("stop_loss_pct debe estar entre 0 y 100 (ambos excluidos); el tamaño de la posición depende del stop")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct debe ser mayor que 0")
        if not 0 < self.posicion_max_pct <= 100:
            raise ValueError("posicion_max_pct debe estar entre 0 (excluido) y 100 (sin apalancamiento)")
        if not 0 < self.drawdown_max_pct <= 100:
            raise ValueError("drawdown_max_pct debe estar entre 0 (excluido) y 100")
        if not 0 <= self.comision_pct < 10:
            raise ValueError("comision_pct debe estar entre 0 y 10")
        if not 0 <= self.slippage_pct < 10:
            raise ValueError("slippage_pct debe estar entre 0 y 10")
        if self.periodos_por_ano <= 0:
            raise ValueError("periodos_por_ano debe ser mayor que 0")


def _validar_precios(cierres: Sequence[float]) -> None:
    if len(cierres) > MAX_PUNTOS:
        raise ValueError(f"Máximo {MAX_PUNTOS} precios por backtest (recibidos {len(cierres)})")
    if len(cierres) < 2:
        raise ValueError("Se necesitan al menos 2 precios")
    for x in cierres:
        if not math.isfinite(x) or x <= 0:
            raise ValueError("Todos los precios deben ser números finitos mayores que 0")


# --------------------------------------------------------------------------- simulador

def simular(cierres: Sequence[float], objetivo: Sequence[bool], params: ParametrosBacktest) -> dict:
    """
    Ejecuta la simulación con una serie `objetivo` ya calculada (True = quiero estar dentro).
    Devuelve operaciones y curva de equity. Es la pieza que se prueba con valores exactos.
    """
    params.validar()
    _validar_precios(cierres)
    if len(objetivo) != len(cierres):
        raise ValueError("objetivo y cierres deben tener la misma longitud")

    n = len(cierres)
    comision = params.comision_pct / 100
    slippage = params.slippage_pct / 100

    efectivo = params.capital_inicial
    pos: Optional[dict] = None
    operaciones: List[dict] = []
    curva: List[float] = []
    omitidas = 0
    pico = params.capital_inicial
    detenido = False
    esperar_reinicio = False
    pendiente: Optional[str] = None
    barras_en_mercado = 0

    def abrir(idx: int, precio: float) -> None:
        nonlocal efectivo, pos, omitidas
        entrada = precio * (1 + slippage)
        stop = entrada * (1 - params.stop_loss_pct / 100)
        tam = calcular_tamano_posicion(
            capital=efectivo,
            entrada=entrada,
            stop=stop,
            riesgo_pct=params.riesgo_por_trade_pct,
            posicion_max_pct=params.posicion_max_pct,
            saldo_disponible=efectivo / (1 + comision),   # la comisión también sale del efectivo
        )
        cantidad = tam["cantidad"]
        if cantidad <= 0:
            omitidas += 1
            return
        costo = cantidad * entrada * (1 + comision)
        efectivo -= costo
        pos = {
            "idx": idx, "entrada": entrada, "cantidad": cantidad, "costo": costo,
            "stop": stop,
            "take_profit": entrada * (1 + params.take_profit_pct / 100) if params.take_profit_pct else None,
        }

    def cerrar(idx: int, precio: float, motivo: str) -> None:
        nonlocal efectivo, pos
        salida = precio * (1 - slippage)
        ingreso = pos["cantidad"] * salida * (1 - comision)
        efectivo += ingreso
        pnl = ingreso - pos["costo"]
        operaciones.append({
            "entrada_idx": pos["idx"], "salida_idx": idx,
            "precio_entrada": round(pos["entrada"], 8), "precio_salida": round(salida, 8),
            "cantidad": pos["cantidad"],
            "pnl": round(pnl, 2),
            "retorno_pct": round(pnl / pos["costo"] * 100, 4),
            "barras": idx - pos["idx"],
            "motivo": motivo,
            "_pnl": pnl,
        })
        pos = None

    for i, precio in enumerate(cierres):
        # 1) orden decidida con datos hasta la barra anterior, ejecutada al precio de ésta
        if pendiente == "comprar" and pos is None and not detenido:
            abrir(i, precio)
        elif pendiente == "vender" and pos is not None:
            cerrar(i, precio, "senal")
        pendiente = None

        # 2) stop-loss / take-profit al cierre
        if pos is not None:
            if precio <= pos["stop"]:
                cerrar(i, precio, "stop_loss")
                esperar_reinicio = True
            elif pos["take_profit"] is not None and precio >= pos["take_profit"]:
                cerrar(i, precio, "take_profit")
                esperar_reinicio = True

        # 3) equity y freno por drawdown
        equity = efectivo + (pos["cantidad"] * precio if pos else 0.0)
        pico = max(pico, equity)
        if not detenido and (pico - equity) / pico * 100 >= params.drawdown_max_pct:
            detenido = True
            if pos is not None:
                cerrar(i, precio, "drawdown_maximo")
                equity = efectivo
        if pos is not None:
            barras_en_mercado += 1
        curva.append(equity)

        # 4) señal para la barra siguiente (la última barra no puede ejecutar nada)
        if not objetivo[i]:
            esperar_reinicio = False
        if not detenido and i < n - 1:
            if objetivo[i] and pos is None and not esperar_reinicio:
                pendiente = "comprar"
            elif not objetivo[i] and pos is not None:
                pendiente = "vender"

    if pos is not None:  # cierre forzado al final de los datos
        cerrar(n - 1, cierres[-1], "fin_de_datos")
        curva[-1] = efectivo

    return {"operaciones": operaciones, "curva": curva, "omitidas": omitidas,
            "detenido_por_drawdown": detenido, "barras_en_mercado": barras_en_mercado}


# --------------------------------------------------------------------------- métricas

def _max_drawdown_pct(curva: Sequence[float]) -> float:
    pico, peor = curva[0], 0.0
    for v in curva:
        pico = max(pico, v)
        peor = max(peor, (pico - v) / pico * 100)
    return peor


def _sharpe(curva: Sequence[float], periodos_por_ano: float) -> Optional[float]:
    retornos = [curva[i] / curva[i - 1] - 1 for i in range(1, len(curva)) if curva[i - 1] > 0]
    if len(retornos) < 2:
        return None
    media = sum(retornos) / len(retornos)
    varianza = sum((r - media) ** 2 for r in retornos) / (len(retornos) - 1)
    desvio = math.sqrt(varianza)
    if desvio < 1e-12:
        return None
    return media / desvio * math.sqrt(periodos_por_ano)   # tasa libre de riesgo = 0


def calcular_metricas(cierres: Sequence[float], resultado: dict, params: ParametrosBacktest) -> dict:
    curva, ops = resultado["curva"], resultado["operaciones"]
    n = len(cierres)
    capital = params.capital_inicial
    final = curva[-1]

    pnls = [o["_pnl"] for o in ops]
    ganadoras = [p for p in pnls if p > 0]
    perdedoras = [p for p in pnls if p < 0]
    suma_g, suma_p = sum(ganadoras), -sum(perdedoras)

    anos = (n - 1) / params.periodos_por_ano
    anualizado = None
    if anos >= 1 and final > 0:
        anualizado = round(((final / capital) ** (1 / anos) - 1) * 100, 2)

    sharpe = _sharpe(curva, params.periodos_por_ano)
    return {
        "capital_inicial": round(capital, 2),
        "capital_final": round(final, 2),
        "retorno_total_pct": round((final / capital - 1) * 100, 2),
        "retorno_anualizado_pct": anualizado,   # solo con 1 año o más de datos
        "buy_and_hold_pct": round((cierres[-1] / cierres[0] - 1) * 100, 2),
        "max_drawdown_pct": round(_max_drawdown_pct(curva), 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "operaciones": len(ops),
        "ganadoras": len(ganadoras),
        "perdedoras": len(perdedoras),
        "win_rate_pct": round(len(ganadoras) / len(ops) * 100, 2) if ops else None,
        "profit_factor": round(suma_g / suma_p, 3) if suma_p > 0 else None,
        "pnl_promedio": round(sum(pnls) / len(ops), 2) if ops else None,
        "mejor_operacion": round(max(pnls), 2) if ops else None,
        "peor_operacion": round(min(pnls), 2) if ops else None,
        "tiempo_en_mercado_pct": round(resultado["barras_en_mercado"] / n * 100, 2),
        "detenido_por_drawdown": resultado["detenido_por_drawdown"],
    }


def _reducir_curva(curva: Sequence[float]) -> List[List[float]]:
    paso = max(1, math.ceil(len(curva) / MAX_PUNTOS_CURVA))
    indices = list(range(0, len(curva), paso))
    if indices[-1] != len(curva) - 1:
        indices.append(len(curva) - 1)
    return [[i, round(curva[i], 2)] for i in indices]


def _advertencias(metricas: dict, resultado: dict, n: int) -> List[str]:
    avisos = ["Resultado histórico: no garantiza resultados futuros."]
    if metricas["operaciones"] < POCAS_OPERACIONES:
        avisos.append(
            f"Solo {metricas['operaciones']} operaciones: con menos de {POCAS_OPERACIONES} "
            "las estadísticas (win rate, profit factor, Sharpe) no son fiables."
        )
    if metricas["detenido_por_drawdown"]:
        avisos.append("La operativa se detuvo al alcanzar el drawdown máximo; el resto del período quedó fuera del mercado.")
    if resultado["omitidas"]:
        avisos.append(f"{resultado['omitidas']} señales de compra se omitieron porque el tamaño calculado era 0 (saldo o límites).")
    if metricas["retorno_anualizado_pct"] is None:
        avisos.append("Menos de 1 año de datos: no se calcula retorno anualizado.")
    return avisos


# --------------------------------------------------------------------------- API pública

def ejecutar_backtest(
    estrategia: str,
    cierres: Sequence[float],
    parametros_estrategia: Optional[Dict[str, float]] = None,
    params: ParametrosBacktest = ParametrosBacktest(),
) -> dict:
    """Valida, calcula las señales, simula y resume. Lanza ValueError con mensajes claros."""
    if estrategia not in ESTRATEGIAS:
        raise ValueError(f"Estrategia desconocida '{estrategia}'. Disponibles: {', '.join(ESTRATEGIAS)}")
    definicion = ESTRATEGIAS[estrategia]

    parametros_estrategia = parametros_estrategia or {}
    desconocidos = set(parametros_estrategia) - set(definicion["parametros"])
    if desconocidos:
        raise ValueError(
            f"Parámetros desconocidos para '{estrategia}': {', '.join(sorted(desconocidos))}. "
            f"Válidos: {', '.join(definicion['parametros'])}"
        )
    for nombre, valor in parametros_estrategia.items():
        if not math.isfinite(valor):
            raise ValueError(f"{nombre} debe ser un número finito")

    params.validar()
    _validar_precios(cierres)
    if len(cierres) < MIN_PUNTOS:
        raise ValueError(f"Se necesitan al menos {MIN_PUNTOS} precios (recibidos {len(cierres)})")

    usados = definicion["validar"]({**definicion["parametros"], **parametros_estrategia}, len(cierres))
    objetivo = definicion["objetivo"](cierres, usados)

    resultado = simular(cierres, objetivo, params)
    metricas = calcular_metricas(cierres, resultado, params)

    return {
        "estrategia": estrategia,
        "parametros_estrategia": usados,
        "parametros_simulacion": asdict(params),
        "puntos": len(cierres),
        "metricas": metricas,
        "operaciones": [{k: v for k, v in o.items() if not k.startswith("_")} for o in resultado["operaciones"]],
        "curva_equity": _reducir_curva(resultado["curva"]),
        "advertencias": _advertencias(metricas, resultado, len(cierres)),
    }
