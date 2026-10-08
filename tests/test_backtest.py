# tests/test_backtest.py
"""Motor de backtesting (lógica pura). Valores esperados calculados a mano."""
import math
import random
from dataclasses import replace

import pytest

from app.services.backtest import (
    MAX_PUNTOS,
    ParametrosBacktest,
    ejecutar_backtest,
    listar_estrategias,
    rsi,
    simular,
    sma,
    calcular_metricas,
)

# Parámetros "limpios": sin comisión ni slippage, para poder comprobar números exactos.
# Capital 10.000, riesgo 1%, stop 5% -> 20 unidades a 100 (posición de 2.000 = 20% < 25%).
LIMPIO = ParametrosBacktest(comision_pct=0, slippage_pct=0)


def _objetivo(n, *tramos):
    """Construye una serie de True/False a partir de tramos (desde_idx, hasta_idx_exclusivo)."""
    obj = [False] * n
    for a, b in tramos:
        for i in range(a, b):
            obj[i] = True
    return obj


# -------------------------------------------------------------------- indicadores

def test_sma():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    assert sma([1, 2], 3) == [None, None]


def test_rsi_tendencia_alcista_es_100_y_bajista_es_0():
    subida = [100 + i for i in range(30)]
    bajada = [200 - i for i in range(30)]
    assert rsi(subida, 14)[-1] == 100
    assert rsi(bajada, 14)[-1] == 0


def test_rsi_precio_plano_es_50_y_los_primeros_valores_son_none():
    r = rsi([100.0] * 30, 14)
    assert r[:14] == [None] * 14
    assert r[14] == 50 and r[-1] == 50


def test_rsi_calculo_exacto_con_suavizado_de_wilder():
    # periodo 2: cambios +2, -1 -> media_g = 1, media_p = 0,5 -> RS = 2 -> RSI = 66,666...
    r = rsi([10, 12, 11], periodo=2)
    assert r[2] == pytest.approx(100 - 100 / 3)
    # siguiente cambio +3: media_g = (1*1 + 3)/2 = 2 ; media_p = (0,5*1 + 0)/2 = 0,25 -> RS = 8 -> 88,88...
    r = rsi([10, 12, 11, 14], periodo=2)
    assert r[3] == pytest.approx(100 - 100 / 9)


# ------------------------------------------------------------ simulación exacta

def test_operacion_ganadora_exacta_sin_costos():
    cierres = [100, 100, 110, 110, 110]
    # señal encendida en 0-1: compra en la barra 1 (a 100); se apaga en la 2: vende en la 3 (a 110)
    r = simular(cierres, _objetivo(5, (0, 2)), LIMPIO)
    (op,) = r["operaciones"]
    assert op["cantidad"] == 20
    assert (op["entrada_idx"], op["salida_idx"]) == (1, 3)
    assert op["precio_entrada"] == 100 and op["precio_salida"] == 110
    assert op["pnl"] == 200 and op["motivo"] == "senal"
    assert r["curva"][-1] == 10_200


def test_comision_y_slippage_reducen_el_resultado_con_cuentas_exactas():
    cierres = [100, 100, 110, 110, 110]
    # solo comisión 1% por lado: compra 20 * 100 * 1,01 = 2.020 ; venta 20 * 110 * 0,99 = 2.178
    r = simular(cierres, _objetivo(5, (0, 2)), replace(LIMPIO, comision_pct=1))
    assert r["operaciones"][0]["pnl"] == pytest.approx(158)
    assert r["curva"][-1] == pytest.approx(10_158)
    # con slippage 1% el precio de entrada sube y el de salida baja
    r2 = simular(cierres, _objetivo(5, (0, 2)), replace(LIMPIO, slippage_pct=1))
    op = r2["operaciones"][0]
    assert op["precio_entrada"] == pytest.approx(101) and op["precio_salida"] == pytest.approx(108.9)
    assert op["pnl"] < 200


