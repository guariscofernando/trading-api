"""Fase 13: cierre de sesión, cambio de contraseña y revocación de tokens."""
import pytest
from starlette.websockets import WebSocketDisconnect

from app.dao.UserDAO import UserDAO
from tests.conftest import crear_usuario_y_login
from utils.authorization import create_access_token

PWD = "password-de-prueba-123"


def _login(client, username="ana", password=PWD):
    r = client.post("/usuarios/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ok(client, headers):
    return client.get("/usuarios/me", headers=headers).status_code


@pytest.fixture
def ana(client):
    headers, uid = crear_usuario_y_login(client, "ana", "ana@example.com")
    return {"headers": headers, "id": uid}


def test_logout_revoca_el_token_y_todos_los_demas_del_usuario(client, ana):
    otro_dispositivo = _login(client)
    assert _ok(client, ana["headers"]) == 200
    assert client.post("/usuarios/logout", headers=ana["headers"]).status_code == 200
    assert _ok(client, ana["headers"]) == 401
    assert _ok(client, otro_dispositivo) == 401
    assert _ok(client, _login(client)) == 200      # un login nuevo vale


def test_logout_no_afecta_a_otros_usuarios(client, ana):
    h_b, _ = crear_usuario_y_login(client, "beto", "beto@example.com")
    client.post("/usuarios/logout", headers=ana["headers"])
    assert _ok(client, h_b) == 200


def test_logout_exige_token(client):
    assert client.post("/usuarios/logout").status_code in (401, 403)


def test_token_viejo_sin_claim_de_version_sigue_valiendo_hasta_la_primera_revocacion(client, ana):
    token = create_access_token({"sub": str(ana["id"])})
    h = {"Authorization": f"Bearer {token}"}
    assert _ok(client, h) == 200
    client.post("/usuarios/logout", headers=ana["headers"])
    assert _ok(client, h) == 401


@pytest.mark.parametrize("tv", ["0", True, 1.5, None, [], 99])
def test_version_malformada_o_futura_se_rechaza(client, ana, tv):
    token = create_access_token({"sub": str(ana["id"]), "tv": tv})
    assert _ok(client, {"Authorization": f"Bearer {token}"}) == 401


def test_cambiar_password_revoca_sesiones_y_devuelve_token_nuevo(client, ana):
    r = client.post("/usuarios/cambiar-password", headers=ana["headers"],
                    json={"password_actual": PWD, "password_nueva": "otra-clave-456"})
    assert r.status_code == 200, r.text
    nuevo = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _ok(client, ana["headers"]) == 401
    assert _ok(client, nuevo) == 200
    assert client.post("/usuarios/login", json={"username": "ana", "password": PWD}).status_code == 401
    assert client.post("/usuarios/login", json={"username": "ana", "password": "otra-clave-456"}).status_code == 200


def test_cambiar_password_con_la_actual_incorrecta_no_cambia_nada(client, ana):
    r = client.post("/usuarios/cambiar-password", headers=ana["headers"],
                    json={"password_actual": "equivocada", "password_nueva": "otra-clave-456"})
    assert r.status_code == 403
    assert _ok(client, ana["headers"]) == 200
    assert client.post("/usuarios/login", json={"username": "ana", "password": PWD}).status_code == 200


def test_la_nueva_debe_ser_distinta_y_valida(client, ana):
    url = "/usuarios/cambiar-password"
    assert client.post(url, headers=ana["headers"], json={"password_actual": PWD, "password_nueva": PWD}).status_code == 422
    assert client.post(url, headers=ana["headers"], json={"password_actual": PWD, "password_nueva": "corta"}).status_code == 422
    assert client.post(url, headers=ana["headers"], json={"password_actual": PWD, "password_nueva": "é" * 40}).status_code == 422
    assert _ok(client, ana["headers"]) == 200


def test_cambiar_password_exige_token(client):
    r = client.post("/usuarios/cambiar-password", json={"password_actual": PWD, "password_nueva": "otra-clave-456"})
    assert r.status_code in (401, 403)


def test_los_intentos_fallidos_se_bloquean_como_en_el_login(client, ana):
    codigos = []
    for _ in range(12):
        r = client.post("/usuarios/cambiar-password", headers=ana["headers"],
                        json={"password_actual": "mala", "password_nueva": "otra-clave-456"})
        codigos.append(r.status_code)
    assert 429 in codigos
    # bloqueado: ni siquiera la correcta pasa
    r = client.post("/usuarios/cambiar-password", headers=ana["headers"],
                    json={"password_actual": PWD, "password_nueva": "otra-clave-456"})
    assert r.status_code == 429


def test_dao_cambiar_password_no_pisa_si_el_hash_cambio_entremedias(client, ana):
    dao = UserDAO()
    u = dao.obtener_usuario_por_id(ana["id"])
    assert dao.cambiar_password(ana["id"], "hash-que-no-es", "x") is None
    assert dao.obtener_usuario_por_id(ana["id"])["password_hash"] == u["password_hash"]
    assert dao.cambiar_password(ana["id"], u["password_hash"], "nuevo") == u["token_version"] + 1


def test_el_token_revocado_no_entra_a_los_websockets(client, ana):
    token = ana["headers"]["Authorization"].split()[1]
    client.post("/usuarios/logout", headers=ana["headers"])
    for ruta in ("/ws/chat", "/ws/notificaciones"):
        try:
            with client.websocket_connect(f"{ruta}?token={token}") as ws:
                msg = ws.receive_json()
        except WebSocketDisconnect:
            continue
        assert msg.get("tipo") == "error", msg


def test_logout_cierra_los_websockets_abiertos(client, ana):
    token = ana["headers"]["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/notificaciones?token={token}") as ws:
        assert ws.receive_json()["tipo"] == "conexion"
        client.post("/usuarios/logout", headers=ana["headers"])
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
