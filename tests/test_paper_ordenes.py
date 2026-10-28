# tests/test_paper_ordenes.py
"""Sprint 8: órdenes pendientes LIMIT y STOP del paper trading y su motor de ejecución."""
import asyncio
import concurrent.futures
from decimal import Decimal as D

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.config import config
from app.dao.PaperDAO import PaperDAO
from app.dao.UserDAO import UserDAO
from app.database import engine
from app.services import paper_matching, paper_trading as pt
from tests.conftest import alembic_config

COM, SLIP = D("0.1"), D("0.05")


# ====================================================================== lógica pura

@pytest.mark.parametrize("tipo,side,mercado,orden,espera", [
    ("LIMIT", "BUY", 99, 100, True), ("LIMIT", "BUY", 100, 100, True), ("LIMIT", "BUY", 101, 100, False),
    ("LIMIT", "SELL", 101, 100, True), ("LIMIT", "SELL", 100, 100, True), ("LIMIT", "SELL", 99, 100, False),
    ("STOP", "SELL", 99, 100, True), ("STOP", "SELL", 100, 100, True), ("STOP", "SELL", 101, 100, False),
    ("STOP", "BUY", 101, 100, True), ("STOP", "BUY", 100, 100, True), ("STOP", "BUY", 99, 100, False),
])
def test_cuando_se_dispara_cada_tipo(tipo, side, mercado, orden, espera):
    assert pt.se_dispara(tipo, side, D(mercado), D(orden)) is espera


def test_un_tipo_desconocido_se_rechaza():
    with pytest.raises(pt.PaperError):
        pt.se_dispara("OCO", "BUY", D(1), D(1))


def test_limit_se_rellena_al_precio_limite_sin_slippage_y_stop_a_mercado_con_slippage():
    assert pt.parametros_de_relleno("LIMIT", D(90), D(100), SLIP) == (D(100), D(0))
    assert pt.parametros_de_relleno("STOP", D(90), D(100), SLIP) == (D(90), SLIP)


def test_un_limit_de_compra_nunca_paga_mas_que_su_limite():
    ref, sl = pt.parametros_de_relleno("LIMIT", D(50), D(100), SLIP)
    r = pt.calcular_compra(D(10000), D(1), ref, COM, sl)
    assert r["precio"] == D(100)                       # no se ejecuta al mercado (50) ni peor que el límite


@pytest.mark.parametrize("side,mercado,stop,valido", [
    ("SELL", 90, 100, False), ("SELL", 100, 100, False), ("SELL", 100, 95, True),
    ("BUY", 110, 100, False), ("BUY", 100, 100, False), ("BUY", 100, 105, True),
])
def test_un_stop_ya_disparado_no_se_puede_crear(side, mercado, stop, valido):
    if valido:
        pt.validar_stop_al_crear(side, D(mercado), D(stop))
    else:
        with pytest.raises(pt.PaperError):
            pt.validar_stop_al_crear(side, D(mercado), D(stop))


# ====================================================================== API

@pytest.fixture
def mercado(monkeypatch):
    estado = {"precios": {"bitcoin": 100.0, "ethereum": 50.0}, "caido": False}

    async def un_precio(coin_id, moneda="usd"):
        if estado["caido"]:
            return None
        return {coin_id: {"usd": estado["precios"][coin_id]}} if coin_id in estado["precios"] else {}

    async def varios(coin_ids, moneda="usd"):
        if estado["caido"]:
            return None
        return {c: {"usd": estado["precios"][c]} for c in coin_ids if c in estado["precios"]}

    monkeypatch.setattr(pt, "obtener_precio", un_precio)
    monkeypatch.setattr("app.services.coingecko.obtener_precios_multiples", varios)
    for campo, valor in (("PAPER_COMMISSION_PCT", COM), ("PAPER_SLIPPAGE_PCT", SLIP), ("PAPER_INITIAL_BALANCE", D(10000))):
        monkeypatch.setattr(config, campo, valor)
    return estado


