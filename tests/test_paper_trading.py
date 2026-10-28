# tests/test_paper_trading.py
"""Sprint 6: paper trading (dinero simulado a precios reales)."""
import concurrent.futures
from decimal import Decimal as D

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.config import config
from app.dao.PaperDAO import PaperDAO
from app.database import engine
from app.dao.UserDAO import UserDAO
from app.services import paper_trading as pt
from tests.conftest import alembic_config, crear_usuario_y_login

COM, SLIP = D("0.1"), D("0.05")


# ====================================================================== lógica pura

def test_compra_aplica_slippage_en_contra_y_comision():
    r = pt.calcular_compra(D(10000), D(1), D(100), COM, SLIP)
    assert r["precio"] == D("100.05")
    assert r["valor"] == D("100.05")
    assert r["comision"] == D("0.10005")
    assert r["saldo"] == D(10000) - D("100.15005")
    assert r["pos_cantidad"] == D(1) and r["pos_precio_medio"] == D("100.15005")   # el medio incluye comisión


def test_venta_aplica_slippage_en_contra_y_calcula_pnl_exacto():
    compra = pt.calcular_compra(D(10000), D(1), D(100), COM, SLIP)
    v = pt.calcular_venta(D(1), D(110), COM, SLIP, compra["pos_cantidad"], compra["pos_precio_medio"], compra["saldo"])
    assert v["precio"] == D("109.945")
    assert v["comision"] == D("0.109945")
    assert v["pnl_realizado"] == D("109.835055") - D("100.15005")
    # el saldo final = inicial + pnl realizado: la contabilidad cuadra al céntimo
    assert v["saldo"] == D(10000) + v["pnl_realizado"]
    assert v["pos_cantidad"] == 0


def test_comprar_dos_veces_promedia_el_precio():
    a = pt.calcular_compra(D(10000), D(1), D(100), D(0), D(0))
    b = pt.calcular_compra(a["saldo"], D(3), D(200), D(0), D(0), a["pos_cantidad"], a["pos_precio_medio"])
    assert b["pos_cantidad"] == 4 and b["pos_precio_medio"] == D(175)


def test_los_redondeos_nunca_favorecen_al_usuario():
    c = pt.calcular_compra(D(10000), D("0.00000003"), D("33.33333333"), COM, SLIP)
    assert c["valor"] >= D("0.00000003") * c["precio"]                 # lo que paga se redondea hacia arriba
    v = pt.calcular_venta(D("0.00000003"), D("33.33333333"), COM, SLIP, D("0.00000003"), D(1), D(0))
    assert v["valor"] <= D("0.00000003") * v["precio"]                 # lo que cobra, hacia abajo


def test_saldo_insuficiente_incluye_la_comision():
    # alcanza para el valor (100.05) pero no para valor + comisión (100.15005)
    with pytest.raises(pt.SaldoInsuficiente):
        pt.calcular_compra(D("100.10"), D(1), D(100), COM, SLIP)
    assert pt.calcular_compra(D("100.15005"), D(1), D(100), COM, SLIP)["saldo"] == 0


def test_no_se_vende_mas_de_lo_que_se_tiene():
    with pytest.raises(pt.PosicionInsuficiente):
        pt.calcular_venta(D("1.00000001"), D(100), COM, SLIP, D(1), D(100), D(0))
    with pytest.raises(pt.PosicionInsuficiente):
        pt.calcular_venta(D(1), D(100), COM, SLIP, D(0), D(0), D(0))


@pytest.mark.parametrize("cantidad,precio", [
    (D(0), D(1)), (D(-1), D(1)), (D("0.000000001"), D(1)), (D("NaN"), D(1)), (D("Infinity"), D(1)),
    (D(1), D(0)), (D(1), D(-5)), (D(1), D("NaN")), (D(10**9), D(2)),
])
def test_ordenes_invalidas_se_rechazan(cantidad, precio):
    with pytest.raises(pt.PaperError):
        pt.validar_orden(cantidad, precio)


def test_valoracion_con_y_sin_precio():
    pos = [{"coin_id": "bitcoin", "cantidad": D(2), "precio_medio": D(100)},
           {"coin_id": "ethereum", "cantidad": D(1), "precio_medio": D(50)}]
    ok = pt.valorar_posiciones(pos, {"bitcoin": D(120), "ethereum": D(40)})
    assert ok["completo"] and ok["valor_posiciones"] == D(280) and ok["pnl_no_realizado"] == D(30)
    assert ok["posiciones"][0]["pnl_pct"] == D(20)
    parcial = pt.valorar_posiciones(pos, {"bitcoin": D(120)})
    assert parcial["completo"] is False and parcial["valor_posiciones"] == D(240)   # no incluye ethereum
    assert parcial["posiciones"][1]["valor_actual"] is None


