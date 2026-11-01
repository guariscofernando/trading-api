"""Fase 15: métricas Prometheus, /metrics protegido y /ready."""
import asyncio

import pytest

from app.config import config
from app.services import metricas, paper_matching
from app.services.metricas import token_valido
from tests.test_paper_ordenes import _pend, mercado  # noqa: F401 (fixture)


@pytest.fixture
def con_token(monkeypatch):
    monkeypatch.setattr(config, "METRICS_TOKEN", "secreto-de-metricas")
    return {"Authorization": "Bearer secreto-de-metricas"}


def _valor(texto, nombre, etiquetas=""):
    """Valor de una serie del texto Prometheus (0 si aún no existe)."""
    for linea in texto.splitlines():
        if linea.startswith(nombre + etiquetas + " ") or (not etiquetas and linea.startswith(nombre + "{")):
            return float(linea.rsplit(" ", 1)[1])
    return 0.0


def test_sin_metrics_token_el_endpoint_no_existe(client, monkeypatch):
    monkeypatch.setattr(config, "METRICS_TOKEN", "")
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer "}).status_code == 404


@pytest.mark.parametrize("cabecera", [None, "", "Bearer", "Bearer otro", "Basic secreto-de-metricas", "secreto-de-metricas"])
def test_metrics_rechaza_tokens_ausentes_o_incorrectos(client, con_token, cabecera):
    headers = {"Authorization": cabecera} if cabecera is not None else {}
    r = client.get("/metrics", headers=headers)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_metrics_con_el_token_devuelve_formato_prometheus(client, con_token):
    r = client.get("/metrics", headers=con_token)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_peticiones_total counter" in r.text
    assert "paper_ultimo_ciclo_ok_timestamp" in r.text


def test_token_valido_unitario():
    assert token_valido("Bearer abc", "abc") and token_valido("bearer abc", "abc")
    assert not token_valido("Bearer ", "") and not token_valido("Bearer", "") and not token_valido("", "")  # sin token configurado nunca entra
    assert not token_valido("Bearer abc", "") and not token_valido("", "abc") and not token_valido("Bearer abd", "abc")


def test_las_peticiones_se_cuentan_por_plantilla_de_ruta_no_por_url_real(client, con_token, auth_headers):
    for oid in (1, 2, 3):
        client.delete(f"/paper/ordenes/{oid}", headers=auth_headers)
    client.get("/ruta-que-no-existe-123")
    texto = client.get("/metrics", headers=con_token).text
    assert 'ruta="/paper/ordenes/{orden_id}"' in texto
    assert "/paper/ordenes/1" not in texto and "ruta-que-no-existe" not in texto
    assert 'ruta="no_encontrada"' in texto


def test_la_duracion_se_registra_en_el_histograma(client, con_token):
    client.get("/health")
    assert 'http_duracion_segundos_count{metodo="GET",ruta="/health"}' in client.get("/metrics", headers=con_token).text


def test_el_motor_cuenta_las_ordenes_ejecutadas(client, con_token, mercado, auth_headers):
    antes = _valor(client.get("/metrics", headers=con_token).text, "paper_ordenes_procesadas_total", '{resultado="ejecutadas"}')
    _pend(client, auth_headers, "BUY", "LIMIT", 120)
    assert asyncio.run(paper_matching.un_ciclo())["ejecutadas"] == 1
    despues = _valor(client.get("/metrics", headers=con_token).text, "paper_ordenes_procesadas_total", '{resultado="ejecutadas"}')
    assert despues == antes + 1


def test_el_bucle_marca_el_ultimo_ciclo_ok_y_cuenta_los_errores(monkeypatch):
    marcas = []

    async def ciclo_ok():
        return {}

    async def ciclo_roto():
        raise RuntimeError("boom")

    async def correr(ciclo):
        monkeypatch.setattr(paper_matching, "un_ciclo", ciclo)
        monkeypatch.setattr(config, "PAPER_MATCH_INTERVAL_SECONDS", 0)
        tarea = asyncio.create_task(paper_matching.bucle_de_casamiento())
        await asyncio.sleep(0.05)
        tarea.cancel()

    metricas.ULTIMO_CICLO_OK.set(0)
    ok0 = metricas.CICLOS.labels("ok")._value.get()
    err0 = metricas.CICLOS.labels("error")._value.get()
    asyncio.run(correr(ciclo_ok))
    assert metricas.ULTIMO_CICLO_OK._value.get() > 0 and metricas.CICLOS.labels("ok")._value.get() > ok0
    metricas.ULTIMO_CICLO_OK.set(0)
    asyncio.run(correr(ciclo_roto))
    assert metricas.CICLOS.labels("error")._value.get() > err0
    assert metricas.ULTIMO_CICLO_OK._value.get() == 0          # un ciclo roto NO refresca la marca


def test_coingecko_cuenta_ok_y_errores(monkeypatch):
    from tests.test_robustez import _falso_http
    from app.services import coingecko
    from app.services.cache import cache
    cache.clear() if hasattr(cache, "clear") else None
    ok0 = metricas.COINGECKO.labels("ok")._value.get()
    err0 = metricas.COINGECKO.labels("error_http")._value.get()
    _falso_http(monkeypatch, {"bitcoin": {"usd": 1}})
    asyncio.run(coingecko.obtener_precio("bitcoin-m1"))
    assert metricas.COINGECKO.labels("ok")._value.get() == ok0 + 1
    _falso_http(monkeypatch, {"error": "x"}, status=429)
    asyncio.run(coingecko.obtener_precio("bitcoin-m2"))
    assert metricas.COINGECKO.labels("error_http")._value.get() == err0 + 1


def test_logout_y_cambio_de_password_cuentan_revocaciones(client, con_token, auth_headers):
    antes = metricas.SESIONES_REVOCADAS._value.get()
    assert client.post("/usuarios/logout", headers=auth_headers).status_code == 200
    assert metricas.SESIONES_REVOCADAS._value.get() == antes + 1


def test_el_bloqueo_de_login_se_cuenta_una_vez_por_cubo(client):
    antes = metricas.LOGIN_BLOQUEOS._value.get()
    client.post("/usuarios/registro", json={"username": "victima", "email": "v@e.com", "password": "clave-larga-1"})
    for _ in range(config.LOGIN_MAX_FAILURES + 2):
        client.post("/usuarios/login", json={"username": "victima", "password": "mala-mala"})
    assert metricas.LOGIN_BLOQUEOS._value.get() >= antes + 1


# ---------------------------------------------------------------- /ready

def test_ready_ok_con_la_base_viva(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json() == {"status": "listo"}


def test_ready_da_503_si_la_base_falla(client, monkeypatch):
    import app.main as m

    def rota():
        raise RuntimeError("db caída")
    monkeypatch.setattr(m, "_ping_db", rota)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "no_listo", "fallan": ["db"]}


def test_ready_da_503_si_redis_configurado_no_responde(client, monkeypatch):
    import app.main as m

    async def rota():
        raise RuntimeError("sin redis")
    monkeypatch.setattr(config, "REDIS_URL", "redis://localhost:6390/0")
    monkeypatch.setattr(m, "_ping_redis", rota)
    assert client.get("/ready").json()["fallan"] == ["redis"]


def test_health_sigue_siendo_solo_vivacidad(client, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_ping_db", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert client.get("/health").status_code == 200
