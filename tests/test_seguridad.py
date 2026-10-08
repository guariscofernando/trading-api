# tests/test_seguridad.py
"""Acceso sin token, aislamiento entre usuarios, validación de config y robustez."""
import pytest
from fastapi.testclient import TestClient

NO_AUTORIZADO = (401, 403)  # según la versión de FastAPI, HTTPBearer devuelve 401 o 403

TRADE_BTC = {"tipo": "compra", "activo": "BTC", "precio": 50000, "cantidad": 0.5}


def _crear_trade(client, headers, **cambios):
    r = client.post("/trades/", json={**TRADE_BTC, **cambios}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- sin token

ENDPOINTS_PROTEGIDOS = [
    ("GET", "/trades/buscar"),
    ("GET", "/trades/exportar/csv"),
    ("GET", "/trades/estadisticas"),
    ("GET", "/trades/resumen/pnl"),
    ("GET", "/trades/resumen/mejor-trade"),
    ("GET", "/trades/resumen/por-fecha"),
    ("GET", "/trades/resumen/por-activo/BTC"),
    ("GET", "/trades/1"),
    ("GET", "/usuarios/1"),
    ("GET", "/precios/cache/stats"),
    ("DELETE", "/precios/cache/clear"),
    ("GET", "/system/metrics"),
    ("GET", "/system/endpoints"),
]


@pytest.mark.parametrize("metodo,ruta", ENDPOINTS_PROTEGIDOS)
def test_endpoints_exigen_token(client, metodo, ruta):
    response = client.request(metodo, ruta)
    assert response.status_code in NO_AUTORIZADO, (
        f"{metodo} {ruta} respondió {response.status_code} sin token"
    )


def test_token_invalido_es_rechazado(client):
    response = client.get(
        "/trades/estadisticas", headers={"Authorization": "Bearer token.falso.xxx"}
    )
    assert response.status_code == 401


# --------------------------------------------------- aislamiento entre usuarios

def test_usuario_b_no_ve_trades_de_a_en_endpoints_de_resumen(client, usuario_a, usuario_b):
    _crear_trade(client, usuario_a["headers"])

    h = usuario_b["headers"]
    assert client.get("/trades/estadisticas", headers=h).json() == {
        "mensaje": "No hay trades registrados"
    }
    assert client.get("/trades/buscar", headers=h).json() == []
    assert client.get("/trades/resumen/por-fecha", headers=h).json() == []
    assert client.get("/trades/resumen/pnl", headers=h).json()["total_trades"] == 0
    assert client.get("/trades/resumen/mejor-trade", headers=h).status_code == 404
    assert client.get("/trades/resumen/por-activo/BTC", headers=h).status_code == 404


def test_csv_solo_incluye_trades_propios(client, usuario_a, usuario_b):
    _crear_trade(client, usuario_a["headers"], activo="BTC")
    _crear_trade(client, usuario_b["headers"], activo="ETH")

    csv_b = client.get("/trades/exportar/csv", headers=usuario_b["headers"]).text
    assert "ETH" in csv_b
    assert "BTC" not in csv_b


def test_usuario_a_si_ve_sus_propios_datos(client, usuario_a):
    _crear_trade(client, usuario_a["headers"])
    h = usuario_a["headers"]

    assert client.get("/trades/estadisticas", headers=h).json()["total_trades"] == 1
    assert len(client.get("/trades/buscar", headers=h).json()) == 1
    assert client.get("/trades/resumen/por-activo/BTC", headers=h).status_code == 200


def test_no_se_puede_leer_trade_ajeno_por_id(client, usuario_a, usuario_b):
    trade = _crear_trade(client, usuario_a["headers"])

    ajeno = client.get(f"/trades/{trade['id']}", headers=usuario_b["headers"])
    inexistente = client.get("/trades/999999", headers=usuario_b["headers"])
    propio = client.get(f"/trades/{trade['id']}", headers=usuario_a["headers"])

    assert ajeno.status_code == 404
    # No debe poder distinguirse "es de otro" de "no existe"
    assert ajeno.json() == inexistente.json()
    assert propio.status_code == 200


def test_no_se_puede_modificar_ni_borrar_trade_ajeno(client, usuario_a, usuario_b):
    trade = _crear_trade(client, usuario_a["headers"])
    url = f"/trades/{trade['id']}"

    assert client.patch(url, json={"precio": 1}, headers=usuario_b["headers"]).status_code == 403
    assert client.delete(url, headers=usuario_b["headers"]).status_code == 403
    # El trade sigue intacto para su dueño
    assert client.get(url, headers=usuario_a["headers"]).json()["precio"] == 50000


def test_usuario_solo_puede_ver_su_propio_perfil(client, usuario_a, usuario_b):
    ajeno = client.get(f"/usuarios/{usuario_a['id']}", headers=usuario_b["headers"])
    propio = client.get(f"/usuarios/{usuario_b['id']}", headers=usuario_b["headers"])

    assert ajeno.status_code == 404
    assert propio.status_code == 200
    assert propio.json()["username"] == "usuario_b"


# ------------------------------------------------------------------- config

def _config_valida(**cambios):
    from app.config import Config
    cfg = Config()
    cfg.ENVIRONMENT = "development"
    cfg.SECRET_KEY = "una-clave-de-prueba-suficientemente-larga-123456"
    cfg.ALGORITHM = "HS256"
    cfg.DATABASE_URL = "postgresql://u:p@localhost:5432/x_test"
    cfg.APP_NAME = "T"
    cfg.APP_VERSION = "1"
    cfg.APP_DESCRIPTION = "t"
    cfg.CORS_ORIGINS = ["http://localhost:3000"]
    for campo, valor in cambios.items():
        setattr(cfg, campo, valor)
    return cfg


def test_config_valida_no_falla():
    _config_valida().validate()


@pytest.mark.parametrize("variable", ["SECRET_KEY", "ALGORITHM", "DATABASE_URL", "APP_NAME"])
def test_config_falla_con_mensaje_claro_si_falta_variable(variable):
    cfg = _config_valida(**{variable: None})
    with pytest.raises(RuntimeError, match=variable):
        cfg.validate()


def test_config_rechaza_algoritmo_invalido():
    # "none" desactivaría la firma del JWT
    with pytest.raises(RuntimeError, match="ALGORITHM"):
        _config_valida(ALGORITHM="none").validate()


@pytest.mark.parametrize("clave", [
    "corta",
    "cambiar-por-una-clave-segura-en-produccion",
    "cambia-esto-en-produccion",
])
def test_config_produccion_rechaza_secret_key_debil(clave):
    cfg = _config_valida(ENVIRONMENT="production", SECRET_KEY=clave)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        cfg.validate()


def test_config_produccion_rechaza_cors_abierto():
    for origenes in ([], ["*"]):
        cfg = _config_valida(ENVIRONMENT="production", CORS_ORIGINS=origenes)
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            cfg.validate()


def test_config_produccion_valida_ok():
    _config_valida(ENVIRONMENT="production").validate()


# ----------------------------------------------------------------- robustez

def test_binance_no_toca_la_red_al_crear_el_cliente(monkeypatch):
    """Si Binance está caído o bloqueado por región, la API igual debe poder arrancar."""
    from binance.client import Client

    def ping_falla(self, *a, **k):
        raise ConnectionError("Binance no disponible")

    monkeypatch.setattr(Client, "ping", ping_falla)

    from app.services.binance_service import BinanceService
    servicio = BinanceService()  # no debe lanzar excepción

    # y el ping del servicio informa False en vez de romper con 500
    assert servicio.ping() is False


def test_error_interno_no_filtra_detalles_en_produccion(monkeypatch):
    from app.main import app
    from app.config import config

    async def boom():
        raise RuntimeError("password=super-secreto host=db-interna")

    app.add_api_route("/__boom", boom, methods=["GET"])
    try:
        cliente = TestClient(app, raise_server_exceptions=False)

        monkeypatch.setattr(type(config), "ENVIRONMENT", "production")
        r = cliente.get("/__boom")
        assert r.status_code == 500
        assert "super-secreto" not in r.text
        assert "mensaje" not in r.json()

        monkeypatch.setattr(type(config), "ENVIRONMENT", "development")
        r = cliente.get("/__boom")
        assert "super-secreto" in r.json()["mensaje"]
    finally:
        app.router.routes[:] = [
            ruta for ruta in app.router.routes if getattr(ruta, "path", "") != "/__boom"
        ]
