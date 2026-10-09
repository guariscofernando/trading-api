# tests/test_regresiones.py
"""Bugs encontrados al preparar la migración a SQLAlchemy. Cada test fallaba antes del arreglo."""


def _crear(client, headers, fecha_ok=True):
    r = client.post("/trades/", json={"tipo": "compra", "activo": "BTC", "precio": 100, "cantidad": 1},
                    headers=headers)
    assert r.status_code == 201, r.text


def test_buscar_con_fecha_desde_y_hasta_no_da_500(client, auth_headers):
    _crear(client, auth_headers)
    r = client.get("/trades/buscar?fecha_desde=2000-01-01&fecha_hasta=2999-12-31", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_buscar_filtra_realmente_por_fecha(client, auth_headers):
    _crear(client, auth_headers)
    assert len(client.get("/trades/buscar?fecha_desde=2999-01-01", headers=auth_headers).json()) == 0
    assert len(client.get("/trades/buscar?fecha_hasta=2000-01-01", headers=auth_headers).json()) == 0


def test_buscar_con_fecha_invalida_da_422(client, auth_headers):
    r = client.get("/trades/buscar?fecha_desde=ayer", headers=auth_headers)
    assert r.status_code == 422


def test_watchlist_acepta_ids_largos_de_coingecko(client, auth_headers):
    for coin_id in ("binancecoin", "avalanche-2", "wrapped-bitcoin", "matic-network"):
        r = client.post("/analisis/watchlist", json={"coin_id": coin_id, "precio_alerta": 10},
                        headers=auth_headers)
        assert r.status_code == 201, f"{coin_id}: {r.status_code} {r.text}"
        assert r.json()["coin_id"] == coin_id


def test_watchlist_rechaza_ids_absurdamente_largos_con_422(client, auth_headers):
    r = client.post("/analisis/watchlist", json={"coin_id": "x" * 500, "precio_alerta": 10},
                    headers=auth_headers)
    assert r.status_code == 422
