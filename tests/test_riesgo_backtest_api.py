# tests/test_riesgo_backtest_api.py
"""Endpoints /riesgo y /backtest: autenticación, validación, aislamiento y fuente de datos."""
import math
import random

import pytest

NO_AUTORIZADO = (401, 403)


def _serie(n=120, semilla=11):
    rng = random.Random(semilla)
    precios = [100.0]
    for i in range(n - 1):
        precios.append(max(1.0, precios[-1] * (1 + 0.004 * math.sin(i / 15) + rng.uniform(-0.01, 0.01))))
    return precios


def _trade(client, headers, tipo, activo, precio, cantidad):
    r = client.post("/trades/", json={"tipo": tipo, "activo": activo, "precio": precio, "cantidad": cantidad},
                    headers=headers)
    assert r.status_code == 201, r.text


# ------------------------------------------------------------------ sin token

@pytest.mark.parametrize("metodo,ruta", [
    ("GET", "/riesgo/limites"),
    ("POST", "/riesgo/tamano-posicion"),
    ("POST", "/riesgo/niveles-salida"),
    ("POST", "/riesgo/evaluar-trade"),
    ("GET", "/riesgo/portafolio"),
    ("GET", "/backtest/estrategias"),
    ("POST", "/backtest/"),
])
def test_endpoints_exigen_token(client, metodo, ruta):
    assert client.request(metodo, ruta).status_code in NO_AUTORIZADO


# ---------------------------------------------------------------------- riesgo

