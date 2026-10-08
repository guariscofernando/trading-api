# tests/test_risk.py
"""Gestión de riesgo (lógica pura). Los valores esperados están calculados a mano."""
import math

import pytest

from app.services.risk import (
    LimitesRiesgo,
    analizar_portafolio,
    calcular_tamano_posicion,
    evaluar_trade,
    niveles_salida,
)


# ------------------------------------------------------------ tamaño de posición

def test_tamano_por_riesgo_fijo():
    # Riesgo 1% de 10.000 = 100; distancia al stop = 100 - 95 = 5 -> 20 unidades
    r = calcular_tamano_posicion(capital=10_000, entrada=100, stop=95, riesgo_pct=1)
    assert r["cantidad"] == 20
    assert r["valor_posicion"] == 2000
    assert r["posicion_pct"] == 20
    assert r["riesgo_monetario"] == 100
    assert r["riesgo_pct_real"] == 1
    assert r["distancia_stop_pct"] == 5
    assert r["limitado_por"] == "riesgo"


def test_tamano_limitado_por_posicion_maxima():
    r = calcular_tamano_posicion(10_000, 100, 95, riesgo_pct=1, posicion_max_pct=10)
    assert r["cantidad"] == 10            # 10% de 10.000 / 100
    assert r["limitado_por"] == "posicion_max"
    assert r["riesgo_pct_real"] == 0.5    # arriesga menos de lo permitido


def test_tamano_limitado_por_saldo():
    r = calcular_tamano_posicion(10_000, 100, 95, riesgo_pct=1, saldo_disponible=500)
    assert r["cantidad"] == 5
    assert r["limitado_por"] == "saldo"


def test_tamano_trunca_nunca_redondea_hacia_arriba():
    # 10 / 3 = 3.3333... ; redondear a 8 decimales daría 3.33333333 y el riesgo seguiría <= 10,
    # pero con 2/3 el redondeo sí se pasaría: se exige que el riesgo real NUNCA supere al pedido.
    for stop in (97, 96.3, 91.7, 99.99):
        r = calcular_tamano_posicion(1000, 100, stop, riesgo_pct=1)
        assert r["cantidad"] * (100 - stop) <= 10 + 1e-12


@pytest.mark.parametrize("kwargs", [
    dict(capital=0, entrada=100, stop=95, riesgo_pct=1),
    dict(capital=-5, entrada=100, stop=95, riesgo_pct=1),
    dict(capital=1000, entrada=0, stop=95, riesgo_pct=1),
    dict(capital=1000, entrada=100, stop=100, riesgo_pct=1),      # stop == entrada
    dict(capital=1000, entrada=100, stop=105, riesgo_pct=1),      # stop encima (corto)
    dict(capital=1000, entrada=100, stop=95, riesgo_pct=0),
    dict(capital=1000, entrada=100, stop=95, riesgo_pct=101),
    dict(capital=1000, entrada=100, stop=95, riesgo_pct=1, posicion_max_pct=150),  # apalancamiento
    dict(capital=1000, entrada=100, stop=95, riesgo_pct=1, saldo_disponible=-1),
    dict(capital=math.nan, entrada=100, stop=95, riesgo_pct=1),
    dict(capital=1000, entrada=math.inf, stop=95, riesgo_pct=1),
    dict(capital=1000, entrada=100, stop=95, riesgo_pct=math.nan),
])
def test_tamano_rechaza_entradas_invalidas(kwargs):
    with pytest.raises(ValueError):
        calcular_tamano_posicion(**kwargs)


# ------------------------------------------------------------- niveles de salida

def test_niveles_con_ratio():
    r = niveles_salida(entrada=100, stop_loss_pct=5, ratio_riesgo_beneficio=2)
    assert r["stop_loss"] == 95
    assert r["take_profit"] == 110        # 100 + 2 * 5
    assert r["ratio_riesgo_beneficio"] == 2


def test_niveles_con_take_profit_porcentual():
    r = niveles_salida(entrada=100, stop_loss_pct=5, take_profit_pct=20)
    assert r["take_profit"] == 120
    assert r["ratio_riesgo_beneficio"] == 4


