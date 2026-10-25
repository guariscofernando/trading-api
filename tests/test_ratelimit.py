# tests/test_ratelimit.py
"""Rate limit: IP real detrás de proxies, almacenes (memoria / Redis / respaldo) y middleware."""
import logging
import os
import threading

import pytest

from app.config import config
from app.services.ratelimit import (
    AlmacenConRespaldo,
    AlmacenMemoria,
    AlmacenRedis,
    Limitador,
    crear_limitador,
    ip_cliente,
    limitador,
)


# ============================================================================ IP del cliente

def _scope(peer="10.0.0.9", *xff):
    """Scope ASGI mínimo; cada valor de `xff` es una línea X-Forwarded-For distinta."""
    return {
        "client": (peer, 40000) if peer is not None else None,
        "headers": [(b"x-forwarded-for", v.encode()) for v in xff],
    }


def test_sin_proxies_de_confianza_x_forwarded_for_se_ignora_por_completo():
    # Un cliente directo puede escribir lo que quiera en la cabecera: no debe poder elegir su IP.
    assert ip_cliente(_scope("198.51.100.4", "1.2.3.4"), proxies_confiables=0) == "198.51.100.4"
    assert ip_cliente(_scope("198.51.100.4", "1.2.3.4, 5.6.7.8"), proxies_confiables=0) == "198.51.100.4"


def test_un_proxy_la_ip_real_es_la_ultima_entrada():
    assert ip_cliente(_scope("10.0.0.9", "203.0.113.7"), proxies_confiables=1) == "203.0.113.7"


def test_lo_que_el_cliente_escribe_a_la_izquierda_no_cambia_el_resultado():
    """El cliente antepone entradas falsas; el proxy de confianza añade la real a la derecha."""
    reales = {ip_cliente(_scope("10.0.0.9", f"{falsa}, 203.0.113.7"), proxies_confiables=1)
              for falsa in ("1.1.1.1", "8.8.8.8", "9.9.9.9, 4.4.4.4", "no-es-una-ip")}
    assert reales == {"203.0.113.7"}


def test_dos_proxies_la_ip_real_es_la_penultima():
    # cliente -> proxy1 -> proxy2 -> app : XFF = "cliente, ip_de_proxy1"
    assert ip_cliente(_scope("10.0.0.9", "203.0.113.7, 172.16.0.5"), proxies_confiables=2) == "203.0.113.7"
    assert ip_cliente(_scope("10.0.0.9", "falsa, 203.0.113.7, 172.16.0.5"), proxies_confiables=2) == "203.0.113.7"


def test_varias_lineas_de_cabecera_se_unen_en_orden():
    assert ip_cliente(_scope("10.0.0.9", "falsa", "203.0.113.7"), proxies_confiables=1) == "203.0.113.7"
    assert ip_cliente(_scope("10.0.0.9", "203.0.113.7", "172.16.0.5"), proxies_confiables=2) == "203.0.113.7"


def test_si_faltan_entradas_se_usa_la_direccion_del_socket():
    """La petición no pasó por todos los proxies esperados: no se confía en nada de la cabecera."""
    assert ip_cliente(_scope("198.51.100.4", "203.0.113.7"), proxies_confiables=2) == "198.51.100.4"
    assert ip_cliente(_scope("198.51.100.4"), proxies_confiables=1) == "198.51.100.4"      # sin cabecera


def test_entrada_que_no_es_una_ip_cae_en_la_direccion_del_socket():
    assert ip_cliente(_scope("198.51.100.4", "unknown"), proxies_confiables=1) == "198.51.100.4"
    assert ip_cliente(_scope("198.51.100.4", "<script>"), proxies_confiables=1) == "198.51.100.4"


def test_acepta_puerto_y_ipv6_entre_corchetes():
    assert ip_cliente(_scope("10.0.0.9", "203.0.113.7:51234"), proxies_confiables=1) == "203.0.113.7"
    assert ip_cliente(_scope("10.0.0.9", '[2001:db8:1:2::9]:443'), proxies_confiables=1) == "2001:db8:1:2::/64"