# ====================================================================== API

@pytest.fixture
def mercado(monkeypatch):
    """Precios falsos de CoinGecko (el servicio real se prueba contra su propia caché en otros tests)."""
    estado = {"precios": {"bitcoin": 100.0, "ethereum": 50.0}, "caido": False, "llamadas": 0}

    async def un_precio(coin_id, moneda="usd"):
        estado["llamadas"] += 1
        if estado["caido"]:
            return None
        return {coin_id: {"usd": estado["precios"][coin_id]}} if coin_id in estado["precios"] else {}

    async def varios(coin_ids, moneda="usd"):
        if estado["caido"]:
            return None
        return {c: {"usd": estado["precios"][c]} for c in coin_ids if c in estado["precios"]}

    monkeypatch.setattr(pt, "obtener_precio", un_precio)
    monkeypatch.setattr("app.services.coingecko.obtener_precios_multiples", varios)
    monkeypatch.setattr(config, "PAPER_COMMISSION_PCT", COM)
    monkeypatch.setattr(config, "PAPER_SLIPPAGE_PCT", SLIP)
    monkeypatch.setattr(config, "PAPER_INITIAL_BALANCE", D(10000))
    return estado


def _orden(client, headers, side="BUY", cantidad=1, coin="bitcoin", **extra):
    return client.post("/paper/orden", headers=headers, json={"coin_id": coin, "side": side, "cantidad": cantidad, **extra})


RUTAS = [("POST", "/paper/orden"), ("GET", "/paper/billetera"), ("GET", "/paper/posiciones"),
         ("GET", "/paper/historial"), ("POST", "/paper/reiniciar")]


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_todas_las_rutas_exigen_login(client, mercado, metodo, ruta):
    r = client.request(metodo, ruta, json={"coin_id": "bitcoin", "side": "BUY", "cantidad": 1} if metodo == "POST" else None)
    assert r.status_code in (401, 403)


def test_billetera_nueva_arranca_con_el_saldo_inicial(client, mercado, auth_headers):
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["saldo_usdt"] == 10000 and b["equity"] == 10000 and b["pnl_total"] == 0
    assert b["posiciones"] == [] and b["valoracion_completa"] is True


def test_compra_y_venta_completas(client, mercado, auth_headers):
    r = _orden(client, auth_headers, "BUY", 1)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["precio"] == 100.05 and c["comision"] == 0.10005 and c["saldo_usdt"] == 9899.84995
    assert c["repetida"] is False and c["pnl_realizado"] is None

    mercado["precios"]["bitcoin"] = 110.0
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["posiciones"][0]["precio_actual"] == 110.0 and b["posiciones"][0]["valor_actual"] == 110.0
    assert b["equity"] == pytest.approx(9899.84995 + 110.0)

    v = _orden(client, auth_headers, "SELL", 1).json()
    assert v["precio"] == 109.945 and v["pnl_realizado"] == pytest.approx(9.685005)
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["posiciones"] == [] and b["saldo_usdt"] == pytest.approx(10000 + 9.685005)
    assert b["pnl_realizado"] == pytest.approx(9.685005) and b["pnl_total"] == pytest.approx(9.685005)


def test_venta_parcial_deja_el_resto_con_el_mismo_precio_medio(client, mercado, auth_headers):
    _orden(client, auth_headers, "BUY", 4)
    medio = client.get("/paper/posiciones", headers=auth_headers).json()["posiciones"][0]["precio_medio"]
    _orden(client, auth_headers, "SELL", 1)
    p = client.get("/paper/posiciones", headers=auth_headers).json()["posiciones"][0]
    assert p["cantidad"] == 3 and p["precio_medio"] == medio


def test_saldo_insuficiente_da_409_y_no_cambia_nada(client, mercado, auth_headers):
    r = _orden(client, auth_headers, "BUY", 101)         # 101 x 100.05 > 10000
    assert r.status_code == 409 and "Saldo insuficiente" in r.json()["detail"]
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["saldo_usdt"] == 10000 and b["posiciones"] == []
    assert client.get("/paper/historial", headers=auth_headers).json() == []


