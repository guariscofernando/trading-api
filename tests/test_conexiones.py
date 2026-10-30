# tests/test_conexiones.py
"""Fase 10: tope de conexiones de chat por usuario, sumando todos los procesos."""
import asyncio
import os
import time
import uuid

import pytest

from app.config import config
from app.services import conexiones
from app.services.conexiones import RegistroLocal, RegistroRedis, crear_registro

URL_REDIS = os.getenv("TEST_REDIS_URL")
necesita_redis = pytest.mark.skipif(not URL_REDIS, reason="Define TEST_REDIS_URL para probar contra un Redis real")


def correr(c):
    return asyncio.run(c)


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ====================================================================== RegistroLocal

def test_el_tope_se_respeta_y_es_por_usuario():
    async def prueba():
        r = RegistroLocal()
        assert [await r.registrar(1, f"c{i}", 3, 60) for i in range(5)] == [True, True, True, False, False]
        assert await r.registrar(2, "otro", 3, 60) is True
        assert r.abiertas(1) == 3 and r.abiertas(2) == 1

    correr(prueba())


def test_liberar_devuelve_el_cupo_y_es_idempotente():
    async def prueba():
        r = RegistroLocal()
        for i in range(2):
            await r.registrar(1, f"c{i}", 2, 60)
        assert await r.registrar(1, "x", 2, 60) is False
        await r.liberar(1, "c0")
        await r.liberar(1, "c0")                    # repetir no rompe ni libera de más
        await r.liberar(9, "nadie")
        assert await r.registrar(1, "x", 2, 60) is True
        assert await r.registrar(1, "y", 2, 60) is False

    correr(prueba())


def test_registrar_dos_veces_la_misma_conexion_no_cuenta_doble():
    async def prueba():
        r = RegistroLocal()
        assert await r.registrar(1, "a", 1, 60) and await r.registrar(1, "a", 1, 60)
        assert r.abiertas(1) == 1

    correr(prueba())


def test_un_registro_sin_renovar_vence_y_renovarlo_lo_mantiene():
    async def prueba():
        reloj = Reloj()
        r = RegistroLocal(reloj)
        await r.registrar(1, "viva", 2, 60)
        await r.registrar(1, "muerta", 2, 60)
        reloj.t += 50
        await r.renovar(1, "viva", 60)             # "viva" sigue; "muerta" no se renovó
        reloj.t += 20                              # 70 s: "muerta" venció, "viva" no
        assert await r.registrar(1, "nueva", 2, 60) is True
        assert r.abiertas(1) == 2
        assert await r.registrar(1, "otra", 2, 60) is False

    correr(prueba())


def test_sin_redis_se_crea_un_registro_local():
    assert type(crear_registro("")) is RegistroLocal
    assert isinstance(crear_registro("redis://127.0.0.1:1/0"), RegistroRedis)


# ====================================================================== RegistroRedis (Redis real)

def _par():
    prefijo = f"t{uuid.uuid4().hex}:"
    return RegistroRedis(URL_REDIS, prefijo), RegistroRedis(URL_REDIS, prefijo), prefijo


@necesita_redis
def test_el_tope_cuenta_las_conexiones_de_todos_los_procesos():
    async def prueba():
        a, b, _ = _par()
        try:
            # 2 procesos intentando 3 conexiones cada uno para el mismo usuario con tope 3
            resultados = [await a.registrar(7, "a1", 3, 60), await b.registrar(7, "b1", 3, 60),
                          await a.registrar(7, "a2", 3, 60), await b.registrar(7, "b2", 3, 60),
                          await a.registrar(7, "a3", 3, 60)]
            assert resultados == [True, True, True, False, False]
            await b.liberar(7, "b1")                                       # liberar en uno devuelve cupo a todos
            assert await a.registrar(7, "a3", 3, 60) is True
        finally:
            await a.cerrar(); await b.cerrar()

    correr(prueba())


@necesita_redis
def test_registros_simultaneos_nunca_superan_el_tope():
    async def prueba():
        a, b, _ = _par()
        try:
            tareas = [(a if i % 2 else b).registrar(5, f"c{i}", 4, 60) for i in range(40)]
            resultados = await asyncio.gather(*tareas)
            assert sum(resultados) == 4
        finally:
            await a.cerrar(); await b.cerrar()

    correr(prueba())