def _pend(client, headers, side="BUY", tipo="LIMIT", precio=90, cantidad=1, coin="bitcoin", **extra):
    return client.post("/paper/ordenes", headers=headers,
                       json={"coin_id": coin, "side": side, "tipo": tipo, "cantidad": cantidad, "precio": precio, **extra})


def _ciclo():
    return asyncio.run(paper_matching.un_ciclo())


def _saldo(client, headers):
    return client.get("/paper/billetera", headers=headers).json()["saldo_usdt"]


def test_las_rutas_de_ordenes_exigen_login(client, mercado):
    for metodo, ruta in (("POST", "/paper/ordenes"), ("GET", "/paper/ordenes"), ("DELETE", "/paper/ordenes/1")):
        assert client.request(metodo, ruta).status_code in (401, 403)


def test_crear_una_orden_limit_no_ejecuta_nada_todavia(client, mercado, auth_headers):
    r = _pend(client, auth_headers, "BUY", "LIMIT", 90)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "ABIERTA" and r.json()["precio"] == 90 and r.json()["trade_id"] is None
    assert _saldo(client, auth_headers) == 10000
    assert client.get("/paper/historial", headers=auth_headers).json() == []


def test_limit_de_compra_se_ejecuta_cuando_el_precio_baja_y_al_precio_limite(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 90)
    assert _ciclo()["ejecutadas"] == 0                      # mercado 100 > 90: no se dispara
    mercado["precios"]["bitcoin"] = 85.0
    assert _ciclo()["ejecutadas"] == 1
    o = client.get("/paper/ordenes", headers=auth_headers).json()[0]
    assert o["estado"] == "EJECUTADA" and o["trade_id"] is not None and o["cerrada_en"]
    t = client.get("/paper/historial", headers=auth_headers).json()[0]
    assert t["id"] == o["trade_id"] and t["precio"] == 90 and t["comision"] == 0.09      # al límite, no a 85
    assert _saldo(client, auth_headers) == pytest.approx(10000 - 90.09)
    assert client.get("/paper/posiciones", headers=auth_headers).json()["posiciones"][0]["cantidad"] == 1


