# tests/test_chat_y_roles.py
"""Fase 5: chat autenticado y con límite de mensajes, y rol de administrador para el caché."""
import subprocess
import sys
from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.config import config
from app.dao.UserDAO import UserDAO
from app.database import engine
from app.routers.websocket import chat_manager
from app.services.cache import cache
from tests.conftest import RAIZ, alembic_config, crear_usuario_y_login
from utils.authorization import create_access_token

dao = UserDAO()


def _token(user_id, **kw):
    return create_access_token({"sub": str(user_id)}, **kw)


def _crear(username):
    return dao.crear_usuario_db(username, f"{username}@example.com", "x")


def _rechazado(client, ruta):
    """Devuelve el código con el que se cerró el handshake (o None si se aceptó)."""
    try:
        with client.websocket_connect(ruta):
            return None
    except WebSocketDisconnect as e:
        return e.code


@pytest.fixture(autouse=True)
def _chat_limpio():
    chat_manager.conexiones.clear()
    yield
    chat_manager.conexiones.clear()


# ================================================================== chat: autenticación

def test_el_chat_rechaza_sin_token(client):
    assert _rechazado(client, "/ws/chat") == 1008


def test_el_chat_rechaza_token_basura(client):
    assert _rechazado(client, "/ws/chat?token=esto.no.es.un.jwt") == 1008


def test_el_chat_rechaza_token_caducado(client):
    uid = _crear("ana")
    assert _rechazado(client, f"/ws/chat?token={_token(uid, expires_delta=timedelta(seconds=-5))}") == 1008


def test_el_chat_rechaza_token_de_usuario_que_ya_no_existe(client):
    assert _rechazado(client, f"/ws/chat?token={_token(99999)}") == 1008


def test_el_chat_rechaza_token_sin_sub_o_con_sub_no_numerico(client):
    assert _rechazado(client, f"/ws/chat?token={create_access_token({'otro': 1})}") == 1008
    assert _rechazado(client, f"/ws/chat?token={create_access_token({'sub': 'abc'})}") == 1008


def test_el_chat_acepta_token_valido_y_saluda(client):
    uid = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(uid)}") as ws:
        assert ws.receive_json()["tipo"] == "conexion"


def test_los_mensajes_llevan_el_autor_del_token_y_llegan_a_todos(client):
    ana, beto = _crear("ana"), _crear("beto")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a, \
         client.websocket_connect(f"/ws/chat?token={_token(beto)}") as b:
        a.receive_json(), b.receive_json()
        a.send_text("hola a todos")
        assert a.receive_json() == {"tipo": "mensaje", "usuario": "ana", "mensaje": "hola a todos"}
        assert b.receive_json() == {"tipo": "mensaje", "usuario": "ana", "mensaje": "hola a todos"}


def test_el_cliente_no_puede_suplantar_a_otro_usuario(client):
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text('{"usuario": "admin", "mensaje": "soy admin"}')
        recibido = a.receive_json()
        assert recibido["usuario"] == "ana"          # el autor sale del token, nunca del texto


def test_los_mensajes_del_chat_no_llegan_a_quien_solo_ve_precios(client):
    """Antes el chat y /ws/precios compartían la lista de conexiones."""
    from app.routers.websocket import manager
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        assert manager.active_connections == []
        assert len(chat_manager.conexiones) == 1


# ================================================================== chat: límites