def test_limites_por_defecto(client, auth_headers):
    r = client.get("/riesgo/limites", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["riesgo_max_por_trade_pct"] == 1.0


def test_tamano_posicion(client, auth_headers):
    r = client.post("/riesgo/tamano-posicion", headers=auth_headers,
                    json={"capital": 10000, "entrada": 100, "stop": 95, "riesgo_pct": 1})
    assert r.status_code == 200
    assert r.json()["cantidad"] == 20 and r.json()["limitado_por"] == "riesgo"


def test_tamano_posicion_stop_invalido_da_422_con_mensaje(client, auth_headers):
    r = client.post("/riesgo/tamano-posicion", headers=auth_headers,
                    json={"capital": 10000, "entrada": 100, "stop": 105})
    assert r.status_code == 422
    assert "stop" in r.text.lower()


@pytest.mark.parametrize("valor_json", ["NaN", "Infinity", "-5", "0"])
def test_numeros_no_finitos_o_no_positivos_se_rechazan(client, auth_headers, valor_json):
    cuerpo = '{"capital": %s, "entrada": 100, "stop": 95}' % valor_json
    r = client.post("/riesgo/tamano-posicion", content=cuerpo,
                    headers={**auth_headers, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_niveles_salida(client, auth_headers):
    r = client.post("/riesgo/niveles-salida", headers=auth_headers,
                    json={"entrada": 100, "stop_loss_pct": 5, "ratio_riesgo_beneficio": 2})
    assert r.status_code == 200
    assert r.json()["stop_loss"] == 95 and r.json()["take_profit"] == 110


def test_niveles_salida_take_profit_y_ratio_a_la_vez_es_422(client, auth_headers):
    r = client.post("/riesgo/niveles-salida", headers=auth_headers,
                    json={"entrada": 100, "stop_loss_pct": 5, "take_profit_pct": 10, "ratio_riesgo_beneficio": 2})
    assert r.status_code == 422


def test_evaluar_trade_con_limites_por_defecto_y_personalizados(client, auth_headers):
    base = {"capital": 10000, "entrada": 100, "stop": 95, "cantidad": 40}   # arriesga 2%
    r = client.post("/riesgo/evaluar-trade", headers=auth_headers, json=base)
    assert r.status_code == 200 and r.json()["permitido"] is False
    assert "riesgo_por_trade" in {v["codigo"] for v in r.json()["violaciones"]}

    permisivo = {**base, "limites": {"riesgo_max_por_trade_pct": 5, "posicion_max_pct": 100}}
    r = client.post("/riesgo/evaluar-trade", headers=auth_headers, json=permisivo)
    assert r.json()["permitido"] is True
    # lo no indicado conserva su valor por defecto
    assert r.json()["limites_aplicados"]["drawdown_max_pct"] == 20.0


def test_portafolio_solo_usa_trades_del_usuario(client, usuario_a, usuario_b):
    _trade(client, usuario_a["headers"], "compra", "BTC", 100, 10)
    _trade(client, usuario_a["headers"], "venta", "BTC", 150, 10)

    a = client.get("/riesgo/portafolio?capital=10000", headers=usuario_a["headers"])
    b = client.get("/riesgo/portafolio?capital=10000", headers=usuario_b["headers"])
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["realizado"]["pnl_total"] == 500
    assert b.json()["realizado"]["pnl_total"] == 0
    assert b.json()["realizado"]["ventas_cerradas"] == 0


@pytest.mark.parametrize("capital", ["0", "-1", "NaN", "abc"])
def test_portafolio_capital_invalido(client, auth_headers, capital):
    assert client.get(f"/riesgo/portafolio?capital={capital}", headers=auth_headers).status_code == 422


# -------------------------------------------------------------------- backtest

def test_listar_estrategias(client, auth_headers):
    r = client.get("/backtest/estrategias", headers=auth_headers)
    assert r.status_code == 200 and set(r.json()) == {"cruce_medias", "rsi"}


def test_backtest_con_precios_enviados(client, auth_headers):
    r = client.post("/backtest/", headers=auth_headers, json={
        "estrategia": "cruce_medias", "parametros_estrategia": {"rapida": 5, "lenta": 20},
        "precios": _serie(),
    })
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["origen_datos"] == "precios_enviados"
    assert cuerpo["parametros_estrategia"] == {"rapida": 5, "lenta": 20}
    assert cuerpo["metricas"]["capital_inicial"] == 10000
    assert cuerpo["advertencias"]


def test_backtest_aplica_los_parametros_de_simulacion(client, auth_headers):
    base = {"estrategia": "cruce_medias", "parametros_estrategia": {"rapida": 5, "lenta": 20}, "precios": _serie()}
    sin_costos = client.post("/backtest/", headers=auth_headers,
                             json={**base, "comision_pct": 0, "slippage_pct": 0}).json()
    con_costos = client.post("/backtest/", headers=auth_headers,
                             json={**base, "comision_pct": 1, "slippage_pct": 1}).json()
    assert sin_costos["metricas"]["operaciones"] > 0
    assert con_costos["metricas"]["capital_final"] < sin_costos["metricas"]["capital_final"]
    assert con_costos["parametros_simulacion"]["comision_pct"] == 1


@pytest.mark.parametrize("cuerpo,fragmento", [
    ({"estrategia": "inexistente", "precios": [100.0] * 40}, "estrategia"),
    ({"estrategia": "rsi"}, "fuente"),                                                 # sin datos
    ({"estrategia": "rsi", "precios": [100.0] * 40, "coin_id": "bitcoin"}, "fuente"),  # dos fuentes
    ({"estrategia": "rsi", "precios": [100.0] * 5}, "precios"),                        # muy pocos
    ({"estrategia": "rsi", "precios": [100.0] * 5001}, "precios"),                     # demasiados
    ({"estrategia": "rsi", "precios": [100.0] * 39 + [-1.0]}, "precios"),
    ({"estrategia": "rsi", "precios": [100.0] * 40, "stop_loss_pct": 0}, "stop_loss_pct"),
    ({"estrategia": "rsi", "precios": [100.0] * 40, "comision_pct": 99}, "comision_pct"),
    ({"estrategia": "rsi", "coin_id": "../../etc/passwd"}, "coin_id"),                 # inyección en la URL
    ({"estrategia": "rsi", "coin_id": "bitcoin?x=1"}, "coin_id"),
    ({"estrategia": "rsi", "coin_id": "bitcoin", "dias": 5000}, "dias"),
])
def test_backtest_validaciones(client, auth_headers, cuerpo, fragmento):
    r = client.post("/backtest/", headers=auth_headers, json=cuerpo)
    assert r.status_code == 422
    assert fragmento in r.text


def test_backtest_parametro_de_estrategia_invalido_da_422_con_mensaje(client, auth_headers):
    r = client.post("/backtest/", headers=auth_headers, json={
        "estrategia": "cruce_medias", "parametros_estrategia": {"rapida": 30, "lenta": 10}, "precios": _serie()})
    assert r.status_code == 422 and "rapida" in r.text
    r = client.post("/backtest/", headers=auth_headers, json={
        "estrategia": "rsi", "parametros_estrategia": {"inventado": 1}, "precios": _serie()})
    assert r.status_code == 422 and "inventado" in r.text


def test_backtest_con_coin_id_usa_el_historico_de_coingecko(client, auth_headers, monkeypatch):
    llamadas = []

    async def falso_historico(coin_id, moneda, dias):
        llamadas.append((coin_id, moneda, dias))
        return _serie(150)

    monkeypatch.setattr("app.routers.backtest_router.obtener_historico", falso_historico)
    r = client.post("/backtest/", headers=auth_headers, json={
        "estrategia": "rsi", "coin_id": "bitcoin", "dias": 180})
    assert r.status_code == 200, r.text
    assert r.json()["origen_datos"] == "coingecko:bitcoin" and r.json()["puntos"] == 150
    assert llamadas == [("bitcoin", "usd", 180)]


def test_backtest_si_coingecko_falla_responde_502(client, auth_headers, monkeypatch):
    async def sin_datos(*a, **k):
        return None

    monkeypatch.setattr("app.routers.backtest_router.obtener_historico", sin_datos)
    r = client.post("/backtest/", headers=auth_headers, json={"estrategia": "rsi", "coin_id": "bitcoin"})
    assert r.status_code == 502


# ------------------------------------------------- obtener_historico (CoinGecko)

class _Respuesta:
    def __init__(self, status=200, datos=None, texto=""):
        self.status_code, self._datos, self.text = status, datos, texto

    def json(self):
        if isinstance(self._datos, Exception):
            raise self._datos
        return self._datos


def _cliente_falso(respuesta=None, error=None, registro=None):
    class Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, timeout=None):
            if registro is not None:
                registro.append((url, params))
            if error:
                raise error
            return respuesta
    return Cliente


def test_obtener_historico_extrae_los_cierres_y_usa_la_url_correcta(monkeypatch):
    import asyncio
    import app.services.coingecko as cg
    from app.services.cache import cache
    cache.clear()
    registro = []
    datos = {"prices": [[1, 100.5], [2, 101.0], [3, 99.0]]}
    monkeypatch.setattr(cg.httpx, "AsyncClient", _cliente_falso(_Respuesta(200, datos), registro=registro))

    assert asyncio.run(cg.obtener_historico("bitcoin", "usd", 90)) == [100.5, 101.0, 99.0]
    url, params = registro[0]
    assert url.endswith("/coins/bitcoin/market_chart")
    assert params == {"vs_currency": "usd", "days": 90, "interval": "daily"}

    # segunda llamada: sale del caché, no vuelve a pedir
    assert asyncio.run(cg.obtener_historico("bitcoin", "usd", 90)) == [100.5, 101.0, 99.0]
    assert len(registro) == 1
    cache.clear()


@pytest.mark.parametrize("respuesta,error", [
    (_Respuesta(429, texto="rate limit"), None),
    (_Respuesta(200, {"prices": []}), None),
    (_Respuesta(200, {"otra_cosa": 1}), None),
    (_Respuesta(200, {"prices": [[1]]}), None),
    (_Respuesta(200, ValueError("json roto")), None),
    (None, __import__("httpx").ConnectError("sin red")),
])
def test_obtener_historico_devuelve_none_ante_fallos(monkeypatch, respuesta, error):
    import asyncio
    import app.services.coingecko as cg
    from app.services.cache import cache
    cache.clear()
    monkeypatch.setattr(cg.httpx, "AsyncClient", _cliente_falso(respuesta, error))
    assert asyncio.run(cg.obtener_historico("ethereum", "usd", 30)) is None
    cache.clear()


# ------------------------------------------------ manejador global de validación

@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity"])
def test_valores_no_finitos_en_json_dan_422_y_no_500_en_cualquier_endpoint(client, auth_headers, valor):
    # /trades/ es un endpoint anterior a la fase 2: el manejador global debe cubrirlo también
    cuerpo = '{"tipo": "compra", "activo": "BTC", "precio": %s, "cantidad": "no-es-numero"}' % valor
    r = client.post("/trades/", content=cuerpo, headers={**auth_headers, "Content-Type": "application/json"})
    assert r.status_code == 422, r.text


def test_error_de_validacion_no_devuelve_listas_enormes(client, auth_headers):
    r = client.post("/backtest/", headers=auth_headers,
                    json={"estrategia": "rsi", "precios": [100.0] * 6000})
    assert r.status_code == 422
    assert len(r.text) < 3000                      # antes devolvía los 6.000 valores
    assert "elementos" in r.text
