# tests/test_bus.py
"""Fase 9: bus de mensajes entre procesos (chat, notificaciones y vaciado de caché con varios workers)."""
import asyncio
import os
import shutil
import socket
import subprocess
import time
import uuid
from decimal import Decimal

import pytest

from app.config import Config
from app.services import bus as modulo_bus
from app.services.bus import BusLocal, BusRedis, crear_bus
from tests.test_config_ratelimit import _cfg

URL_REDIS = os.getenv("TEST_REDIS_URL")
necesita_redis = pytest.mark.skipif(not URL_REDIS, reason="Define TEST_REDIS_URL para probar contra un Redis real")


def correr(corrutina):
    return asyncio.run(corrutina)


# ====================================================================== BusLocal

def test_el_bus_local_entrega_a_los_manejadores_del_canal():
    async def prueba():
        b, recibido = BusLocal(), []

        async def m(mensaje):
            recibido.append(mensaje)

        b.registrar("a", m)
        await b.publicar("a", {"x": 1})
        await b.publicar("otro", {"x": 2})            # canal sin manejadores: se ignora
        assert recibido == [{"x": 1}]

    correr(prueba())


def test_un_manejador_que_falla_no_impide_que_los_demas_reciban():
    async def prueba():
        b, recibido = BusLocal(), []

        async def malo(_):
            raise RuntimeError("fallo")

        async def bueno(m):
            recibido.append(m)

        b.registrar("a", malo)
        b.registrar("a", bueno)
        await b.publicar("a", {"ok": True})
        assert recibido == [{"ok": True}]

    correr(prueba())


def test_sin_redis_se_crea_un_bus_local_y_con_redis_uno_de_redis():
    assert type(crear_bus("")) is BusLocal
    b = crear_bus("redis://localhost:1/0")
    assert isinstance(b, BusRedis)
    correr(b.detener())


# ====================================================================== integración con la app (bus local)

def test_las_notificaciones_pasan_por_el_bus_y_llegan_al_websocket(client, auth_headers):
    from app.dao.UserDAO import UserDAO
    from utils.authorization import create_access_token
    uid = UserDAO().obtener_usuario_por_username("tradetester")["id"]
    token = create_access_token({"sub": str(uid)})
    with client.websocket_connect(f"/ws/notificaciones?token={token}") as ws:
        assert ws.receive_json()["tipo"] == "conexion"
        r = client.post("/trades/", headers=auth_headers, json={"tipo": "compra", "activo": "BTC", "precio": 100, "cantidad": 1})
        assert r.status_code == 201, r.text
        assert ws.receive_json()["tipo"] == "nuevo_trade"


def test_vaciar_el_cache_se_publica_en_el_bus_para_los_demas_procesos(client, monkeypatch):
    from app.dao.UserDAO import UserDAO
    from app.services.cache import cache
    publicados = []
    original = modulo_bus.bus.publicar

    async def espia(canal, mensaje):
        publicados.append(canal)
        await original(canal, mensaje)

    monkeypatch.setattr(modulo_bus.bus, "publicar", espia)
    cache.set("k", 1, ttl_seconds=60)
    admin = _admin(client)
    assert client.delete("/precios/cache/clear", headers=admin).status_code == 200
    assert publicados == ["cache_clear"] and cache.get("k") is None


def test_un_mensaje_cache_clear_que_llega_por_el_bus_vacia_el_cache_local():
    from app.services.cache import cache
    cache.set("k", 1, ttl_seconds=60)
    correr(modulo_bus.bus.publicar("cache_clear", {}))
    assert cache.get("k") is None


def _admin(client):
    from app.dao.UserDAO import UserDAO
    from tests.conftest import crear_usuario_y_login
    headers, _ = crear_usuario_y_login(client, "rooty", "rooty@example.com")
    UserDAO().cambiar_rol("rooty", "admin")
    return headers


# ====================================================================== configuración de procesos

def test_varios_workers_sin_redis_impiden_arrancar():
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        _cfg(WEB_CONCURRENCY=2, REDIS_URL="").validate()


def test_varios_workers_con_redis_son_validos():
    _cfg(WEB_CONCURRENCY=4, REDIS_URL="redis://localhost:6379/0").validate()