def test_sin_mirar_el_futuro_una_senal_en_la_ultima_barra_no_se_ejecuta():
    cierres = [100.0] * 39 + [200.0]          # el salto ocurre justo en la última barra
    r = ejecutar_backtest("cruce_medias", cierres, {"rapida": 3, "lenta": 10}, LIMPIO)
    assert r["metricas"]["operaciones"] == 0
    assert r["metricas"]["capital_final"] == 10_000


def test_la_orden_se_ejecuta_en_la_barra_siguiente_y_no_en_la_de_la_senal():
    cierres = [100, 100, 100, 120, 120, 120]
    r = simular(cierres, _objetivo(6, (2, 6)), LIMPIO)   # señal aparece en la barra 2
    assert r["operaciones"][0]["entrada_idx"] == 3
    assert r["operaciones"][0]["precio_entrada"] == 120   # no el 100 de la barra de la señal


def test_stop_loss_sale_al_cierre_aunque_sea_peor_que_el_stop():
    # entrada 100, stop 95. Cierra a 94: pérdida = 20 * 6 = 120 (> 100 de riesgo por el salto)
    r = simular([100, 100, 94, 94, 94], _objetivo(5, (0, 5)), LIMPIO)
    (op,) = r["operaciones"]
    assert op["motivo"] == "stop_loss" and op["salida_idx"] == 2
    assert op["pnl"] == -120


def test_stop_loss_exacto_pierde_el_riesgo_configurado():
    r = simular([100, 100, 95, 95, 95], _objetivo(5, (0, 5)), LIMPIO)
    assert r["operaciones"][0]["pnl"] == -100            # 1% del capital


def test_take_profit():
    p = replace(LIMPIO, take_profit_pct=10)
    r = simular([100, 100, 105, 111, 111], _objetivo(5, (0, 5)), p)
    (op,) = r["operaciones"]
    assert op["motivo"] == "take_profit" and op["salida_idx"] == 3
    assert op["pnl"] == pytest.approx(220)               # 20 * 11


def test_no_reentra_tras_un_stop_hasta_que_la_senal_se_apague_y_vuelva():
    cierres = [100, 100, 90, 90, 90, 90, 90, 90]
    # señal siempre encendida: tras el stop en la barra 2 NO debe volver a comprar
    r = simular(cierres, [True] * 8, LIMPIO)
    assert len(r["operaciones"]) == 1
    # señal que se apaga en la barra 4 y vuelve en la 5: sí puede reentrar
    r = simular(cierres, [True, True, True, True, False, True, True, True], LIMPIO)
    assert len(r["operaciones"]) == 2 and r["operaciones"][1]["entrada_idx"] == 6


def test_drawdown_maximo_cierra_y_detiene_la_operativa():
    # Todo el capital en una posición (riesgo 50%, stop 50%, tope 100%): cae 30% > límite 20%
    p = replace(LIMPIO, riesgo_por_trade_pct=50, stop_loss_pct=50, posicion_max_pct=100, drawdown_max_pct=20)
    cierres = [100, 100, 70, 100, 100, 100]
    r = simular(cierres, [True] * 6, p)
    (op,) = r["operaciones"]
    assert op["motivo"] == "drawdown_maximo" and op["salida_idx"] == 2
    assert r["detenido_por_drawdown"] is True
    assert r["curva"][-1] == pytest.approx(7_000)        # quedó fuera aunque el precio se recuperó


def test_posicion_abierta_al_final_se_cierra_y_cuenta():
    r = simular([100, 100, 105, 110, 120], [True] * 5, LIMPIO)
    (op,) = r["operaciones"]
    assert op["motivo"] == "fin_de_datos" and op["salida_idx"] == 4
    assert op["pnl"] == pytest.approx(400)               # 20 * (120 - 100)
    assert r["curva"][-1] == pytest.approx(10_400)


