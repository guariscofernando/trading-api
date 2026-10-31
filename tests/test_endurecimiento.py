# tests/test_endurecimiento.py
"""Fase 11: endurecimiento antes de abrir la API al público (config estricta, caché acotado, validación de
entradas que llegan a servicios externos y límites por abuso)."""
import concurrent.futures
import threading
from datetime import datetime, timedelta

import pytest

from app.config import _booleano, config
from app.dao.UserDAO import UserDAO
from app.dao.WatchlistDAO import WatchlistDAO, WatchlistLlena
from app.services import validacion
from app.services.cache import MAX_ENTRADAS, SimpleCache
from tests.conftest import crear_usuario_y_login
from tests.test_config_ratelimit import _cfg


# ====================================================================== booleanos estrictos

@pytest.mark.parametrize("texto", ["true", "TRUE", " True ", "1", "yes", "on"])
def test_valores_verdaderos(monkeypatch, texto):
    monkeypatch.setenv("X_FLAG", texto)
    assert _booleano("X_FLAG", False) is True


@pytest.mark.parametrize("texto", ["false", "FALSE", " False ", "0", "no", "off"])
def test_valores_falsos(monkeypatch, texto):
    monkeypatch.setenv("X_FLAG", texto)
    assert _booleano("X_FLAG", True) is False


def test_sin_definir_o_vacio_se_usa_el_defecto(monkeypatch):
    monkeypatch.delenv("X_FLAG", raising=False)
    assert _booleano("X_FLAG", True) is True and _booleano("X_FLAG", False) is False
    monkeypatch.setenv("X_FLAG", "  ")
    assert _booleano("X_FLAG", True) is True


@pytest.mark.parametrize("texto", ["tru", "2", "verdadero", "ture", "falso", "nope"])
def test_un_valor_ambiguo_impide_arrancar_en_vez_de_interpretarse(monkeypatch, texto):
    """Antes BINANCE_TESTNET='tru' (un typo) se leía como falso y operaba con dinero real."""
    monkeypatch.setenv("X_FLAG", texto)
    with pytest.raises(RuntimeError, match="X_FLAG"):
        _booleano("X_FLAG", True)


def test_operar_con_dinero_real_exige_confirmacion_explicita():
    with pytest.raises(RuntimeError, match="BINANCE_ALLOW_LIVE"):
        _cfg(BINANCE_TESTNET=False, BINANCE_ALLOW_LIVE=False).validate()
    _cfg(BINANCE_TESTNET=False, BINANCE_ALLOW_LIVE=True).validate()          # confirmado: se permite
    _cfg(BINANCE_TESTNET=True, BINANCE_ALLOW_LIVE=False).validate()          # el caso normal


def test_por_defecto_se_usa_testnet_y_sin_permiso_de_dinero_real():
    assert config.BINANCE_TESTNET is True and config.BINANCE_ALLOW_LIVE is False


@pytest.mark.parametrize("campo", ["MARKET_RATE_LIMIT", "REPORT_RATE_LIMIT", "WATCHLIST_MAX_ITEMS"])
@pytest.mark.parametrize("valor", [0, -1])
def test_los_limites_nuevos_deben_ser_positivos(campo, valor):
    with pytest.raises(RuntimeError, match=campo):
        _cfg(**{campo: valor}).validate()


def test_valores_por_defecto_de_los_limites_nuevos():
    assert (config.MARKET_RATE_LIMIT, config.REPORT_RATE_LIMIT, config.WATCHLIST_MAX_ITEMS) == (30, 10, 50)


# ====================================================================== caché acotado

def test_el_cache_nunca_supera_su_tope():
    c = SimpleCache(max_entradas=5)
    for i in range(50):
        c.set(f"k{i}", i, ttl_seconds=60)
        assert len(c.cache) <= 5