@pytest.mark.parametrize("valor", [0, -1, 65])
def test_workers_fuera_de_rango(valor):
    with pytest.raises(RuntimeError, match="WEB_CONCURRENCY"):
        _cfg(WEB_CONCURRENCY=valor, REDIS_URL="redis://localhost:6379/0").validate()


def test_un_worker_sin_redis_sigue_siendo_valido():
    _cfg(WEB_CONCURRENCY=1, REDIS_URL="").validate()


# ====================================================================== BusRedis contra un Redis real

def _par(prefijo):
    """Dos 'procesos' (dos buses con su propia suscripción) que comparten Redis."""
    return BusRedis(URL_REDIS, prefijo=prefijo, espera_inicial=0.1), BusRedis(URL_REDIS, prefijo=prefijo, espera_inicial=0.1)


async def _esperar(condicion, segundos=3.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.02)
    return False


def _manejador(lista):
    async def m(mensaje):
        lista.append(mensaje)
    return m


@necesita_redis
def test_un_mensaje_publicado_en_un_proceso_llega_a_todos_exactamente_una_vez():
    async def prueba():
        a, b = _par(f"t{uuid.uuid4().hex}:")
        ra, rb = [], []
        a.registrar("chat", _manejador(ra))
        b.registrar("chat", _manejador(rb))
        await a.iniciar(); await b.iniciar()
        try:
            assert await _esperar(lambda: a.conectado and b.conectado)
            await a.publicar("chat", {"n": 1})
            await b.publicar("chat", {"n": 2})
            assert await _esperar(lambda: len(ra) == 2 and len(rb) == 2)
            await asyncio.sleep(0.3)                                  # margen para detectar duplicados
            assert sorted(m["n"] for m in ra) == [1, 2] and sorted(m["n"] for m in rb) == [1, 2]
        finally:
            await a.detener(); await b.detener()

    correr(prueba())


@necesita_redis
def test_los_canales_estan_aislados_y_el_orden_se_conserva():
    async def prueba():
        a, b = _par(f"t{uuid.uuid4().hex}:")
        chat, notif = [], []
        b.registrar("chat", _manejador(chat))
        b.registrar("notif", _manejador(notif))
        a.registrar("chat", _manejador([]))
        a.registrar("notif", _manejador([]))
        await a.iniciar(); await b.iniciar()
        try:
            assert await _esperar(lambda: a.conectado and b.conectado)
            for i in range(20):
                await a.publicar("chat", {"i": i})
            await a.publicar("notif", {"x": 1})
            assert await _esperar(lambda: len(chat) == 20 and len(notif) == 1)
            assert [m["i"] for m in chat] == list(range(20)) and notif == [{"x": 1}]
        finally:
            await a.detener(); await b.detener()

    correr(prueba())


@necesita_redis
def test_dos_aplicaciones_con_distinto_prefijo_no_se_mezclan():
    async def prueba():
        a = BusRedis(URL_REDIS, prefijo=f"A{uuid.uuid4().hex}:", espera_inicial=0.1)
        b = BusRedis(URL_REDIS, prefijo=f"B{uuid.uuid4().hex}:", espera_inicial=0.1)
        rb = []
        a.registrar("chat", _manejador([]))
        b.registrar("chat", _manejador(rb))
        await a.iniciar(); await b.iniciar()
        try:
            assert await _esperar(lambda: a.conectado and b.conectado)
            await a.publicar("chat", {"x": 1})
            await asyncio.sleep(0.3)
            assert rb == []
        finally:
            await a.detener(); await b.detener()

    correr(prueba())


@necesita_redis
def test_un_mensaje_ilegible_se_descarta_y_la_suscripcion_sigue_viva():
    async def prueba():
        prefijo = f"t{uuid.uuid4().hex}:"
        a = BusRedis(URL_REDIS, prefijo=prefijo, espera_inicial=0.1)
        ra = []
        a.registrar("chat", _manejador(ra))
        await a.iniciar()
        try:
            assert await _esperar(lambda: a.conectado)
            await a._cliente.publish(prefijo + "chat", "esto no es json {{{")
            await a.publicar("chat", {"ok": 1})
            assert await _esperar(lambda: ra == [{"ok": 1}])
        finally:
            await a.detener()

    correr(prueba())


