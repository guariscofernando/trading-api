"""Fase 14: órdenes venenosas y caché negativo de monedas desconocidas."""
import asyncio

import httpx
import pytest

from app.dao.PaperDAO import PaperDAO
from app.services import coingecko
from app.services.cache import cache
from tests.test_paper_ordenes import _ciclo, _pend, mercado  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def _fallos_limpios():
    PaperDAO._fallos.clear()
    yield
    PaperDAO._fallos.clear()


def _roto(monkeypatch):
    def explota(*a, **k):
        raise RuntimeError("fallo inesperado")
    monkeypatch.setattr(PaperDAO, "_procesar_una", staticmethod(explota))


def _estado(client, headers):
    return client.get("/paper/ordenes", headers=headers).json()[0]


def test_una_orden_venenosa_se_rechaza_tras_el_tope_de_fallos(client, mercado, auth_headers, monkeypatch):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    _roto(monkeypatch)
    for _ in range(PaperDAO.MAX_FALLOS - 1):
        assert _ciclo()["errores"] == 1
        assert _estado(client, auth_headers)["estado"] == "ABIERTA"
    r = _ciclo()
    assert r["errores"] == 1 and r["rechazadas"] == 1
    o = _estado(client, auth_headers)
    assert o["estado"] == "RECHAZADA" and "Error interno" in o["motivo"] and o["cerrada_en"]
    assert _ciclo() == {"ejecutadas": 0, "rechazadas": 0, "errores": 0}      # ya no se reintenta


def test_un_exito_reinicia_la_cuenta_de_fallos(client, mercado, auth_headers, monkeypatch):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    original = PaperDAO._procesar_una
    _roto(monkeypatch)
    for _ in range(PaperDAO.MAX_FALLOS - 1):
        _ciclo()
    monkeypatch.setattr(PaperDAO, "_procesar_una", staticmethod(original))
    assert _ciclo()["ejecutadas"] == 1
    assert PaperDAO._fallos == {}


def test_una_venenosa_no_impide_ejecutar_las_demas(client, mercado, auth_headers, monkeypatch):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    _pend(client, auth_headers, "BUY", "LIMIT", 130)
    original = PaperDAO._procesar_una
    primera = client.get("/paper/ordenes", headers=auth_headers).json()
    id_malo = min(o["id"] for o in primera)

    def selectiva(orden_id, *a, **k):
        if orden_id == id_malo:
            raise RuntimeError("boom")
        return original(orden_id, *a, **k)
    monkeypatch.setattr(PaperDAO, "_procesar_una", staticmethod(selectiva))
    r = _ciclo()
    assert r["ejecutadas"] == 1 and r["errores"] == 1


def test_una_orden_ya_cerrada_no_se_rechaza_por_error(client, mercado, auth_headers):
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    oid = _estado(client, auth_headers)["id"]
    _ciclo()                                       # se ejecuta
    PaperDAO._fallos[oid] = PaperDAO.MAX_FALLOS - 1
    assert PaperDAO()._anotar_fallo(oid) is False  # el UPDATE exige estado ABIERTA
    assert _estado(client, auth_headers)["estado"] == "EJECUTADA"


# ---------------------------------------------------------------- caché negativo

def _falso_http(monkeypatch, cuerpo, status=200):
    llamadas = []

    class Cliente:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **k):
            llamadas.append(url)
            return httpx.Response(status, json=cuerpo, request=httpx.Request("GET", url))
    monkeypatch.setattr(coingecko.httpx, "AsyncClient", Cliente)
    return llamadas


def test_una_moneda_desconocida_se_cachea_y_no_repite_la_peticion(monkeypatch):
    cache.clear() if hasattr(cache, "clear") else None
    llamadas = _falso_http(monkeypatch, {})
    for _ in range(3):
        assert asyncio.run(coingecko.obtener_precio("noexiste-xyz")) == {}
    assert len(llamadas) == 1


def test_un_error_de_coingecko_no_se_cachea(monkeypatch):
    cache.clear() if hasattr(cache, "clear") else None
    llamadas = _falso_http(monkeypatch, {"error": "x"}, status=500)
    for _ in range(2):
        assert asyncio.run(coingecko.obtener_precio("bitcoin-err")) is None
    assert len(llamadas) == 2