def test_al_llenarse_descarta_primero_lo_vencido_y_despues_lo_mas_antiguo():
    c = SimpleCache(max_entradas=3)
    c.set("viejo_vencido", 1, ttl_seconds=60)
    c.cache["viejo_vencido"] = (1, datetime.now() - timedelta(seconds=1))      # ya venció
    c.set("b", 2, ttl_seconds=60)
    c.set("c", 3, ttl_seconds=60)
    c.set("d", 4, ttl_seconds=60)                                               # lleno: sale el vencido, no "b"
    assert set(c.cache) == {"b", "c", "d"}
    c.set("e", 5, ttl_seconds=60)                                               # nada vencido: sale el más antiguo
    assert set(c.cache) == {"c", "d", "e"}


def test_reescribir_una_clave_no_ocupa_otro_lugar_y_la_vuelve_la_mas_reciente():
    c = SimpleCache(max_entradas=3)
    for k in "abc":
        c.set(k, k, ttl_seconds=60)
    c.set("a", "nuevo", ttl_seconds=60)                  # "a" pasa a ser la más reciente
    c.set("d", "d", ttl_seconds=60)                      # sale "b", la más antigua
    assert set(c.cache) == {"c", "a", "d"} and c.get("a") == "nuevo"


def test_get_delete_clear_y_stats():
    c = SimpleCache(max_entradas=10)
    c.set("a", 1, ttl_seconds=60)
    c.cache["v"] = (2, datetime.now() - timedelta(seconds=1))
    assert c.get("a") == 1 and c.get("v") is None and "v" not in c.cache and c.get("no") is None
    c.delete("a"); c.delete("a")                          # borrar dos veces no falla
    c.set("x", 1, 60)
    assert c.stats()["entradas"] == 1
    c.clear()
    assert c.cache == {}


def test_el_tope_por_defecto_es_razonable_y_el_cache_global_lo_usa():
    from app.services.cache import cache
    assert MAX_ENTRADAS == 5000 and cache.max_entradas == MAX_ENTRADAS


def test_escrituras_desde_varios_hilos_no_superan_el_tope_ni_fallan():
    c = SimpleCache(max_entradas=50)
    errores = []

    def escribir(n):
        try:
            for i in range(300):
                c.set(f"{n}-{i}", i, ttl_seconds=60)
        except Exception as e:      # pragma: no cover
            errores.append(e)

    hilos = [threading.Thread(target=escribir, args=(n,)) for n in range(8)]
    [h.start() for h in hilos]; [h.join() for h in hilos]
    assert errores == [] and len(c.cache) <= 50


# ====================================================================== validación de identificadores

def test_lista_de_coin_ids_normaliza_ordena_y_quita_repetidos():
    assert validacion.lista_de_coin_ids(" Ethereum, bitcoin ,bitcoin,,") == ["bitcoin", "ethereum"]


@pytest.mark.parametrize("texto", ["", " , ,", "bit coin", "bitcoin;ethereum", "../x", "bitcoin,$$", "-bitcoin", "a" * 65])
def test_lista_de_coin_ids_rechaza_basura(texto):
    with pytest.raises(ValueError):
        validacion.lista_de_coin_ids(texto)


def test_lista_de_coin_ids_limita_la_cantidad():
    validacion.lista_de_coin_ids(",".join(f"coin{i}" for i in range(20)))
    with pytest.raises(ValueError):
        validacion.lista_de_coin_ids(",".join(f"coin{i}" for i in range(21)))


# ====================================================================== rutas de mercado: validación y límite

@pytest.fixture
def mercado(monkeypatch):
    """Servicios externos simulados; `llamadas` cuenta cuántas veces se habría tocado la red."""
    estado = {"llamadas": 0, "ultimos": None}

    async def un_precio(coin_id, moneda="usd"):
        estado["llamadas"] += 1
        return {coin_id: {moneda: 1.0}}

    async def varios(coin_ids, moneda="usd"):
        estado["llamadas"] += 1
        estado["ultimos"] = list(coin_ids)
        return {c: {moneda: 1.0} for c in coin_ids}

    async def buscar(query):
        estado["llamadas"] += 1
        return {"coins": [{"id": "bitcoin"}]}

    monkeypatch.setattr("app.routers.precios.obtener_precio", un_precio)
    monkeypatch.setattr("app.routers.precios.obtener_precios_multiples", varios)
    monkeypatch.setattr("app.routers.precios.buscar_moneda", buscar)
    from app.services.binance_service import binance_service
    monkeypatch.setattr(binance_service, "ping", lambda: True)
    monkeypatch.setattr(binance_service, "get_ticker", lambda s: {"symbol": s, "price": "1"}, raising=False)
    monkeypatch.setattr(binance_service, "get_all_tickers", lambda: [], raising=False)
    from app.services.cache import cache
    cache.clear()
    return estado