def test_ipv6_se_agrupa_por_64_y_ipv4_mapeada_es_ipv4():
    a = ip_cliente(_scope("2001:db8:aaaa:1::1"), proxies_confiables=0)
    b = ip_cliente(_scope("2001:db8:aaaa:1:ffff:ffff:ffff:ffff"), proxies_confiables=0)
    otra = ip_cliente(_scope("2001:db8:aaaa:2::1"), proxies_confiables=0)
    assert a == b == "2001:db8:aaaa:1::/64"
    assert otra != a
    assert ip_cliente(_scope("::ffff:203.0.113.7"), proxies_confiables=0) == "203.0.113.7"


def test_direccion_ausente_o_no_ip():
    assert ip_cliente(_scope(None), proxies_confiables=0) == "desconocida"
    assert ip_cliente(_scope("testclient"), proxies_confiables=0) == "testclient"
    assert len(ip_cliente(_scope("x" * 500), proxies_confiables=0)) <= 64


def test_usa_la_configuracion_cuando_no_se_pasa_el_numero_de_proxies(monkeypatch):
    s = _scope("10.0.0.9", "falsa, 203.0.113.7")
    assert ip_cliente(s) == "10.0.0.9"
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    assert ip_cliente(s) == "203.0.113.7"


# ============================================================================ memoria

class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_memoria_cuenta_y_reinicia_la_ventana():
    reloj = Reloj()
    m = AlmacenMemoria(reloj=reloj)
    assert m.incrementar("k", 60) == (1, 60)
    reloj.t += 10
    assert m.incrementar("k", 60) == (2, 50)          # la ventana NO se prolonga con cada petición
    assert m.consultar("k") == (2, 50)
    reloj.t += 50                                     # justo al vencer, vuelve a empezar
    assert m.consultar("k") == (0, 0)
    assert m.incrementar("k", 60) == (1, 60)


def test_memoria_claves_independientes_borrar_y_vaciar():
    m = AlmacenMemoria(reloj=Reloj())
    m.incrementar("a", 60), m.incrementar("a", 60), m.incrementar("b", 60)
    assert m.consultar("a")[0] == 2 and m.consultar("b")[0] == 1
    m.borrar("a")
    assert m.consultar("a") == (0, 0) and m.consultar("b")[0] == 1
    m.borrar("no-existe")                             # no falla
    m.vaciar()
    assert len(m) == 0


def test_memoria_consultar_no_suma():
    m = AlmacenMemoria(reloj=Reloj())
    for _ in range(5):
        assert m.consultar("k") == (0, 0)
    assert m.incrementar("k", 60)[0] == 1


def test_memoria_limpia_las_claves_vencidas():
    """Antes cada IP vista quedaba guardada para siempre."""
    reloj = Reloj()
    m = AlmacenMemoria(reloj=reloj)
    for i in range(500):
        m.incrementar(f"ip:{i}", 60)
    assert len(m) == 500
    reloj.t += 3600
    m.incrementar("nueva", 60)                        # el barrido ocurre en la siguiente operación
    assert len(m) == 1


def test_memoria_nunca_supera_su_tope_aunque_todas_las_claves_esten_vivas():
    reloj = Reloj()
    m = AlmacenMemoria(max_claves=100, reloj=reloj)
    for i in range(5000):                             # 5.000 IPs distintas, todas dentro de su ventana
        reloj.t += 0.001
        m.incrementar(f"ip:{i}", 3600)
        assert len(m) <= 100
    assert m.consultar("ip:4999")[0] == 1             # las más recientes se conservan


def test_memoria_descarta_primero_las_que_antes_vencen():
    reloj = Reloj()
    m = AlmacenMemoria(max_claves=10, reloj=reloj)
    m.incrementar("corta", 5)
    for i in range(9):
        m.incrementar(f"larga:{i}", 3600)
    m.incrementar("empuja", 3600)                     # desborda: sale la de vencimiento más próximo
    assert m.consultar("corta") == (0, 0)
    assert m.consultar("larga:0")[0] == 1


