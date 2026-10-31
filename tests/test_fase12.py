# tests/test_fase12.py
"""Fase 12: quitar monedas de la watchlist, cabeceras de seguridad y alertas sin repetirse cada minuto."""
import asyncio
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient as StarletteClient

from app.config import config
from app.dao.TradeDAO import TradeDAO
from app.dao.UserDAO import UserDAO
from app.dao.WatchlistDAO import WatchlistDAO
from app.middleware import SecurityHeadersMiddleware
from app.services.ratelimit import limitador
from tests.test_config_ratelimit import _cfg


# ====================================================================== watchlist: DELETE

def _agregar(client, headers, coin="bitcoin"):
    return client.post("/analisis/watchlist", headers=headers, json={"coin_id": coin, "precio_alerta": 10})


def test_quitar_una_moneda_de_la_watchlist(client, auth_headers):
    item = _agregar(client, auth_headers).json()
    r = client.delete(f"/analisis/watchlist/{item['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["id"] == item["id"]
    assert client.get("/analisis/watchlist", headers=auth_headers).json() == []
    assert client.delete(f"/analisis/watchlist/{item['id']}", headers=auth_headers).status_code == 404


def test_no_se_puede_quitar_lo_de_otro_usuario_y_el_404_es_igual_que_si_no_existe(client, usuario_a, usuario_b):
    item = _agregar(client, usuario_a["headers"]).json()
    ajeno = client.delete(f"/analisis/watchlist/{item['id']}", headers=usuario_b["headers"])
    inexistente = client.delete("/analisis/watchlist/999999", headers=usuario_b["headers"])
    assert ajeno.status_code == inexistente.status_code == 404 and ajeno.json() == inexistente.json()
    assert len(client.get("/analisis/watchlist", headers=usuario_a["headers"]).json()) == 1      # sigue ahí


@pytest.mark.parametrize("ruta", ["/analisis/watchlist/0", "/analisis/watchlist/-1", "/analisis/watchlist/abc",
                                  "/analisis/watchlist/99999999999999"])
def test_ids_invalidos_dan_422(client, auth_headers, ruta):
    assert client.delete(ruta, headers=auth_headers).status_code == 422


def test_quitar_exige_login(client):
    assert client.delete("/analisis/watchlist/1").status_code in (401, 403)


def test_quitar_libera_cupo_del_tope(client, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_MAX_ITEMS", 2)
    ids = [_agregar(client, auth_headers, f"coin{i}").json()["id"] for i in range(2)]
    assert _agregar(client, auth_headers, "coin9").status_code == 409
    client.delete(f"/analisis/watchlist/{ids[0]}", headers=auth_headers)
    assert _agregar(client, auth_headers, "coin9").status_code == 201


def test_el_dao_solo_borra_lo_propio(db_limpia):
    a = UserDAO().crear_usuario_db("ana", "a@example.com", "x")
    b = UserDAO().crear_usuario_db("beto", "b@example.com", "x")
    item = WatchlistDAO().agregar_db(a, "bitcoin", 1)
    assert WatchlistDAO().eliminar_db(b, item) is False and len(WatchlistDAO().obtener_por_usuario_db(a)) == 1
    assert WatchlistDAO().eliminar_db(a, item) is True and WatchlistDAO().eliminar_db(a, item) is False


# ====================================================================== cabeceras de seguridad

COMUNES = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer"}


def _con_cabeceras(r):
    h = {k.lower(): v for k, v in r.headers.items()}
    for k, v in COMUNES.items():
        assert h.get(k) == v, f"falta {k} en {r.status_code}"
    return h


def test_las_respuestas_de_la_api_llevan_cabeceras_de_seguridad(client):
    h = _con_cabeceras(client.get("/health"))
    assert h["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert h["cache-control"] == "no-store"


def test_tambien_en_errores_y_respuestas_de_limite(client, monkeypatch):
    _con_cabeceras(client.get("/usuarios/me"))                              # 401/403
    _con_cabeceras(client.get("/ruta/que/no/existe"))                       # 404
    _con_cabeceras(client.post("/usuarios/login", json={"username": "", "password": ""}))   # 422
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 1)
    client.get("/info")
    r = client.get("/info")
    assert r.status_code == 429
    _con_cabeceras(r)


def test_tambien_en_la_respuesta_de_cors(client):
    r = client.options("/info", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    _con_cabeceras(r)


def test_la_documentacion_y_los_estaticos_no_reciben_csp_ni_no_store(client):
    for ruta in ("/docs", "/static/websocket_test.html"):
        h = _con_cabeceras(client.get(ruta))
        assert "content-security-policy" not in h and h.get("cache-control") != "no-store", ruta


def test_sin_hsts_en_desarrollo_y_con_hsts_cuando_se_activa(client):
    assert "strict-transport-security" not in client.get("/health").headers

    async def vivo(request):
        return JSONResponse({"ok": 1}, headers={"Cache-Control": "max-age=60"})

    app = Starlette(routes=[Route("/x", vivo)])
    app.add_middleware(SecurityHeadersMiddleware, hsts=True)
    r = StarletteClient(app).get("/x")
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert r.headers["cache-control"] == "max-age=60"                          # no pisa la cabecera de la ruta


def test_el_middleware_no_toca_los_websockets(client):
    from app.dao.UserDAO import UserDAO
    from utils.authorization import create_access_token
    uid = UserDAO().crear_usuario_db("ana", "a@example.com", "x")
    with client.websocket_connect(f"/ws/chat?token={create_access_token({'sub': str(uid)})}") as ws:
        assert ws.receive_json()["tipo"] == "conexion"


def test_en_produccion_el_middleware_se_monta_con_hsts(monkeypatch):
    import importlib, app.main as principal
    monkeypatch.setattr(config.__class__, "is_production", property(lambda self: True))
    recargado = importlib.reload(principal)
    try:
        r = StarletteClient(recargado.app).get("/health")
        assert "strict-transport-security" in r.headers
    finally:
        monkeypatch.undo()
        importlib.reload(principal)


# ====================================================================== alertas con cooldown

class WsFalso:
    def __init__(self):
        self.enviados = []

    async def send_json(self, mensaje):
        self.enviados.append(mensaje)


def _pasada(monkeypatch, precios):
    """Ejecuta UNA vuelta del bucle de alertas (sin esperar 60 s) y devuelve."""
    from app.routers import websocket as ws_mod
    vueltas = {"n": 0}

    async def sleep(_):
        vueltas["n"] += 1
        if vueltas["n"] > 1:
            raise asyncio.CancelledError()

    async def precios_falsos(coin_ids, moneda="usd"):
        return {c: {"usd": precios[c]} for c in coin_ids if c in precios}

    monkeypatch.setattr(ws_mod, "asyncio", SimpleNamespace(sleep=sleep, gather=asyncio.gather))
    monkeypatch.setattr(ws_mod, "obtener_precios_multiples", precios_falsos)
    try:
        asyncio.run(ws_mod.verificar_alertas())
    except asyncio.CancelledError:
        pass


@pytest.fixture
def conectado(db_limpia):
    """Un usuario con una moneda en la watchlist y un WebSocket de notificaciones abierto (falso)."""
    from app.routers.websocket import notification_manager
    uid = UserDAO().crear_usuario_db("ana", "a@example.com", "x")
    WatchlistDAO().agregar_db(uid, "bitcoin", 10)
    ws = WsFalso()
    notification_manager.conexiones[uid] = [ws]
    limitador.reiniciar()
    yield uid, ws
    notification_manager.conexiones.pop(uid, None)
    limitador.reiniciar()


def _precio_objetivo(ws):
    return [m for m in ws.enviados if m["tipo"] == "precio_objetivo"]


def test_una_alerta_de_precio_no_se_repite_cada_minuto(conectado, monkeypatch):
    uid, ws = conectado
    _pasada(monkeypatch, {"bitcoin": 100.0})
    assert len(_precio_objetivo(ws)) == 1
    for _ in range(3):                                   # minutos siguientes: la condición sigue cumpliéndose
        limitador.olvidar(f"alertas:{uid}")              # (el turno por usuario ya no es lo que frena)
        _pasada(monkeypatch, {"bitcoin": 100.0})
    assert len(_precio_objetivo(ws)) == 1


def test_el_aviso_vuelve_a_enviarse_al_terminar_el_cooldown(conectado, monkeypatch):
    uid, ws = conectado
    _pasada(monkeypatch, {"bitcoin": 100.0})
    limitador.reiniciar()                                # equivale a que venza el cooldown
    _pasada(monkeypatch, {"bitcoin": 100.0})
    assert len(_precio_objetivo(ws)) == 2


def test_el_cooldown_es_por_moneda(conectado, monkeypatch):
    uid, ws = conectado
    WatchlistDAO().agregar_db(uid, "ethereum", 10)
    _pasada(monkeypatch, {"bitcoin": 100.0, "ethereum": 100.0})
    assert sorted(m["coin_id"] for m in _precio_objetivo(ws)) == ["bitcoin", "ethereum"]


def test_el_cooldown_es_por_usuario(conectado, monkeypatch):
    from app.routers.websocket import notification_manager
    uid, ws = conectado
    otro = UserDAO().crear_usuario_db("beto", "b@example.com", "x")
    WatchlistDAO().agregar_db(otro, "bitcoin", 10)
    ws2 = WsFalso()
    notification_manager.conexiones[otro] = [ws2]
    try:
        _pasada(monkeypatch, {"bitcoin": 100.0})
        assert len(_precio_objetivo(ws)) == 1 and len(_precio_objetivo(ws2)) == 1
    finally:
        notification_manager.conexiones.pop(otro, None)


def test_sin_alerta_si_el_precio_no_llega_y_no_gasta_cooldown(conectado, monkeypatch):
    uid, ws = conectado
    _pasada(monkeypatch, {"bitcoin": 5.0})              # por debajo del objetivo (10)
    assert _precio_objetivo(ws) == []
    limitador.olvidar(f"alertas:{uid}")
    _pasada(monkeypatch, {"bitcoin": 100.0})            # ahora sí llega: debe avisar de inmediato
    assert len(_precio_objetivo(ws)) == 1


def test_el_pnl_significativo_tambien_tiene_cooldown(conectado, monkeypatch):
    uid, ws = conectado
    TradeDAO().crear_trade_db(uid, "compra", "BTC", 50, 1, "2026-01-01")      # comprado a 50, ahora vale 100: +100 %
    _pasada(monkeypatch, {"bitcoin": 100.0})
    limitador.olvidar(f"alertas:{uid}")
    _pasada(monkeypatch, {"bitcoin": 100.0})
    assert len([m for m in ws.enviados if m["tipo"] == "pnl_significativo"]) == 1


def test_un_fallo_del_limitador_deja_pasar_el_aviso(conectado, monkeypatch):
    uid, ws = conectado

    def roto(*a, **k):
        raise RuntimeError("redis caído")
    monkeypatch.setattr(limitador, "golpear", roto)
    _pasada(monkeypatch, {"bitcoin": 100.0})
    assert len(_precio_objetivo(ws)) == 1


def test_configuracion_del_cooldown():
    assert config.ALERT_COOLDOWN_SECONDS == 3600
    for valor in (0, -1):
        with pytest.raises(RuntimeError, match="ALERT_COOLDOWN_SECONDS"):
            _cfg(ALERT_COOLDOWN_SECONDS=valor).validate()