@pytest.mark.parametrize("ruta", [
    "/precios/BITCOIN", "/precios/" + "a" * 65, "/precios/bit.coin", "/precios/bitcoin?moneda=usd1",
    "/precios/bitcoin?moneda=U", "/precios/bitcoin?moneda=usdusdusdusd",
])
def test_precio_individual_rechaza_identificadores_invalidos_sin_tocar_la_red(client, mercado, ruta):
    assert client.get(ruta).status_code == 422
    assert mercado["llamadas"] == 0


def test_precio_individual_valido_funciona(client, mercado):
    r = client.get("/precios/bitcoin?moneda=eur")
    assert r.status_code == 200 and mercado["llamadas"] == 1


@pytest.mark.parametrize("consulta", [
    "coins=", "coins=,,", "coins=bit coin", "coins=bitcoin,$$", "coins=" + ",".join(f"c{i}" for i in range(21)),
    "coins=" + "a" * 1001, "coins=bitcoin&moneda=1", "moneda=usd",
])
def test_precios_multiples_rechaza_entradas_invalidas_sin_tocar_la_red(client, mercado, consulta):
    assert client.get(f"/precios/multiples?{consulta}").status_code == 422
    assert mercado["llamadas"] == 0


def test_precios_multiples_normaliza_la_lista_antes_de_consultar(client, mercado):
    r = client.get("/precios/multiples?coins=Ethereum,bitcoin,bitcoin")
    assert r.status_code == 200 and mercado["ultimos"] == ["bitcoin", "ethereum"]


@pytest.mark.parametrize("q", ["a" * 51, "%3Cscript%3E", "a%2Fb", "a%3Fb%3Dc", "x%00y"])
def test_buscar_rechaza_consultas_invalidas(client, mercado, q):
    assert client.get(f"/precios/buscar/{q}").status_code in (404, 422)
    assert mercado["llamadas"] == 0


def test_buscar_acepta_texto_normal(client, mercado):
    assert client.get("/precios/buscar/wrapped bitcoin").status_code == 200


@pytest.mark.parametrize("ruta", ["/binance/price/BTC!!", "/binance/price/" + "A" * 21, "/binance/symbol-info/BT-C",
                                  "/binance/symbol-info/" + "A" * 21, "/binance/price/B"])
def test_los_simbolos_de_binance_se_validan(client, mercado, ruta):
    assert client.get(ruta).status_code == 422


def test_ping_informa_si_es_testnet_segun_la_configuracion(client, mercado, monkeypatch):
    assert client.get("/binance/ping").json()["testnet"] is True
    monkeypatch.setattr(config, "BINANCE_TESTNET", False)
    assert client.get("/binance/ping").json()["testnet"] is False


def test_las_rutas_de_mercado_estan_limitadas_por_ip(client, mercado, monkeypatch):
    monkeypatch.setattr(config, "MARKET_RATE_LIMIT", 3)
    estados = [client.get("/precios/bitcoin").status_code for _ in range(5)]
    assert estados == [200, 200, 200, 429, 429]
    r = client.get("/precios/bitcoin")
    assert int(r.headers["Retry-After"]) >= 1 and "Demasiadas" in r.json()["detail"]


def test_el_limite_de_mercado_se_comparte_entre_rutas_y_es_por_ip(client, mercado, monkeypatch):
    monkeypatch.setattr(config, "MARKET_RATE_LIMIT", 3)
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    a, b = {"X-Forwarded-For": "203.0.113.1"}, {"X-Forwarded-For": "203.0.113.2"}
    assert client.get("/precios/bitcoin", headers=a).status_code == 200
    assert client.get("/precios/multiples?coins=bitcoin", headers=a).status_code == 200
    assert client.get("/binance/ping", headers=a).status_code == 200
    assert client.get("/precios/buscar/btc", headers=a).status_code == 429       # el cupo de A se agotó entre rutas
    assert client.get("/precios/bitcoin", headers=b).status_code == 200          # B no se ve afectada