def test_una_orden_ejecutada_no_se_ejecuta_dos_veces(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    assert _ciclo()["ejecutadas"] == 1
    assert _ciclo()["ejecutadas"] == 0
    assert len(client.get("/paper/historial", headers=auth_headers).json()) == 1


def test_stop_loss_vende_cuando_el_precio_cae(client, mercado, auth_headers):
    client.post("/paper/orden", headers=auth_headers, json={"coin_id": "bitcoin", "side": "BUY", "cantidad": 2})
    assert _pend(client, auth_headers, "SELL", "STOP", 95, cantidad=2).status_code == 201
    assert _ciclo()["ejecutadas"] == 0
    mercado["precios"]["bitcoin"] = 90.0
    assert _ciclo()["ejecutadas"] == 1
    t = client.get("/paper/historial", headers=auth_headers).json()[0]
    assert t["side"] == "SELL" and t["precio"] == 89.955          # mercado 90 con slippage en contra
    assert t["pnl_realizado"] < 0
    assert client.get("/paper/posiciones", headers=auth_headers).json()["posiciones"] == []


def test_stop_de_compra_entra_por_ruptura(client, mercado, auth_headers):
    assert _pend(client, auth_headers, "BUY", "STOP", 105).status_code == 201
    mercado["precios"]["bitcoin"] = 106.0
    assert _ciclo()["ejecutadas"] == 1
    assert client.get("/paper/historial", headers=auth_headers).json()[0]["precio"] == 106.053   # 106 + 0,05 %


def test_limit_de_venta_toma_ganancias(client, mercado, auth_headers):
    client.post("/paper/orden", headers=auth_headers, json={"coin_id": "bitcoin", "side": "BUY", "cantidad": 1})
    _pend(client, auth_headers, "SELL", "LIMIT", 120)
    mercado["precios"]["bitcoin"] = 125.0
    assert _ciclo()["ejecutadas"] == 1
    t = client.get("/paper/historial", headers=auth_headers).json()[0]
    assert t["precio"] == 120 and t["pnl_realizado"] > 0


def test_un_stop_ya_disparado_se_rechaza_al_crearlo(client, mercado, auth_headers):
    r = _pend(client, auth_headers, "SELL", "STOP", 100)           # mercado = 100: ya está disparado
    assert r.status_code == 422 and "debe fijarse" in r.json()["detail"]
    assert _pend(client, auth_headers, "BUY", "STOP", 99).status_code == 422
    assert client.get("/paper/ordenes", headers=auth_headers).json() == []


def test_sin_saldo_al_dispararse_la_orden_queda_rechazada_con_motivo(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 90, cantidad=200)        # vale 18.000 > 10.000
    mercado["precios"]["bitcoin"] = 80.0
    assert _ciclo() == {"ejecutadas": 0, "rechazadas": 1, "errores": 0}
    o = client.get("/paper/ordenes", headers=auth_headers).json()[0]
    assert o["estado"] == "RECHAZADA" and "Saldo insuficiente" in o["motivo"]
    assert _saldo(client, auth_headers) == 10000
    assert _ciclo()["rechazadas"] == 0                                    # no se reintenta cada ciclo


def test_sin_posicion_al_dispararse_la_venta_queda_rechazada(client, mercado, auth_headers):
    _pend(client, auth_headers, "SELL", "LIMIT", 120)
    mercado["precios"]["bitcoin"] = 130.0
    assert _ciclo()["rechazadas"] == 1
    assert "solo tienes" in client.get("/paper/ordenes", headers=auth_headers).json()[0]["motivo"]


def test_el_rechazo_de_una_orden_no_impide_ejecutar_las_demas(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 120, cantidad=200)      # se rechazará (sin saldo)
    _pend(client, auth_headers, "BUY", "LIMIT", 120, cantidad=1)
    assert _ciclo() == {"ejecutadas": 1, "rechazadas": 1, "errores": 0}


def test_sin_precio_el_ciclo_no_ejecuta_ni_rechaza_nada(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    mercado["caido"] = True
    assert _ciclo() == {"ejecutadas": 0, "rechazadas": 0, "errores": 0}
    assert client.get("/paper/ordenes?estado=ABIERTA", headers=auth_headers).json()[0]["estado"] == "ABIERTA"
    mercado["caido"] = False
    assert _ciclo()["ejecutadas"] == 1


def test_el_ciclo_ignora_monedas_sin_precio_pero_procesa_las_demas(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 120, coin="bitcoin")
    _pend(client, auth_headers, "BUY", "LIMIT", 60, coin="ethereum")
    del mercado["precios"]["ethereum"]
    assert _ciclo()["ejecutadas"] == 1


def test_cancelar(client, mercado, auth_headers):
    oid = _pend(client, auth_headers).json()["id"]
    r = client.delete(f"/paper/ordenes/{oid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    mercado["precios"]["bitcoin"] = 50.0
    assert _ciclo()["ejecutadas"] == 0                                    # cancelada: no se ejecuta
    assert client.delete(f"/paper/ordenes/{oid}", headers=auth_headers).status_code == 409
    assert client.delete("/paper/ordenes/999999", headers=auth_headers).status_code == 404
    assert client.delete("/paper/ordenes/99999999999999", headers=auth_headers).status_code == 422
    assert client.delete("/paper/ordenes/0", headers=auth_headers).status_code == 422


def test_no_se_puede_cancelar_una_orden_ya_ejecutada(client, mercado, auth_headers):
    oid = _pend(client, auth_headers, "BUY", "LIMIT", 120).json()["id"]
    _ciclo()
    assert client.delete(f"/paper/ordenes/{oid}", headers=auth_headers).status_code == 409


def test_aislamiento_entre_usuarios(client, mercado, usuario_a, usuario_b):
    oid = _pend(client, usuario_a["headers"]).json()["id"]
    assert client.get("/paper/ordenes", headers=usuario_b["headers"]).json() == []
    assert client.delete(f"/paper/ordenes/{oid}", headers=usuario_b["headers"]).status_code == 404
    assert client.get("/paper/ordenes", headers=usuario_a["headers"]).json()[0]["estado"] == "ABIERTA"


def test_filtro_por_estado_y_paginacion(client, mercado, auth_headers):
    ids = [_pend(client, auth_headers, precio=90 - i).json()["id"] for i in range(4)]
    client.delete(f"/paper/ordenes/{ids[0]}", headers=auth_headers)
    assert [o["id"] for o in client.get("/paper/ordenes?estado=CANCELADA", headers=auth_headers).json()] == [ids[0]]
    assert len(client.get("/paper/ordenes?estado=ABIERTA", headers=auth_headers).json()) == 3
    assert [o["id"] for o in client.get("/paper/ordenes?skip=1&limit=2", headers=auth_headers).json()] == [ids[2], ids[1]]
    for q in ("estado=otra", "limit=0", "limit=101", "skip=-1"):
        assert client.get(f"/paper/ordenes?{q}", headers=auth_headers).status_code == 422


def test_idempotencia_de_ordenes_pendientes(client, mercado, auth_headers):
    a = _pend(client, auth_headers, client_order_id="p-1")
    b = _pend(client, auth_headers, client_order_id="p-1")
    assert (a.status_code, b.status_code) == (201, 200) and b.json()["repetida"] and b.json()["id"] == a.json()["id"]
    assert _pend(client, auth_headers, precio=80, client_order_id="p-1").status_code == 409
    assert len(client.get("/paper/ordenes", headers=auth_headers).json()) == 1


def test_tope_de_ordenes_abiertas(client, mercado, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "PAPER_MAX_OPEN_ORDERS", 2)
    assert [_pend(client, auth_headers, precio=90 - i).status_code for i in range(3)] == [201, 201, 409]
    oid = client.get("/paper/ordenes", headers=auth_headers).json()[0]["id"]
    client.delete(f"/paper/ordenes/{oid}", headers=auth_headers)           # al cancelar se libera cupo
    assert _pend(client, auth_headers, precio=70).status_code == 201


@pytest.mark.parametrize("cuerpo", [
    {"tipo": "MARKET"}, {"tipo": "limit"}, {"precio": 0}, {"precio": -1}, {"precio": "NaN"}, {"precio": "0.000000001"},
    {"precio": 10**12}, {"cantidad": 0}, {"side": "SHORT"}, {"coin_id": "../x"}, {"client_order_id": "a b"},
])
def test_entradas_invalidas_dan_422(client, mercado, auth_headers, cuerpo):
    base = {"coin_id": "bitcoin", "side": "BUY", "tipo": "LIMIT", "cantidad": 1, "precio": 90}
    assert client.post("/paper/ordenes", headers=auth_headers, json={**base, **cuerpo}).status_code == 422


def test_valor_total_excesivo_da_422(client, mercado, auth_headers):
    assert _pend(client, auth_headers, precio=10**8, cantidad=100).status_code == 422


def test_moneda_desconocida_404_y_sin_precio_503(client, mercado, auth_headers):
    assert _pend(client, auth_headers, coin="inventada").status_code == 404
    mercado["caido"] = True
    assert _pend(client, auth_headers).status_code == 503
    mercado["caido"] = False
    assert client.get("/paper/ordenes", headers=auth_headers).json() == []


def test_crear_ordenes_pendientes_gasta_el_cupo_de_ordenes(client, mercado, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "PAPER_ORDERS_PER_MINUTE", 2)
    assert [_pend(client, auth_headers, precio=90 - i).status_code for i in range(3)] == [201, 201, 429]


def test_reiniciar_cancela_las_ordenes_pendientes(client, mercado, auth_headers):
    _pend(client, auth_headers)
    client.post("/paper/reiniciar", headers=auth_headers)
    assert client.get("/paper/ordenes", headers=auth_headers).json() == []
    mercado["precios"]["bitcoin"] = 10.0
    assert _ciclo()["ejecutadas"] == 0


def test_la_orden_ejecutada_por_el_motor_respeta_el_idempotente_de_mercado(client, mercado, auth_headers):
    """El trade creado por el motor no lleva client_order_id: no choca con los de las órdenes de mercado."""
    _pend(client, auth_headers, "BUY", "LIMIT", 120, client_order_id="m-1")
    _ciclo()
    assert client.post("/paper/orden", headers=auth_headers,
                       json={"coin_id": "bitcoin", "side": "BUY", "cantidad": 1, "client_order_id": "m-1"}).status_code == 201


# ====================================================================== bucle y arranque

def test_el_bucle_sigue_vivo_aunque_un_ciclo_falle(monkeypatch):
    llamadas = []

    async def ciclo(dao=None):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise RuntimeError("fallo puntual")
        return {}

    monkeypatch.setattr(paper_matching, "un_ciclo", ciclo)
    monkeypatch.setattr(config, "PAPER_MATCH_INTERVAL_SECONDS", 0)

    async def correr():
        tarea = asyncio.create_task(paper_matching.bucle_de_casamiento())
        await asyncio.sleep(0.2)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(correr())
    assert len(llamadas) >= 2


def test_el_motor_arranca_con_la_app_y_se_puede_desactivar(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app):
        assert getattr(app.state, "tarea_paper", None) is not None
    if hasattr(app.state, "tarea_paper"):
        del app.state.tarea_paper
    monkeypatch.setattr(config, "PAPER_MATCHING_ENABLED", False)
    with TestClient(app):
        assert getattr(app.state, "tarea_paper", None) is None


# ====================================================================== concurrencia y base de datos

def _usuario(nombre="ana"):
    return UserDAO().crear_usuario_db(nombre, f"{nombre}@example.com", "x")


def _pendiente(uid, side="BUY", tipo="LIMIT", cantidad=D(1), precio=D(100), coin="bitcoin", cid=None):
    return PaperDAO().crear_pendiente(uid, coin, side, tipo, cantidad, precio, D(1000), 50, cid)


def _procesar(precios, saldo=D(1000)):
    return PaperDAO().procesar_pendientes(precios, COM, SLIP, saldo)


def test_varios_motores_a_la_vez_ejecutan_cada_orden_una_sola_vez(db_limpia):
    uid = _usuario()
    for _ in range(6):
        _pendiente(uid, cantidad=D(1), precio=D(100))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        resumenes = list(pool.map(lambda _: _procesar({"bitcoin": D(90)}), range(6)))
    assert sum(r["ejecutadas"] for r in resumenes) + sum(r["rechazadas"] for r in resumenes) == 6
    historial = PaperDAO().obtener_historial(uid)
    ejecutadas = PaperDAO().listar_pendientes(uid, "EJECUTADA")
    assert len(historial) == len(ejecutadas) == sum(r["ejecutadas"] for r in resumenes)
    assert len({o["trade_id"] for o in ejecutadas}) == len(ejecutadas)           # ningún trade compartido
    assert PaperDAO().obtener_billetera(uid, D(1000))["balance_usdt"] >= 0


def test_el_motor_y_las_ordenes_de_mercado_a_la_vez_no_gastan_dos_veces_el_saldo(db_limpia):
    """Saldo 1000, compras de ~100,1: caben 9 entre órdenes de mercado y pendientes, nunca más."""
    uid = _usuario()
    for _ in range(10):
        _pendiente(uid, precio=D(100))

    def mercado(_):
        try:
            PaperDAO().ejecutar_orden(uid, "bitcoin", "BUY", D(1), D(100), D(1000), COM, SLIP)
        except pt.SaldoInsuficiente:
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        trabajos = [pool.submit(_procesar, {"bitcoin": D(100)}) for _ in range(3)]
        trabajos += [pool.submit(mercado, i) for i in range(10)]
        for t in trabajos:
            t.result()
    cuenta = PaperDAO().obtener_billetera(uid, D(1000))
    assert cuenta["balance_usdt"] >= 0
    posicion = PaperDAO().obtener_posiciones(uid)[0]["cantidad"]
    assert posicion == len(PaperDAO().obtener_historial(uid))          # cada trade es 1 unidad: la cuenta cuadra


def test_cancelar_y_ejecutar_a_la_vez_nunca_dan_ambos(db_limpia):
    for _ in range(15):
        uid = _usuario(f"u{_}")
        orden = _pendiente(uid)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_procesar, {"bitcoin": D(90)})
            f2 = pool.submit(lambda: _cancelar(uid, orden["id"]))
            f1.result(), f2.result()
        final = PaperDAO().listar_pendientes(uid)[0]
        trades = len(PaperDAO().obtener_historial(uid))
        assert (final["estado"], trades) in (("EJECUTADA", 1), ("CANCELADA", 0)), (final["estado"], trades)


def _cancelar(uid, oid):
    try:
        return PaperDAO().cancelar_pendiente(uid, oid)
    except pt.OrdenNoAbierta:
        return None


def test_reiniciar_y_el_motor_a_la_vez_no_se_bloquean_entre_si(db_limpia):
    uid = _usuario()
    for _ in range(5):
        _pendiente(uid)

    def reiniciar():
        for _ in range(5):
            PaperDAO().reiniciar(uid, D(1000))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        trabajos = [pool.submit(reiniciar)] + [pool.submit(_procesar, {"bitcoin": D(90)}) for _ in range(3)]
        for t in trabajos:
            t.result(timeout=30)                       # un interbloqueo aquí lanzaría una excepción de PostgreSQL


def test_un_error_de_base_en_una_orden_no_detiene_a_las_demas(db_limpia, monkeypatch):
    uid = _usuario()
    _pendiente(uid)
    _pendiente(uid)
    original = PaperDAO._aplicar
    llamadas = []

    def a_veces_falla(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise RuntimeError("fallo inesperado")
        return original(*a, **k)

    monkeypatch.setattr(PaperDAO, "_aplicar", staticmethod(a_veces_falla))
    r = _procesar({"bitcoin": D(90)})
    assert r == {"ejecutadas": 1, "rechazadas": 0, "errores": 1}
    estados = sorted(o["estado"] for o in PaperDAO().listar_pendientes(uid))
    assert estados == ["ABIERTA", "EJECUTADA"]                         # la que falló sigue abierta para reintentar


@pytest.mark.parametrize("sql", [
    "UPDATE paper_orders SET estado = 'FANTASMA'",
    "UPDATE paper_orders SET tipo = 'MARKET'",
    "UPDATE paper_orders SET side = 'SHORT'",
    "UPDATE paper_orders SET precio = 0",
    "UPDATE paper_orders SET cantidad = -1",
])
def test_la_base_rechaza_ordenes_imposibles(db_limpia, sql):
    _pendiente(_usuario())
    with pytest.raises(Exception):
        with engine.begin() as c:
            c.execute(text(sql))


def test_borrar_un_usuario_borra_sus_ordenes_y_borrar_un_trade_no_borra_la_orden(db_limpia):
    uid = _usuario()
    _pendiente(uid)
    _procesar({"bitcoin": D(90)})
    with engine.begin() as c:
        c.execute(text("DELETE FROM paper_trades"))
        assert c.execute(text("SELECT count(*), max(trade_id) FROM paper_orders")).one() == (1, None)
        c.execute(text("DELETE FROM usuarios WHERE id = :i"), {"i": uid})
        assert c.execute(text("SELECT count(*) FROM paper_orders")).scalar_one() == 0


def test_migracion_0005_sube_y_baja_sin_tocar_el_resto():
    uid = _usuario("persistente")
    try:
        command.downgrade(alembic_config(), "0004")
        assert "paper_orders" not in inspect(engine).get_table_names()
        assert {"paper_wallet", "paper_trades"} <= set(inspect(engine).get_table_names())
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM usuarios WHERE id = :i"), {"i": uid}).scalar_one() == 1
    finally:
        command.upgrade(alembic_config(), "head")
        with engine.begin() as c:
            c.execute(text("TRUNCATE usuarios RESTART IDENTITY CASCADE"))
    assert "paper_orders" in inspect(engine).get_table_names()