def test_niveles_solo_stop():
    r = niveles_salida(entrada=100, stop_loss_pct=10)
    assert r["stop_loss"] == 90
    assert r["take_profit"] is None and r["ratio_riesgo_beneficio"] is None


@pytest.mark.parametrize("kwargs", [
    dict(entrada=100, stop_loss_pct=0),
    dict(entrada=100, stop_loss_pct=100),
    dict(entrada=100, stop_loss_pct=5, take_profit_pct=10, ratio_riesgo_beneficio=2),
    dict(entrada=100, stop_loss_pct=5, take_profit_pct=-1),
    dict(entrada=-1, stop_loss_pct=5),
    dict(entrada=100, stop_loss_pct=math.nan),
])
def test_niveles_rechaza_entradas_invalidas(kwargs):
    with pytest.raises(ValueError):
        niveles_salida(**kwargs)


# ---------------------------------------------------------------- evaluar trade

def _codigos(resultado):
    return {v["codigo"] for v in resultado["violaciones"]}


def test_evaluar_trade_permitido():
    r = evaluar_trade(capital=10_000, entrada=100, stop=95, cantidad=20)
    assert r["permitido"] is True
    assert r["violaciones"] == []
    assert r["metricas"]["riesgo_pct"] == 1


def test_evaluar_trade_detecta_riesgo_y_tamano_excesivos():
    # 60 unidades: arriesga 300 (3%) y la posición vale 6000 (60%)
    r = evaluar_trade(10_000, 100, 95, cantidad=60)
    assert r["permitido"] is False
    assert _codigos(r) == {"riesgo_por_trade", "tamano_posicion"}


def test_evaluar_trade_limite_exacto_es_valido():
    # riesgo exactamente 1% y posición exactamente 25%: en el límite, no por encima
    r = evaluar_trade(10_000, 100, 96, cantidad=25)
    assert r["metricas"]["riesgo_pct"] == 1 and r["metricas"]["posicion_pct"] == 25
    assert r["permitido"] is True


def test_evaluar_trade_saldo_perdida_diaria_drawdown_y_posiciones():
    r = evaluar_trade(
        10_000, 100, 95, cantidad=20,
        saldo_disponible=1000, perdida_diaria_pct=3.0,
        drawdown_actual_pct=20.0, posiciones_abiertas=5,
    )
    assert _codigos(r) == {"saldo_insuficiente", "perdida_diaria", "drawdown_maximo", "max_posiciones"}


def test_evaluar_trade_respeta_limites_personalizados():
    limites = LimitesRiesgo(riesgo_max_por_trade_pct=0.5)
    assert evaluar_trade(10_000, 100, 95, 20, limites=limites)["permitido"] is False


def test_evaluar_trade_advierte_riesgo_agresivo_si_el_limite_lo_permite():
    limites = LimitesRiesgo(riesgo_max_por_trade_pct=5, posicion_max_pct=100)
    r = evaluar_trade(10_000, 100, 95, 50, limites=limites)   # arriesga 2,5%
    assert r["permitido"] is True and r["advertencias"]


@pytest.mark.parametrize("kwargs", [
    dict(capital=0, entrada=100, stop=95, cantidad=1),
    dict(capital=1000, entrada=100, stop=100, cantidad=1),
    dict(capital=1000, entrada=100, stop=95, cantidad=0),
    dict(capital=1000, entrada=100, stop=95, cantidad=math.nan),
])
def test_evaluar_trade_rechaza_entradas_invalidas(kwargs):
    with pytest.raises(ValueError):
        evaluar_trade(**kwargs)


# -------------------------------------------------------------------- portafolio

def _t(i, tipo, activo, precio, cantidad, fecha="2026-01-01 10:00"):
    return {"id": i, "tipo": tipo, "activo": activo, "precio": precio, "cantidad": cantidad, "fecha": fecha}