def test_memoria_es_segura_entre_hilos():
    m = AlmacenMemoria()
    hilos = [threading.Thread(target=lambda: [m.incrementar("k", 60) for _ in range(2000)]) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert m.consultar("k")[0] == 16000


# ============================================================================ limitador

def test_limitador_permite_hasta_el_limite_y_bloquea_despues():
    lim = Limitador(AlmacenMemoria(reloj=Reloj()))
    resultados = [lim.golpear("ip", 3, 60) for _ in range(5)]
    assert [r.permitido for r in resultados] == [True, True, True, False, False]
    assert [r.restante for r in resultados] == [2, 1, 0, 0, 0]
    assert resultados[0].limite == 3 and 1 <= resultados[3].reinicia_en <= 60


def test_limitador_se_recupera_al_terminar_la_ventana():
    reloj = Reloj()
    lim = Limitador(AlmacenMemoria(reloj=reloj))
    [lim.golpear("ip", 2, 60) for _ in range(3)]
    assert lim.golpear("ip", 2, 60).permitido is False
    reloj.t += 61
    assert lim.golpear("ip", 2, 60).permitido is True


# ============================================================================ Redis

def _redis_falso():
    import fakeredis
    return AlmacenRedis(fakeredis.FakeRedis())


def _redis_real():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Define TEST_REDIS_URL (p. ej. redis://localhost:6379/15) para probar contra un Redis real")
    almacen = AlmacenRedis.desde_url(url)
    try:
        almacen._r.ping()
    except Exception:
        pytest.skip(f"No hay un Redis accesible en {url}")
    almacen.vaciar()
    return almacen


@pytest.fixture(params=["fakeredis", "redis-real"])
def redis(request):
    almacen = _redis_falso() if request.param == "fakeredis" else _redis_real()
    yield almacen
    almacen.vaciar()


def test_redis_cuenta_con_caducidad(redis):
    assert redis.incrementar("k", 30) == (1, 30)
    contador, restante = redis.incrementar("k", 30)
    assert contador == 2 and 29 <= restante <= 30
    assert redis.consultar("k")[0] == 2
    ttl = redis._r.pttl("trading-api:rl:k")
    assert 0 < ttl <= 30_000                           # la clave SIEMPRE caduca (no queda bloqueo eterno)


def test_redis_la_caducidad_se_fija_en_la_misma_transaccion_atomica(redis):
    """
    No debe depender de un EXPIRE posterior: si el proceso muriera entre la creación de la clave y ese
    EXPIRE, quedaría un contador sin caducidad que bloquearía a esa IP para siempre.
    """
    llamadas = []
    original = redis._r.expire
    redis._r.expire = lambda *a, **k: (llamadas.append(a), original(*a, **k))[1]
    try:
        redis.incrementar("nueva", 30)
        redis.incrementar("nueva", 30)
    finally:
        redis._r.expire = original
    assert llamadas == []
    assert 0 < redis._r.pttl("trading-api:rl:nueva") <= 30_000


def test_redis_consultar_no_suma_y_borrar_olvida(redis):
    assert redis.consultar("k") == (0, 0)
    redis.incrementar("k", 30)
    assert redis.consultar("k")[0] == 1 and redis.consultar("k")[0] == 1
    redis.borrar("k")
    assert redis.consultar("k") == (0, 0)


def test_redis_la_ventana_se_reinicia_al_caducar(redis):
    import time
    redis.incrementar("k", 1)
    redis.incrementar("k", 1)
    time.sleep(1.2)
    assert redis.consultar("k") == (0, 0)
    assert redis.incrementar("k", 1)[0] == 1


def test_redis_repara_una_clave_sin_caducidad(redis):
    """Una clave sin TTL bloquearía para siempre: al contarla se le pone caducidad."""
    redis._r.set("trading-api:rl:huerfana", 7)
    contador, restante = redis.incrementar("huerfana", 40)
    assert contador == 8 and 1 <= restante <= 40
    assert 0 < redis._r.pttl("trading-api:rl:huerfana") <= 40_000


def test_redis_vaciar_solo_borra_las_claves_del_limitador(redis):
    redis._r.set("otra-aplicacion:dato", "importante")
    redis.incrementar("a", 30), redis.incrementar("b", 30)
    redis.vaciar()
    assert redis.consultar("a") == (0, 0) and redis.consultar("b") == (0, 0)
    assert redis._r.get("otra-aplicacion:dato") == b"importante"
    redis._r.delete("otra-aplicacion:dato")


def test_redis_es_exacto_con_muchos_hilos(redis):
    hilos = [threading.Thread(target=lambda: [redis.incrementar("k", 60) for _ in range(100)]) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert redis.consultar("k")[0] == 800


def test_redis_y_memoria_dan_los_mismos_resultados(redis):
    memoria = AlmacenMemoria()
    for _ in range(6):
        assert redis.incrementar("k", 60)[0] == memoria.incrementar("k", 60)[0]
    assert Limitador(redis).golpear("z", 3, 60).permitido is True


# ============================================================================ respaldo

class RedisCaido:
    bloqueante = True

    def __init__(self):
        self.llamadas = 0

    def _falla(self, *a):
        self.llamadas += 1
        raise ConnectionError("Redis no responde")

    incrementar = consultar = borrar = vaciar = _falla


def test_si_redis_falla_se_usa_la_memoria_local_y_se_avisa_una_sola_vez(caplog):
    reloj = Reloj()
    caido = RedisCaido()
    almacen = AlmacenConRespaldo(caido, AlmacenMemoria(reloj=reloj), pausa=5, reloj=reloj)
    with caplog.at_level(logging.WARNING, logger="trading-api"):
        assert [almacen.incrementar("k", 60)[0] for _ in range(3)] == [1, 2, 3]   # sigue contando
    assert almacen.degradado is True
    assert caido.llamadas == 1                          # durante la pausa no se vuelve a llamar a Redis
    assert sum("Redis no responde" in r.message for r in caplog.records) == 1


def test_tras_la_pausa_reintenta_y_cuando_redis_vuelve_lo_usa(caplog):
    import fakeredis
    reloj = Reloj()
    sano = AlmacenRedis(fakeredis.FakeRedis())
    almacen = AlmacenConRespaldo(RedisCaido(), AlmacenMemoria(reloj=reloj), pausa=5, reloj=reloj)
    almacen.incrementar("k", 60)
    assert almacen.degradado
    almacen.principal = sano                             # Redis se recupera
    reloj.t += 4
    assert almacen.incrementar("k", 60)[0] == 2          # aún dentro de la pausa: sigue en local
    reloj.t += 2
    with caplog.at_level(logging.INFO, logger="trading-api"):
        assert almacen.incrementar("k", 60)[0] == 1      # ya usa Redis (contador propio)
    assert almacen.degradado is False
    assert any("disponible de nuevo" in r.message for r in caplog.records)


def test_borrar_olvida_tambien_el_contador_local():
    reloj = Reloj()
    almacen = AlmacenConRespaldo(RedisCaido(), AlmacenMemoria(reloj=reloj), pausa=1, reloj=reloj)
    almacen.incrementar("k", 60)
    almacen.borrar("k")
    assert almacen.consultar("k") == (0, 0)


def test_redis_inalcanzable_de_verdad_no_rompe_el_limitador():
    """Sin mocks: un puerto donde no escucha nada (conexión rechazada)."""
    lim = crear_limitador("redis://127.0.0.1:1/0")
    resultados = [lim.golpear("ip", 2, 60).permitido for _ in range(4)]
    assert resultados == [True, True, False, False]
    assert lim.almacen.degradado is True


@pytest.mark.parametrize("url", ["", "esto-no-es-una-url", "http://localhost:6379"])
def test_crear_limitador_con_url_vacia_o_invalida_usa_memoria(url):
    lim = crear_limitador(url)
    assert lim.golpear("k", 5, 60).permitido is True


# ============================================================================ middleware

def _pedir(client, n, **kw):
    return [client.get("/info", **kw).status_code for _ in range(n)]


def test_101_peticiones_desde_la_misma_ip_la_ultima_recibe_429(client):
    codigos = _pedir(client, 101)
    assert codigos[:100] == [200] * 100 and codigos[100] == 429


def test_la_respuesta_429_dice_cuanto_esperar(client):
    _pedir(client, 100)
    r = client.get("/info")
    assert r.status_code == 429
    espera = int(r.headers["Retry-After"])
    assert 1 <= espera <= 60
    assert f"{espera} segundos" in r.json()["detail"]
    assert r.headers["X-RateLimit-Remaining"] == "0" and r.headers["X-RateLimit-Limit"] == "100"


def test_las_respuestas_normales_informan_del_cupo(client):
    primera, segunda = client.get("/info"), client.get("/info")
    assert primera.headers["X-RateLimit-Limit"] == "100"
    assert primera.headers["X-RateLimit-Remaining"] == "99" and segunda.headers["X-RateLimit-Remaining"] == "98"
    assert 1 <= int(primera.headers["X-RateLimit-Reset"]) <= 60


def test_health_no_gasta_cupo(client):
    """Los health checks de la plataforma llegan cada pocos segundos, a veces desde la misma IP."""
    assert _pedir_ruta(client, "/health", 300) == [200] * 300
    assert client.get("/info").headers["X-RateLimit-Remaining"] == "99"


def _pedir_ruta(client, ruta, n):
    return [client.get(ruta).status_code for _ in range(n)]


def test_el_429_lleva_cabeceras_cors_para_que_el_navegador_pueda_leerlo(client):
    """El limitador debe quedar POR DENTRO de CORS; si no, el navegador ve un error de red."""
    origen = config.CORS_ORIGINS[0]
    _pedir(client, 100)
    r = client.get("/info", headers={"Origin": origen})
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == origen
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_el_preflight_cors_no_cuenta(client):
    origen = config.CORS_ORIGINS[0]
    cabeceras = {"Origin": origen, "Access-Control-Request-Method": "GET"}
    assert [client.options("/info", headers=cabeceras).status_code for _ in range(150)] == [200] * 150
    assert client.get("/info").headers["X-RateLimit-Remaining"] == "99"


def test_detras_de_un_proxy_cada_cliente_tiene_su_propio_cupo(client, monkeypatch):
    """Antes: 120 usuarios distintos compartían la IP del proxy y desde el 101 recibían 429."""
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    codigos = [client.get("/info", headers={"X-Forwarded-For": f"203.0.113.{i % 120}"}).status_code
               for i in range(240)]                       # 120 clientes x 2 peticiones
    assert codigos == [200] * 240


def test_sin_confiar_en_proxies_el_cupo_es_el_del_socket_y_la_cabecera_no_sirve_para_evadirlo(client):
    codigos = [client.get("/info", headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
               for i in range(101)]
    assert codigos[-1] == 429


def test_con_un_proxy_de_confianza_no_se_puede_evadir_falsificando_la_cabecera(client, monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    # el atacante cambia la parte izquierda en cada petición; el proxy siempre añade su IP real a la derecha
    codigos = [client.get("/info", headers={"X-Forwarded-For": f"{i}.{i}.{i}.{i}, 198.51.100.77"}).status_code
               for i in range(1, 102)]
    assert codigos[:100] == [200] * 100 and codigos[100] == 429


def test_un_cliente_bloqueado_no_afecta_a_otro(client, monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    abusador = {"X-Forwarded-For": "198.51.100.1"}
    _pedir(client, 101, headers=abusador)
    assert client.get("/info", headers=abusador).status_code == 429
    assert client.get("/info", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200


def test_el_limite_es_configurable(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 5)
    assert _pedir(client, 6) == [200] * 5 + [429]


def test_limite_estricto_en_login_cuenta_aunque_las_credenciales_sean_malas(client):
    codigos = [client.post("/usuarios/login", json={"username": f"user{i}", "password": "incorrecta"}).status_code
               for i in range(21)]
    assert codigos[:20] == [401] * 20 and codigos[20] == 429
    assert "Retry-After" in client.post("/usuarios/login", json={"username": "x", "password": "y"}).headers


def test_limite_estricto_en_registro(client):
    codigos = [client.post("/usuarios/registro", json={
        "username": f"nuevo{i}", "email": f"nuevo{i}@example.com", "password": "password-123"}).status_code
        for i in range(11)]
    assert codigos[:10] == [201] * 10 and codigos[10] == 429


def test_un_fallo_del_limitador_no_tumba_la_api(client, monkeypatch, caplog):
    def roto(*a, **k):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(limitador.almacen, "incrementar", roto)
    with caplog.at_level(logging.ERROR, logger="trading-api"):
        assert client.get("/info").status_code == 200
    assert any("error al evaluar" in r.message for r in caplog.records)


def test_con_redis_caido_la_api_responde_y_sigue_limitando_en_local(client, monkeypatch):
    degradado = AlmacenConRespaldo(RedisCaido(), AlmacenMemoria(), pausa=60)
    monkeypatch.setattr(limitador, "almacen", degradado)
    assert _pedir(client, 101) == [200] * 100 + [429]
    assert degradado.degradado is True


def test_el_middleware_funciona_con_un_almacen_redis(client, monkeypatch, redis):
    """Camino de Redis: la evaluación corre en un hilo para no bloquear el bucle de eventos."""
    monkeypatch.setattr(limitador, "almacen", redis)
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 4)
    assert _pedir(client, 5) == [200] * 4 + [429]
    assert redis.consultar("global:testclient")[0] == 5


def test_se_ve_la_ip_resuelta_en_el_log_para_poder_comprobar_la_configuracion(client, monkeypatch, caplog):
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    with caplog.at_level(logging.INFO, logger="trading-api"):
        client.get("/info", headers={"X-Forwarded-For": "falsa, 203.0.113.7"})
    assert any("ip=203.0.113.7" in r.message for r in caplog.records)
    assert not any("falsa" in r.message for r in caplog.records)


# ============================================================================ WebSockets

def _conectar_ws(client, headers=None):
    """Abre y cierra una conexión a /ws/chat. Devuelve True si se aceptó, False si el handshake se rechazó."""
    from starlette.websockets import WebSocketDisconnect
    try:
        with client.websocket_connect("/ws/chat", headers=headers or {}):
            return True
    except WebSocketDisconnect:
        return False


def test_los_websockets_tambien_gastan_cupo(client, monkeypatch):
    """Antes el middleware solo miraba peticiones http: las conexiones WebSocket no tenían ningún límite."""
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 3)
    assert [_conectar_ws(client) for _ in range(5)] == [True, True, True, False, False]


def test_websocket_y_http_comparten_el_cupo_de_la_misma_ip(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 3)
    assert _pedir(client, 2) == [200, 200]
    assert _conectar_ws(client) is True            # la tercera del cupo
    assert _pedir(client, 1) == [429]              # el cupo ya se gastó entre http y WebSocket
    assert _conectar_ws(client) is False


def test_un_websocket_rechazado_no_afecta_a_otra_ip(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)
    ip_a, ip_b = {"X-Forwarded-For": "203.0.113.1"}, {"X-Forwarded-For": "203.0.113.2"}
    assert [_conectar_ws(client, ip_a) for _ in range(3)] == [True, True, False]
    assert _conectar_ws(client, ip_b) is True


def test_el_websocket_rechazado_queda_en_el_log(client, monkeypatch, caplog):
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 1)
    _conectar_ws(client)
    with caplog.at_level(logging.WARNING, logger="trading-api"):
        assert _conectar_ws(client) is False
    assert any("WebSocket rechazada" in r.getMessage() and "/ws/chat" in r.getMessage() for r in caplog.records)


def test_websocket_con_redis_caido_sigue_limitando_en_local(client, monkeypatch):
    """Con Redis caído el limitador de WebSockets usa el respaldo en memoria, igual que el de http."""
    degradado = AlmacenConRespaldo(RedisCaido(), AlmacenMemoria(), pausa=60)
    monkeypatch.setattr(limitador, "almacen", degradado)
    monkeypatch.setattr(config, "RATE_LIMIT_REQUESTS", 2)
    assert [_conectar_ws(client) for _ in range(3)] == [True, True, False]
    assert degradado.degradado is True