def test_el_limite_de_mercado_no_afecta_a_otras_rutas(client, mercado, monkeypatch):
    monkeypatch.setattr(config, "MARKET_RATE_LIMIT", 1)
    client.get("/precios/bitcoin"); client.get("/precios/bitcoin")
    assert client.get("/health").status_code == 200 and client.get("/").status_code == 200


def test_un_fallo_del_limitador_no_bloquea_las_rutas_de_mercado(client, mercado, monkeypatch):
    from app.services.ratelimit import limitador

    def roto(*a, **k):
        raise RuntimeError("redis caído")
    monkeypatch.setattr(limitador, "golpear", roto)
    monkeypatch.setattr("app.middleware.RateLimitMiddleware._evaluar", lambda *a, **k: (None, None))
    assert client.get("/precios/bitcoin").status_code == 200


# ====================================================================== informes PDF

def test_los_pdf_estan_limitados_por_usuario(client, usuario_a, usuario_b, monkeypatch):
    monkeypatch.setattr(config, "REPORT_RATE_LIMIT", 2)
    pdfs = [client.get("/dashboard/reporte/pdf", headers=usuario_a["headers"]) for _ in range(3)]
    assert [r.status_code for r in pdfs] == [200, 200, 429]
    assert pdfs[0].content.startswith(b"%PDF") and "Retry-After" in pdfs[2].headers
    assert client.get("/dashboard/reporte/pdf", headers=usuario_b["headers"]).status_code == 200


def test_el_pdf_sigue_exigiendo_login(client):
    assert client.get("/dashboard/reporte/pdf").status_code in (401, 403)


# ====================================================================== watchlist

def _agregar(client, headers, coin="bitcoin", precio=10):
    return client.post("/analisis/watchlist", headers=headers, json={"coin_id": coin, "precio_alerta": precio})


def test_la_watchlist_tiene_un_tope_por_usuario(client, usuario_a, usuario_b, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_MAX_ITEMS", 2)
    assert [_agregar(client, usuario_a["headers"], f"coin{i}").status_code for i in range(3)] == [201, 201, 409]
    assert "máximo 2" in _agregar(client, usuario_a["headers"], "otra").json()["detail"]
    assert _agregar(client, usuario_b["headers"], "coin0").status_code == 201        # el tope es por usuario
    assert len(client.get("/analisis/watchlist", headers=usuario_a["headers"]).json()) == 2


def test_altas_simultaneas_no_superan_el_tope_de_la_watchlist(db_limpia):
    uid = UserDAO().crear_usuario_db("ana", "ana@example.com", "x")

    def alta(i):
        try:
            WatchlistDAO().agregar_db(uid, f"coin{i}", 1, max_items=3)
            return True
        except WatchlistLlena:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        resultados = list(pool.map(alta, range(20)))
    assert sum(resultados) == 3 and len(WatchlistDAO().obtener_por_usuario_db(uid)) == 3


def test_el_dao_sin_tope_sigue_funcionando_como_antes(db_limpia):
    uid = UserDAO().crear_usuario_db("ana", "ana@example.com", "x")
    for i in range(60):
        WatchlistDAO().agregar_db(uid, f"c{i}", 1)
    assert len(WatchlistDAO().obtener_por_usuario_db(uid)) == 60


def test_el_coin_id_de_la_watchlist_se_normaliza_y_se_valida(client, auth_headers):
    r = _agregar(client, auth_headers, " Bitcoin ")
    assert r.status_code == 201 and r.json()["coin_id"] == "bitcoin"
    for malo in ("bit coin", "../x", "a" * 65, "bitcoin;drop", "", "ñandú"):
        assert _agregar(client, auth_headers, malo).status_code == 422, malo