def test_el_exceso_de_mensajes_se_descarta_con_aviso(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_MESSAGES", 2)
    ana, beto = _crear("ana"), _crear("beto")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a, \
         client.websocket_connect(f"/ws/chat?token={_token(beto)}") as b:
        a.receive_json(), b.receive_json()
        for i in range(4):
            a.send_text(f"m{i}")
        respuestas = [a.receive_json() for _ in range(4)]
        assert [r["tipo"] for r in respuestas] == ["mensaje", "mensaje", "error", "error"]
        assert respuestas[2]["reintentar_en"] >= 1
        # Beto solo recibió los 2 permitidos
        assert [b.receive_json()["mensaje"] for _ in range(2)] == ["m0", "m1"]
        b.send_text("yo sí puedo")                    # su cupo es independiente del de Ana
        assert b.receive_json()["mensaje"] == "yo sí puedo"


def test_el_limite_es_por_usuario_no_por_conexion(client, monkeypatch):
    """Abrir otra pestaña no debe dar otro cupo."""
    monkeypatch.setattr(config, "CHAT_MAX_MESSAGES", 2)
    ana = _crear("ana")
    t = _token(ana)
    with client.websocket_connect(f"/ws/chat?token={t}") as a1, client.websocket_connect(f"/ws/chat?token={t}") as a2:
        a1.receive_json(), a2.receive_json()
        a1.send_text("1")
        a2.send_text("2")
        a1.send_text("3")                              # tercero entre las dos pestañas: rechazado
        tipos = []
        while len(tipos) < 3:
            tipos.append(a1.receive_json()["tipo"])
        assert tipos == ["mensaje", "mensaje", "error"]


def test_el_cupo_se_renueva_al_terminar_la_ventana(client, monkeypatch):
    from app.services.ratelimit import limitador
    monkeypatch.setattr(config, "CHAT_MAX_MESSAGES", 1)
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text("uno")
        assert a.receive_json()["tipo"] == "mensaje"
        a.send_text("dos")
        assert a.receive_json()["tipo"] == "error"
        limitador.reiniciar()                          # equivale a que venza la ventana
        a.send_text("tres")
        assert a.receive_json()["mensaje"] == "tres"


def test_un_mensaje_demasiado_largo_cierra_la_conexion(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_LENGTH", 20)
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text("x" * 21)
        with pytest.raises(WebSocketDisconnect) as e:
            a.receive_json()
        assert e.value.code == 1009


def test_un_mensaje_justo_en_el_maximo_se_acepta(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_LENGTH", 20)
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text("x" * 20)
        assert a.receive_json()["mensaje"] == "x" * 20


def test_los_mensajes_vacios_se_ignoran_y_no_gastan_cupo(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_MESSAGES", 1)
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text("   ")
        a.send_text("")
        a.send_text("real")
        assert a.receive_json()["mensaje"] == "real"


def test_conexiones_simultaneas_por_usuario_limitadas(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_CONNECTIONS_PER_USER", 2)
    ana, beto = _crear("ana"), _crear("beto")
    t = _token(ana)
    with client.websocket_connect(f"/ws/chat?token={t}"), client.websocket_connect(f"/ws/chat?token={t}"):
        assert _rechazado(client, f"/ws/chat?token={t}") == 1008      # la tercera de Ana
        assert _rechazado(client, f"/ws/chat?token={_token(beto)}") is None   # otro usuario sí entra
    assert _rechazado(client, f"/ws/chat?token={t}") is None          # al cerrar se libera el cupo


def test_al_desconectar_se_limpia_la_conexion(client):
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        assert len(chat_manager.conexiones) == 1
    assert chat_manager.conexiones == {}


def test_un_fallo_del_limitador_no_tumba_el_chat(client, monkeypatch):
    from app.services.ratelimit import limitador

    def roto(*a, **k):
        raise RuntimeError("redis caído")
    monkeypatch.setattr(limitador, "golpear", roto)
    ana = _crear("ana")
    with client.websocket_connect(f"/ws/chat?token={_token(ana)}") as a:
        a.receive_json()
        a.send_text("sigo aquí")
        assert a.receive_json()["mensaje"] == "sigo aquí"


def test_un_cliente_muerto_se_elimina_del_broadcast(client):
    import asyncio

    class Muerto:
        async def send_json(self, m):
            raise RuntimeError("roto")

    chat_manager.conexiones[Muerto()] = {"id": 1, "username": "x"}
    asyncio.run(chat_manager.broadcast({"tipo": "mensaje"}))
    assert chat_manager.conexiones == {}


# ================================================================== roles

def _admin(client, nombre="root"):
    headers, uid = crear_usuario_y_login(client, nombre, f"{nombre}@example.com")
    assert dao.cambiar_rol(nombre, "admin") is True
    return headers


RUTAS_ADMIN = [("GET", "/precios/cache/stats"), ("DELETE", "/precios/cache/clear"),
               ("GET", "/system/metrics"), ("GET", "/system/endpoints")]


@pytest.mark.parametrize("metodo,ruta", RUTAS_ADMIN)
def test_un_usuario_normal_recibe_403(client, auth_headers, metodo, ruta):
    assert client.request(metodo, ruta, headers=auth_headers).status_code == 403


@pytest.mark.parametrize("metodo,ruta", RUTAS_ADMIN)
def test_sin_token_sigue_siendo_401_o_403_de_esquema(client, metodo, ruta):
    assert client.request(metodo, ruta).status_code in (401, 403)


@pytest.mark.parametrize("metodo,ruta", RUTAS_ADMIN)
def test_un_admin_accede(client, metodo, ruta):
    assert client.request(metodo, ruta, headers=_admin(client)).status_code == 200


def test_el_admin_vacia_el_cache_y_el_usuario_normal_no(client, auth_headers):
    cache.set("clave_de_prueba", {"a": 1}, ttl_seconds=60)
    assert client.delete("/precios/cache/clear", headers=auth_headers).status_code == 403
    assert cache.get("clave_de_prueba") == {"a": 1}                  # no se tocó
    assert client.delete("/precios/cache/clear", headers=_admin(client)).status_code == 200
    assert cache.get("clave_de_prueba") is None


def test_el_rol_se_lee_de_la_base_y_no_del_token(client):
    """Quitarle el rol a un admin surte efecto al instante aunque conserve su token."""
    headers = _admin(client)
    assert client.get("/precios/cache/stats", headers=headers).status_code == 200
    dao.cambiar_rol("root", "usuario")
    assert client.get("/precios/cache/stats", headers=headers).status_code == 403
    dao.cambiar_rol("root", "admin")
    assert client.get("/precios/cache/stats", headers=headers).status_code == 200


def test_el_registro_no_permite_elegir_rol(client):
    r = client.post("/usuarios/registro", json={
        "username": "mala", "email": "mala@example.com", "password": "password-123",
        "rol": "admin", "is_admin": True})
    assert r.status_code == 201
    assert r.json()["rol"] == "usuario"
    assert dao.obtener_usuario_por_username("mala")["rol"] == "usuario"


def test_los_nuevos_usuarios_son_usuario_y_se_ve_en_me_y_en_login(client):
    r = client.post("/usuarios/registro", json={"username": "nuevo", "email": "n@example.com", "password": "password-123"})
    assert r.json()["rol"] == "usuario"
    login = client.post("/usuarios/login", json={"username": "nuevo", "password": "password-123"}).json()
    assert login["usuario"]["rol"] == "usuario"
    me = client.get("/usuarios/me", headers={"Authorization": f"Bearer {login['access_token']}"})
    assert me.json()["rol"] == "usuario"


def test_la_base_rechaza_roles_inventados(client):
    _crear("ana")
    with pytest.raises(Exception):
        with engine.begin() as c:
            c.execute(text("UPDATE usuarios SET rol = 'superman' WHERE username = 'ana'"))


def test_cambiar_rol_de_un_usuario_inexistente_devuelve_false(client):
    assert dao.cambiar_rol("fantasma", "admin") is False


# ================================================================== script de roles

def _script(*args):
    import os
    return subprocess.run([sys.executable, str(RAIZ / "scripts" / "gestionar_roles.py"), *args],
                          capture_output=True, text=True, env=os.environ.copy(), cwd=str(RAIZ))


def test_el_script_promueve_degrada_y_lista(client):
    _crear("ana")
    r = _script("promover", "ANA")                    # mayúsculas: se normaliza como el registro
    assert r.returncode == 0, r.stderr
    assert dao.obtener_usuario_por_username("ana")["rol"] == "admin"
    assert "ana" in _script("listar").stdout
    assert _script("degradar", "ana").returncode == 0
    assert dao.obtener_usuario_por_username("ana")["rol"] == "usuario"
    assert "(ninguno)" in _script("listar").stdout


def test_el_script_falla_con_usuario_inexistente_y_con_argumentos_malos(client):
    assert _script("promover", "nadie").returncode == 1
    assert _script().returncode == 2
    assert _script("promover").returncode == 2
    assert _script("ascender", "ana").returncode == 2


# ================================================================== migración 0003

def test_migrar_conserva_usuarios_existentes_como_usuario():
    command.downgrade(alembic_config(), "0002")
    try:
        with engine.begin() as c:
            c.execute(text("TRUNCATE usuarios RESTART IDENTITY CASCADE"))
            c.execute(text("INSERT INTO usuarios (username,email,password_hash) VALUES ('vieja','v@x.com','h')"))
        command.upgrade(alembic_config(), "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT rol FROM usuarios WHERE username='vieja'")).scalar_one() == "usuario"
    finally:
        with engine.begin() as c:
            c.execute(text("TRUNCATE usuarios RESTART IDENTITY CASCADE"))
        command.upgrade(alembic_config(), "head")


def test_downgrade_de_0003_quita_la_columna():
    from sqlalchemy import inspect
    command.downgrade(alembic_config(), "0002")
    try:
        assert "rol" not in {c["name"] for c in inspect(engine).get_columns("usuarios")}
    finally:
        command.upgrade(alembic_config(), "head")
    assert "rol" in {c["name"] for c in inspect(engine).get_columns("usuarios")}


# ================================================================== el token no se filtra a los logs

def test_el_filtro_tapa_el_token_en_el_log_de_acceso_de_uvicorn():
    import logging
    from app.middleware import OcultarTokenEnLogs
    r = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]',
                          ("127.0.0.1:1", "/ws/chat?token=SECRETO.abc.def&x=1"), None)
    assert OcultarTokenEnLogs().filter(r) is True
    texto = r.getMessage()
    assert "SECRETO" not in texto and "token=***&x=1" in texto
    r2 = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /a?x=1&token=ZZZ HTTP/1.1", None, None)
    OcultarTokenEnLogs().filter(r2)
    assert "ZZZ" not in r2.getMessage()


def test_el_filtro_esta_instalado_en_la_app():
    import logging
    from app.middleware import OcultarTokenEnLogs
    for nombre in ("uvicorn.access", "uvicorn.error"):    # los WebSockets se registran en uvicorn.error
        assert any(isinstance(f, OcultarTokenEnLogs) for f in logging.getLogger(nombre).filters)