@necesita_redis
def test_un_proceso_que_muere_sin_liberar_no_deja_cupos_fantasma():
    async def prueba():
        a, b, _ = _par()
        try:
            assert await a.registrar(3, "x", 1, 1) is True                 # alquiler de 1 s; "a" muere sin liberar
            assert await b.registrar(3, "y", 1, 1) is False
            await asyncio.sleep(1.3)
            assert await b.registrar(3, "y", 1, 1) is True
        finally:
            await a.cerrar(); await b.cerrar()

    correr(prueba())


@necesita_redis
def test_renovar_mantiene_viva_la_conexion_mas_alla_del_alquiler():
    async def prueba():
        a, b, _ = _par()
        try:
            await a.registrar(3, "x", 1, 1)
            for _ in range(4):
                await asyncio.sleep(0.4)
                await a.renovar(3, "x", 1)
            assert await b.registrar(3, "y", 1, 1) is False                # han pasado 1,6 s > 1 s, pero se renovó
        finally:
            await a.cerrar(); await b.cerrar()

    correr(prueba())


@necesita_redis
def test_las_claves_de_redis_tienen_caducidad_y_se_limpian():
    async def prueba():
        a, _, prefijo = _par()
        try:
            await a.registrar(9, "x", 3, 60)
            ttl = await a._cliente.ttl(f"{prefijo}chatconn:9")
            assert 0 < ttl <= 120
            await a.liberar(9, "x")
            assert await a._cliente.zcard(f"{prefijo}chatconn:9") == 0
        finally:
            await a.cerrar()

    correr(prueba())


@necesita_redis
def test_los_usuarios_y_los_prefijos_no_se_mezclan():
    async def prueba():
        a, b, _ = _par()
        c = RegistroRedis(URL_REDIS, f"otra{uuid.uuid4().hex}:")
        try:
            assert await a.registrar(1, "x", 1, 60) and await a.registrar(2, "x2", 1, 60)
            assert await c.registrar(1, "z", 1, 60) is True
        finally:
            await a.cerrar(); await b.cerrar(); await c.cerrar()

    correr(prueba())


def test_con_redis_caido_se_cuenta_localmente_y_no_se_cae():
    async def prueba():
        r = RegistroRedis("redis://127.0.0.1:1/0")                          # puerto sin servicio
        try:
            assert [await r.registrar(1, f"c{i}", 2, 60) for i in range(3)] == [True, True, False]
            await r.renovar(1, "c0", 60)
            await r.liberar(1, "c0")
            assert await r.registrar(1, "c9", 2, 60) is True
        finally:
            await r.cerrar()

    correr(prueba())


# ====================================================================== integración con el chat

def _token(uid):
    from utils.authorization import create_access_token
    return create_access_token({"sub": str(uid)})


def _usuario(nombre="ana"):
    from app.dao.UserDAO import UserDAO
    return UserDAO().crear_usuario_db(nombre, f"{nombre}@example.com", "x")


def test_el_chat_libera_el_cupo_al_cerrar(client):
    uid = _usuario()
    with client.websocket_connect(f"/ws/chat?token={_token(uid)}") as ws:
        ws.receive_json()
        assert conexiones.registro.abiertas(uid) == 1
    assert conexiones.registro.abiertas(uid) == 0


def test_un_rechazo_por_tope_no_deja_registros(client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(config, "CHAT_MAX_CONNECTIONS_PER_USER", 1)
    uid = _usuario()
    with client.websocket_connect(f"/ws/chat?token={_token(uid)}") as ws:
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/chat?token={_token(uid)}"):
                pass
        assert conexiones.registro.abiertas(uid) == 1
    assert conexiones.registro.abiertas(uid) == 0


def test_mientras_la_conexion_vive_su_registro_se_renueva(client, monkeypatch):
    """Sin el renovador, con un alquiler de 0,3 s la segunda conexión entraría pasado ese tiempo."""
    from starlette.websockets import WebSocketDisconnect
    from app.routers import websocket as ws_mod
    monkeypatch.setattr(config, "CHAT_MAX_CONNECTIONS_PER_USER", 1)
    monkeypatch.setattr(ws_mod, "ALQUILER_CONEXION", 0.3)
    uid = _usuario()
    with client.websocket_connect(f"/ws/chat?token={_token(uid)}") as ws:
        ws.receive_json()
        time.sleep(0.9)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/chat?token={_token(uid)}"):
                pass


def test_si_falla_el_registro_en_el_envio_inicial_igual_se_libera(client, monkeypatch):
    from app.routers import websocket as ws_mod
    uid = _usuario()

    async def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ws_mod.chat_manager, "connect", falla)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/chat?token={_token(uid)}"):
            pass
    assert conexiones.registro.abiertas(uid) == 0