@necesita_redis
def test_los_valores_no_json_se_convierten_a_texto_en_vez_de_romper():
    async def prueba():
        a = BusRedis(URL_REDIS, prefijo=f"t{uuid.uuid4().hex}:", espera_inicial=0.1)
        ra = []
        a.registrar("notif", _manejador(ra))
        await a.iniciar()
        try:
            assert await _esperar(lambda: a.conectado)
            await a.publicar("notif", {"precio": Decimal("1.50")})
            assert await _esperar(lambda: ra == [{"precio": "1.50"}])
        finally:
            await a.detener()

    correr(prueba())


@necesita_redis
def test_un_manejador_que_falla_no_mata_la_suscripcion():
    async def prueba():
        a = BusRedis(URL_REDIS, prefijo=f"t{uuid.uuid4().hex}:", espera_inicial=0.1)
        ra = []

        async def malo(_):
            raise RuntimeError("fallo")

        a.registrar("chat", malo)
        a.registrar("chat", _manejador(ra))
        await a.iniciar()
        try:
            assert await _esperar(lambda: a.conectado)
            await a.publicar("chat", {"n": 1})
            await a.publicar("chat", {"n": 2})
            assert await _esperar(lambda: len(ra) == 2)
        finally:
            await a.detener()

    correr(prueba())


def test_con_redis_inalcanzable_se_entrega_localmente_y_no_se_cae():
    async def prueba():
        a = BusRedis("redis://127.0.0.1:1/0", espera_inicial=0.05)       # puerto sin servicio
        ra = []
        a.registrar("chat", _manejador(ra))
        await a.iniciar()
        try:
            await asyncio.sleep(0.2)
            assert a.conectado is False
            await a.publicar("chat", {"n": 1})                           # no lanza
            assert ra == [{"n": 1}]                                      # y llega a los clientes de este proceso
        finally:
            await a.detener()

    correr(prueba())


def test_antes_de_estar_suscrito_el_proceso_no_pierde_sus_propios_mensajes():
    async def prueba():
        a = BusRedis(URL_REDIS or "redis://127.0.0.1:1/0", espera_inicial=0.1)
        ra = []
        a.registrar("chat", _manejador(ra))
        await a.publicar("chat", {"n": 1})        # sin iniciar(): no hay suscripción todavía
        assert ra == [{"n": 1}]
        await a.detener()

    correr(prueba())


@pytest.mark.skipif(not shutil.which("redis-server"), reason="redis-server no está instalado")
def test_la_suscripcion_se_recupera_sola_cuando_vuelve_redis(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]

    def arrancar():
        p = subprocess.Popen(["redis-server", "--port", str(puerto), "--save", "", "--dir", str(tmp_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            with socket.socket() as c:
                if c.connect_ex(("127.0.0.1", puerto)) == 0:
                    return p
            time.sleep(0.1)
        p.kill()
        raise RuntimeError("redis no arrancó")

    async def prueba():
        servidor = arrancar()
        a = BusRedis(f"redis://127.0.0.1:{puerto}/0", espera_inicial=0.1)
        b = BusRedis(f"redis://127.0.0.1:{puerto}/0", espera_inicial=0.1)
        ra, rb = [], []
        a.registrar("chat", _manejador(ra))
        b.registrar("chat", _manejador(rb))
        await a.iniciar(); await b.iniciar()
        try:
            assert await _esperar(lambda: a.conectado and b.conectado)
            servidor.kill(); servidor.wait()
            assert await _esperar(lambda: not a.conectado and not b.conectado, 8)
            await a.publicar("chat", {"fase": "caido"})                  # degrada: solo a este proceso
            assert ra == [{"fase": "caido"}] and rb == []
            servidor = arrancar()
            assert await _esperar(lambda: a.conectado and b.conectado, 15), "no se reconectó"
            await a.publicar("chat", {"fase": "vuelto"})
            assert await _esperar(lambda: {"fase": "vuelto"} in rb)      # y vuelve a llegar al otro proceso
        finally:
            await a.detener(); await b.detener()
            servidor.kill(); servidor.wait()

    correr(prueba())