def test_vender_lo_que_no_se_tiene_da_409(client, mercado, auth_headers):
    assert _orden(client, auth_headers, "SELL", 1).status_code == 409
    _orden(client, auth_headers, "BUY", 1)
    assert _orden(client, auth_headers, "SELL", 2).status_code == 409
    assert _orden(client, auth_headers, "SELL", 1, coin="ethereum").status_code == 409


@pytest.mark.parametrize("cuerpo", [
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": 0},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": -1},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": "0.000000001"},     # 9 decimales
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": "NaN"},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": "Infinity"},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": 10**12},
    {"coin_id": "bitcoin", "side": "SHORT", "cantidad": 1},
    {"coin_id": "bitcoin", "side": "buy", "cantidad": 1},
    {"coin_id": "../etc", "side": "BUY", "cantidad": 1},
    {"coin_id": "", "side": "BUY", "cantidad": 1},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": 1, "client_order_id": "a b"},
    {"coin_id": "bitcoin", "side": "BUY", "cantidad": 1, "client_order_id": "x" * 65},
    {"side": "BUY", "cantidad": 1},
])
def test_entradas_invalidas_dan_422(client, mercado, auth_headers, cuerpo):
    assert client.post("/paper/orden", headers=auth_headers, json=cuerpo).status_code == 422


def test_el_cliente_no_puede_fijar_el_precio(client, mercado, auth_headers):
    r = _orden(client, auth_headers, "BUY", 1, precio=0.0001, price=0.0001, saldo_usdt=10**9)
    assert r.status_code == 201 and r.json()["precio"] == 100.05


def test_sin_precio_no_hay_orden(client, mercado, auth_headers):
    mercado["caido"] = True
    r = _orden(client, auth_headers, "BUY", 1)
    assert r.status_code == 503
    mercado["caido"] = False
    assert client.get("/paper/billetera", headers=auth_headers).json()["saldo_usdt"] == 10000


@pytest.mark.parametrize("basura", [0, -5, "abc", None, float("nan")])
def test_un_precio_invalido_de_la_fuente_se_rechaza(client, mercado, auth_headers, monkeypatch, basura):
    async def raro(coin_id, moneda="usd"):
        return {coin_id: {"usd": basura}}
    monkeypatch.setattr(pt, "obtener_precio", raro)
    assert _orden(client, auth_headers, "BUY", 1).status_code == 503


def test_una_excepcion_al_consultar_el_precio_es_503_y_no_500(client, mercado, auth_headers, monkeypatch):
    async def explota(*a, **k):
        raise RuntimeError("red caída")
    monkeypatch.setattr(pt, "obtener_precio", explota)
    assert _orden(client, auth_headers, "BUY", 1).status_code == 503


def test_moneda_desconocida_da_404(client, mercado, auth_headers):
    assert _orden(client, auth_headers, "BUY", 1, coin="monedainventada").status_code == 404


def test_valoracion_incompleta_se_avisa_y_no_se_inventa(client, mercado, auth_headers):
    _orden(client, auth_headers, "BUY", 1)
    mercado["caido"] = True
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["valoracion_completa"] is False
    assert b["posiciones"][0]["valor_actual"] is None and b["valor_posiciones"] == 0


# ---------------------------------------------------------------- idempotencia

def test_reintentar_con_el_mismo_client_order_id_no_duplica(client, mercado, auth_headers):
    a = _orden(client, auth_headers, "BUY", 1, client_order_id="abc-1")
    b = _orden(client, auth_headers, "BUY", 1, client_order_id="abc-1")
    assert a.status_code == 201 and b.status_code == 200
    assert b.json()["repetida"] is True and b.json()["id"] == a.json()["id"]
    assert b.json()["saldo_usdt"] == a.json()["saldo_usdt"]
    assert len(client.get("/paper/historial", headers=auth_headers).json()) == 1


def test_el_mismo_client_order_id_con_otra_orden_da_409(client, mercado, auth_headers):
    _orden(client, auth_headers, "BUY", 1, client_order_id="abc-1")
    assert _orden(client, auth_headers, "BUY", 2, client_order_id="abc-1").status_code == 409
    assert _orden(client, auth_headers, "BUY", 1, coin="ethereum", client_order_id="abc-1").status_code == 409


def test_dos_usuarios_pueden_usar_el_mismo_client_order_id(client, mercado, usuario_a, usuario_b):
    assert _orden(client, usuario_a["headers"], "BUY", 1, client_order_id="x").status_code == 201
    assert _orden(client, usuario_b["headers"], "BUY", 1, client_order_id="x").status_code == 201