def test_nunca_hay_apalancamiento_ni_saldo_negativo():
    rng = random.Random(7)
    precios = [100.0]
    for _ in range(400):
        precios.append(max(1.0, precios[-1] * (1 + rng.uniform(-0.06, 0.06))))
    p = replace(LIMPIO, riesgo_por_trade_pct=100, stop_loss_pct=1, posicion_max_pct=100, comision_pct=0.5)
    r = simular(precios, [True, False] * (len(precios) // 2) + [True], p)
    assert min(r["curva"]) >= 0
    for op in r["operaciones"]:
        assert op["cantidad"] * op["precio_entrada"] <= 10_000 * 1.0000001


# ------------------------------------------------------------------- métricas

def test_max_drawdown_y_buy_and_hold():
    cierres = [100, 110, 99, 120, 120]
    resultado = {"curva": [100.0, 110.0, 99.0, 120.0, 120.0], "operaciones": [],
                 "barras_en_mercado": 0, "detenido_por_drawdown": False, "omitidas": 0}
    m = calcular_metricas(cierres, resultado, replace(LIMPIO, capital_inicial=100))
    assert m["max_drawdown_pct"] == 10                   # (110 - 99) / 110
    assert m["retorno_total_pct"] == 20
    assert m["buy_and_hold_pct"] == 20


def test_sharpe_es_none_sin_variabilidad_y_tiene_signo_correcto():
    plano = {"curva": [100.0] * 10, "operaciones": [], "barras_en_mercado": 0,
             "detenido_por_drawdown": False, "omitidas": 0}
    assert calcular_metricas([1.0] * 10, plano, replace(LIMPIO, capital_inicial=100))["sharpe"] is None
    sube = {**plano, "curva": [100, 101, 103, 102, 106, 107, 110, 109, 113, 115]}
    baja = {**plano, "curva": [115, 113, 109, 110, 107, 106, 102, 103, 101, 100]}
    p = replace(LIMPIO, capital_inicial=115)
    assert calcular_metricas([1.0] * 10, sube, replace(p, capital_inicial=100))["sharpe"] > 0
    assert calcular_metricas([1.0] * 10, baja, p)["sharpe"] < 0


def test_win_rate_y_profit_factor():
    # Ciclo 1: compra en 1 (100), vende en 3 (110) -> +200 con 20 unidades.
    # Ciclo 2: con 10.200 de capital arriesga 1% = 102 -> 20,4 unidades; compra en 5 (100)
    #          y el stop (95) salta en la barra 6 -> -102.
    cierres = [100, 100, 100, 110, 110, 100, 95, 95, 95]
    obj = _objetivo(9, (0, 2), (4, 9))
    sim = simular(cierres, obj, LIMPIO)
    m = calcular_metricas(cierres, sim, LIMPIO)
    pnls = [o["pnl"] for o in sim["operaciones"]]
    assert pnls == [pytest.approx(200, abs=0.01), pytest.approx(-102, abs=0.01)]
    assert [o["motivo"] for o in sim["operaciones"]] == ["senal", "stop_loss"]
    assert m["win_rate_pct"] == 50
    assert m["profit_factor"] == pytest.approx(200 / 102, abs=0.001)
    assert m["operaciones"] == 2
    assert m["mejor_operacion"] == pytest.approx(200, abs=0.01)
    assert m["peor_operacion"] == pytest.approx(-102, abs=0.01)


def test_retorno_anualizado_solo_con_un_ano_o_mas_de_datos():
    base = {"operaciones": [], "barras_en_mercado": 0, "detenido_por_drawdown": False, "omitidas": 0}
    corto = calcular_metricas([1.0] * 100, {**base, "curva": [10_000.0] * 99 + [11_000.0]}, LIMPIO)
    assert corto["retorno_anualizado_pct"] is None
    n = 366                                                # 365 períodos = 1 año exacto
    largo = calcular_metricas([1.0] * n, {**base, "curva": [10_000.0] * (n - 1) + [11_000.0]}, LIMPIO)
    assert largo["retorno_anualizado_pct"] == pytest.approx(10.0)


# -------------------------------------------------------------- API de alto nivel

def _serie_tendencia(n=300, semilla=3):
    rng = random.Random(semilla)
    precios = [100.0]
    for i in range(n - 1):
        deriva = 0.004 * math.sin(i / 25)
        precios.append(max(1.0, precios[-1] * (1 + deriva + rng.uniform(-0.01, 0.01))))
    return precios


@pytest.mark.parametrize("estrategia", ["cruce_medias", "rsi"])
def test_ejecutar_backtest_devuelve_estructura_completa_y_es_determinista(estrategia):
    precios = _serie_tendencia()
    r1 = ejecutar_backtest(estrategia, precios)
    r2 = ejecutar_backtest(estrategia, precios)
    assert r1 == r2
    assert {"metricas", "operaciones", "curva_equity", "advertencias", "parametros_estrategia"} <= set(r1)
    assert r1["curva_equity"][0][0] == 0 and r1["curva_equity"][-1][0] == len(precios) - 1
    assert any("no garantiza" in a for a in r1["advertencias"])
    for valor in r1["metricas"].values():
        assert not isinstance(valor, float) or math.isfinite(valor)


def test_pocas_operaciones_genera_advertencia():
    r = ejecutar_backtest("cruce_medias", _serie_tendencia(60), {"rapida": 3, "lenta": 10})
    assert r["metricas"]["operaciones"] < 30
    assert any("no son fiables" in a for a in r["advertencias"])


def test_la_curva_devuelta_se_reduce_pero_conserva_extremos():
    r = ejecutar_backtest("cruce_medias", _serie_tendencia(MAX_PUNTOS, 5))
    assert len(r["curva_equity"]) <= 205
    assert r["curva_equity"][-1][0] == MAX_PUNTOS - 1


def test_listar_estrategias_expone_parametros_por_defecto():
    e = listar_estrategias()
    assert e["cruce_medias"]["parametros_por_defecto"] == {"rapida": 10, "lenta": 30}
    assert set(e) == {"cruce_medias", "rsi"}


@pytest.mark.parametrize("precios", [
    [100.0] * (MAX_PUNTOS + 1),                  # demasiados
    [100.0] * 10,                                # muy pocos
    [100.0] * 29 + [math.nan],
    [100.0] * 29 + [math.inf],
    [100.0] * 29 + [0.0],
    [100.0] * 29 + [-5.0],
])
def test_precios_invalidos_se_rechazan(precios):
    with pytest.raises(ValueError):
        ejecutar_backtest("cruce_medias", precios, {"rapida": 2, "lenta": 5})


@pytest.mark.parametrize("estrategia,parametros", [
    ("inexistente", {}),
    ("cruce_medias", {"rapida": 30, "lenta": 10}),
    ("cruce_medias", {"rapida": 0, "lenta": 10}),
    ("cruce_medias", {"lenta": 500}),
    ("cruce_medias", {"lenta": 40}),             # con 40 precios hacen falta lenta + 2
    ("cruce_medias", {"desconocido": 1}),
    ("cruce_medias", {"rapida": math.nan}),
    ("rsi", {"sobreventa": 80, "sobrecompra": 20}),
    ("rsi", {"periodo": 1}),
    ("rsi", {"sobrecompra": 100}),
])
def test_parametros_de_estrategia_invalidos_se_rechazan(estrategia, parametros):
    with pytest.raises(ValueError):
        ejecutar_backtest(estrategia, [100.0 + i % 7 for i in range(40)], parametros)


@pytest.mark.parametrize("cambios", [
    dict(capital_inicial=0), dict(capital_inicial=math.nan),
    dict(riesgo_por_trade_pct=0), dict(riesgo_por_trade_pct=101),
    dict(stop_loss_pct=0), dict(stop_loss_pct=100),
    dict(take_profit_pct=0), dict(posicion_max_pct=150),
    dict(drawdown_max_pct=0), dict(comision_pct=-1), dict(slippage_pct=50),
    dict(periodos_por_ano=0),
])
def test_parametros_de_simulacion_invalidos_se_rechazan(cambios):
    with pytest.raises(ValueError):
        ejecutar_backtest("cruce_medias", _serie_tendencia(60), {"rapida": 3, "lenta": 10},
                          replace(ParametrosBacktest(), **cambios))