def test_portafolio_costo_promedio_y_pnl_realizado():
    trades = [
        _t(1, "compra", "BTC", 100, 1, "2026-01-01 10:00"),
        _t(2, "compra", "BTC", 200, 1, "2026-01-02 10:00"),   # promedio = 150
        _t(3, "venta", "BTC", 180, 1, "2026-01-03 10:00"),    # pnl = (180 - 150) * 1 = 30
    ]
    r = analizar_portafolio(trades)
    btc = r["exposicion"]["por_activo"]["BTC"]
    assert btc["cantidad"] == 1 and btc["costo_promedio"] == 150
    assert r["realizado"]["pnl_total"] == 30
    assert r["realizado"]["win_rate_pct"] == 100
    assert r["realizado"]["profit_factor"] is None            # sin pérdidas no está definido


def test_portafolio_drawdown_win_rate_y_profit_factor():
    # Compra 4 a 100 y vende de a 1: pnl = +50, -30, -40, +10
    trades = [_t(1, "compra", "ETH", 100, 4, "2026-01-01 09:00")] + [
        _t(2, "venta", "ETH", 150, 1, "2026-01-02 09:00"),
        _t(3, "venta", "ETH", 70, 1, "2026-01-03 09:00"),
        _t(4, "venta", "ETH", 60, 1, "2026-01-04 09:00"),
        _t(5, "venta", "ETH", 110, 1, "2026-01-05 09:00"),
    ]
    r = analizar_portafolio(trades)["realizado"]
    assert r["pnl_total"] == -10
    assert r["win_rate_pct"] == 50
    assert r["profit_factor"] == round(60 / 70, 4)
    # acumulado: 50, 20, -20, -10 -> pico 50, mínimo -20 -> drawdown 70
    assert r["max_drawdown_realizado"] == 70
    assert r["peor_dia"] == {"fecha": "2026-01-04", "pnl": -40}


def test_portafolio_ordena_por_fecha_aunque_lleguen_desordenados():
    trades = [
        _t(2, "venta", "BTC", 120, 1, "2026-01-02 10:00"),
        _t(1, "compra", "BTC", 100, 1, "2026-01-01 10:00"),
    ]
    assert analizar_portafolio(trades)["realizado"]["pnl_total"] == 20


def test_portafolio_venta_sin_posicion_no_inventa_ganancias():
    r = analizar_portafolio([_t(1, "venta", "BTC", 100, 5)])
    assert r["realizado"]["ventas_cerradas"] == 0 and r["realizado"]["pnl_total"] == 0
    assert r["advertencias"]


def test_portafolio_venta_mayor_que_posicion_solo_cuenta_lo_cubierto():
    trades = [_t(1, "compra", "BTC", 100, 1, "2026-01-01 10:00"),
              _t(2, "venta", "BTC", 150, 3, "2026-01-02 10:00")]
    r = analizar_portafolio(trades)
    assert r["realizado"]["pnl_total"] == 50          # solo 1 unidad estaba cubierta
    assert r["advertencias"]
    assert "BTC" not in r["exposicion"]["por_activo"]


def test_portafolio_alertas_de_concentracion_y_limites():
    trades = [_t(1, "compra", "BTC", 100, 90, "2026-01-01 10:00"),    # 9.000
              _t(2, "compra", "ETH", 100, 10, "2026-01-01 11:00")]    # 1.000
    r = analizar_portafolio(trades, capital=10_000)
    codigos = {a["codigo"] for a in r["alertas"]}
    assert "concentracion" in codigos
    assert r["exposicion"]["exposicion_pct_capital"] == 100
    assert r["exposicion"]["por_activo"]["BTC"]["peso_pct"] == 90


def test_portafolio_alerta_perdida_diaria_sobre_capital():
    trades = [_t(1, "compra", "BTC", 100, 10, "2026-01-01 10:00"),
              _t(2, "venta", "BTC", 50, 10, "2026-01-02 10:00")]       # pierde 500 = 5% de 10.000
    r = analizar_portafolio(trades, capital=10_000)
    assert "perdida_diaria" in {a["codigo"] for a in r["alertas"]}


def test_portafolio_vacio():
    r = analizar_portafolio([])
    assert r["realizado"]["ventas_cerradas"] == 0 and r["realizado"]["win_rate_pct"] is None
    assert r["exposicion"]["por_activo"] == {}


@pytest.mark.parametrize("capital", [0, -1, math.nan])
def test_portafolio_rechaza_capital_invalido(capital):
    with pytest.raises(ValueError):
        analizar_portafolio([], capital=capital)