# ---------------------------------------------------------------- aislamiento

def test_cada_usuario_ve_solo_lo_suyo(client, mercado, usuario_a, usuario_b):
    _orden(client, usuario_a["headers"], "BUY", 2)
    assert client.get("/paper/posiciones", headers=usuario_b["headers"]).json()["posiciones"] == []
    assert client.get("/paper/historial", headers=usuario_b["headers"]).json() == []
    assert client.get("/paper/billetera", headers=usuario_b["headers"]).json()["saldo_usdt"] == 10000
    assert _orden(client, usuario_b["headers"], "SELL", 1).status_code == 409      # no puede vender lo de A
    client.post("/paper/reiniciar", headers=usuario_b["headers"])
    assert client.get("/paper/posiciones", headers=usuario_a["headers"]).json()["posiciones"][0]["cantidad"] == 2


# ---------------------------------------------------------------- historial, reinicio, límites

def test_historial_orden_y_paginacion(client, mercado, auth_headers):
    for _ in range(5):
        _orden(client, auth_headers, "BUY", 1)
    todo = client.get("/paper/historial", headers=auth_headers).json()
    assert [t["id"] for t in todo] == sorted((t["id"] for t in todo), reverse=True) and len(todo) == 5
    pagina = client.get("/paper/historial?skip=1&limit=2", headers=auth_headers).json()
    assert [t["id"] for t in pagina] == [todo[1]["id"], todo[2]["id"]]
    for q in ("limit=0", "limit=101", "skip=-1"):
        assert client.get(f"/paper/historial?{q}", headers=auth_headers).status_code == 422


def test_reiniciar_devuelve_todo_al_estado_inicial(client, mercado, auth_headers):
    _orden(client, auth_headers, "BUY", 3)
    assert client.post("/paper/reiniciar", headers=auth_headers).status_code == 200
    b = client.get("/paper/billetera", headers=auth_headers).json()
    assert b["saldo_usdt"] == 10000 and b["posiciones"] == [] and b["pnl_realizado"] == 0
    assert client.get("/paper/historial", headers=auth_headers).json() == []


def test_el_reinicio_esta_limitado_por_hora(client, mercado, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "PAPER_RESETS_PER_HOUR", 2)
    estados = [client.post("/paper/reiniciar", headers=auth_headers).status_code for _ in range(3)]
    assert estados == [200, 200, 429]


def test_las_ordenes_estan_limitadas_por_usuario(client, mercado, usuario_a, usuario_b, monkeypatch):
    monkeypatch.setattr(config, "PAPER_ORDERS_PER_MINUTE", 2)
    est = [_orden(client, usuario_a["headers"], "BUY", "0.1").status_code for _ in range(3)]
    assert est == [201, 201, 429]
    r = _orden(client, usuario_a["headers"], "BUY", "0.1")
    assert "Retry-After" in r.headers
    assert _orden(client, usuario_b["headers"], "BUY", "0.1").status_code == 201    # el cupo es por usuario


def test_un_fallo_del_limitador_no_bloquea_las_ordenes(client, mercado, auth_headers, monkeypatch):
    from app.services.ratelimit import limitador

    def roto(*a, **k):
        raise RuntimeError("redis caído")
    monkeypatch.setattr(limitador, "golpear", roto)
    assert _orden(client, auth_headers, "BUY", 1).status_code == 201


def test_el_saldo_inicial_viene_de_la_configuracion(client, mercado, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "PAPER_INITIAL_BALANCE", D(500))
    assert client.get("/paper/billetera", headers=auth_headers).json()["saldo_usdt"] == 500


# ====================================================================== base de datos y concurrencia

def _usuario(nombre="ana"):
    return UserDAO().crear_usuario_db(nombre, f"{nombre}@example.com", "x")


def _ejecutar(uid, side="BUY", cantidad=D(1), precio=D(100), cid=None):
    return PaperDAO().ejecutar_orden(uid, "bitcoin", side, cantidad, precio, D(1000), COM, SLIP, cid)


def test_compras_simultaneas_no_pueden_gastar_el_mismo_saldo(db_limpia):
    """Saldo 1000: cada compra cuesta ~100.15, así que caben 9. Con 20 hilos deben pasar exactamente 9."""
    uid = _usuario()

    def intento(_):
        try:
            _ejecutar(uid)
            return True
        except pt.SaldoInsuficiente:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        resultados = list(pool.map(intento, range(20)))
    assert sum(resultados) == 9
    cuenta = PaperDAO().obtener_billetera(uid, D(1000))
    pos = PaperDAO().obtener_posiciones(uid)[0]
    assert pos["cantidad"] == 9 and cuenta["balance_usdt"] >= 0
    assert cuenta["balance_usdt"] == D(1000) - 9 * D("100.15005")
    assert len(PaperDAO().obtener_historial(uid)) == 9


def test_ventas_simultaneas_no_pueden_vender_lo_mismo_dos_veces(db_limpia):
    uid = _usuario()
    _ejecutar(uid, cantidad=D(2))

    def intento(_):
        try:
            _ejecutar(uid, "SELL", D(1))
            return True
        except pt.PosicionInsuficiente:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(intento, range(8)))
    assert sum(resultados) == 2 and PaperDAO().obtener_posiciones(uid) == []


def test_el_mismo_client_order_id_en_paralelo_ejecuta_una_sola_vez(db_limpia):
    uid = _usuario()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        res = list(pool.map(lambda _: _ejecutar(uid, cid="unico"), range(8)))
    assert sum(1 for r in res if not r["repetida"]) == 1
    assert len(PaperDAO().obtener_historial(uid)) == 1


def test_primera_orden_simultanea_crea_una_sola_billetera(db_limpia):
    uid = _usuario()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: PaperDAO().obtener_billetera(uid, D(1000)), range(8)))
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM paper_wallet")).scalar_one() == 1


def test_un_error_a_mitad_de_la_orden_no_deja_cambios_a_medias(db_limpia, monkeypatch):
    uid = _usuario()
    _ejecutar(uid)
    antes = (PaperDAO().obtener_billetera(uid, D(1000)), PaperDAO().obtener_posiciones(uid))

    def roto(*a, **k):
        raise RuntimeError("fallo")
    monkeypatch.setattr(pt, "calcular_compra", roto)
    with pytest.raises(RuntimeError):
        _ejecutar(uid)
    assert (PaperDAO().obtener_billetera(uid, D(1000)), PaperDAO().obtener_posiciones(uid)) == antes


@pytest.mark.parametrize("sql", [
    "UPDATE paper_wallet SET balance_usdt = -1",
    "UPDATE paper_positions SET cantidad = 0",
    "UPDATE paper_trades SET side = 'SHORT'",
    "UPDATE paper_trades SET precio = 0",
    "UPDATE paper_trades SET comision = -1",
    "INSERT INTO paper_wallet (usuario_id, balance_usdt, saldo_inicial) SELECT usuario_id, 1, 1 FROM paper_wallet",
])
def test_la_base_rechaza_datos_imposibles(db_limpia, sql):
    uid = _usuario()
    _ejecutar(uid)
    with pytest.raises(Exception):
        with engine.begin() as c:
            c.execute(text(sql))


def test_borrar_un_usuario_borra_sus_datos_de_paper(db_limpia):
    uid = _usuario()
    _ejecutar(uid)
    with engine.begin() as c:
        c.execute(text("DELETE FROM usuarios WHERE id = :i"), {"i": uid})
        assert c.execute(text("SELECT (SELECT count(*) FROM paper_wallet) + (SELECT count(*) FROM paper_positions)"
                              " + (SELECT count(*) FROM paper_trades)")).scalar_one() == 0


def test_los_importes_se_guardan_con_8_decimales_sin_perder_precision(db_limpia):
    uid = _usuario()
    r = _ejecutar(uid, cantidad=D("0.01234567"), precio=D("33333.33333333"))
    t = PaperDAO().obtener_historial(uid)[0]
    assert isinstance(t["precio"], D) and t["precio"] == r["precio"] and t["cantidad"] == D("0.01234567")


# ====================================================================== migración 0004

def test_migracion_0004_sube_y_baja_sin_tocar_usuarios():
    uid = _usuario("persistente")
    try:
        command.downgrade(alembic_config(), "0003")
        assert not {"paper_wallet", "paper_positions", "paper_trades"} & set(inspect(engine).get_table_names())
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM usuarios WHERE id = :i"), {"i": uid}).scalar_one() == 1
    finally:
        command.upgrade(alembic_config(), "head")
        with engine.begin() as c:
            c.execute(text("TRUNCATE usuarios RESTART IDENTITY CASCADE"))
    assert {"paper_wallet", "paper_positions", "paper_trades"} <= set(inspect(engine).get_table_names())
