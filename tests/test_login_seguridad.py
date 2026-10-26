# tests/test_login_seguridad.py
"""Protección del login: fuerza bruta, enumeración de usuarios y contraseñas límite."""
import logging

import pytest

from app.config import config
from app.services.ratelimit import AlmacenMemoria, limitador
from tests.conftest import crear_usuario_y_login
from utils.authorization import HASH_FICTICIO, hash_password, verify_password

CLAVE_BUENA = "password-de-prueba-123"


def _login(client, usuario="ana", clave="incorrecta", ip=None):
    cabeceras = {"X-Forwarded-For": ip} if ip else {}
    return client.post("/usuarios/login", json={"username": usuario, "password": clave}, headers=cabeceras)


@pytest.fixture
def ana(client):
    crear_usuario_y_login(client, "ana", "ana@example.com", CLAVE_BUENA)


@pytest.fixture
def detras_de_un_proxy(monkeypatch):
    """Cada cliente se identifica con su X-Forwarded-For (un proxy de confianza)."""
    monkeypatch.setattr(config, "TRUSTED_PROXY_COUNT", 1)


@pytest.fixture
def sin_limite_de_login_por_ip(monkeypatch):
    """Aísla el bloqueo por intentos fallidos del tope de peticiones por IP del middleware."""
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT", 10_000)


# ------------------------------------------------------------ bloqueo por fallos

def test_tras_5_fallos_el_siguiente_intento_recibe_429_con_retry_after(client, ana):
    codigos = [_login(client).status_code for _ in range(5)]
    assert codigos == [401] * 5
    r = _login(client)
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= config.LOGIN_LOCKOUT_SECONDS
    assert "segundos" in r.json()["detail"]


def test_durante_el_bloqueo_ni_la_contrasena_correcta_entra(client, ana):
    [_login(client) for _ in range(5)]
    assert _login(client, clave=CLAVE_BUENA).status_code == 429


def test_el_bloqueo_no_revela_si_el_usuario_existe(client, ana):
    """Un usuario real y uno inventado deben ser indistinguibles: mismos códigos, mismo mensaje."""
    existente = [_login(client, "ana") for _ in range(6)]
    inventado = [_login(client, "fantasma") for _ in range(6)]
    assert [r.status_code for r in existente] == [r.status_code for r in inventado] == [401] * 5 + [429]
    assert existente[0].json() == inventado[0].json()
    assert existente[5].json()["detail"].split(" en ")[0] == inventado[5].json()["detail"].split(" en ")[0]


def test_el_bloqueo_es_por_usuario_y_no_afecta_a_otras_cuentas_de_la_misma_ip(client, ana):
    crear_usuario_y_login(client, "beto", "beto@example.com", CLAVE_BUENA)
    [_login(client, "ana") for _ in range(5)]
    assert _login(client, "ana", CLAVE_BUENA).status_code == 429
    assert _login(client, "beto", CLAVE_BUENA).status_code == 200


def test_un_atacante_no_puede_bloquear_a_la_victima_desde_su_propia_ip(
        client, ana, detras_de_un_proxy):
    for _ in range(5):
        _login(client, "ana", ip="198.51.100.66")                   # el atacante falla 5 veces
    assert _login(client, "ana", ip="198.51.100.66").status_code == 429
    assert _login(client, "ana", CLAVE_BUENA, ip="203.0.113.10").status_code == 200   # la víctima entra


def test_un_login_correcto_reinicia_los_fallos_de_esa_ip_y_usuario(client, ana):
    [_login(client) for _ in range(4)]
    assert _login(client, clave=CLAVE_BUENA).status_code == 200
    assert [_login(client).status_code for _ in range(4)] == [401] * 4        # vuelve a tener 4 intentos
    assert _login(client).status_code == 401                                   # el quinto fallo, todavía 401
    assert _login(client).status_code == 429


def test_ataque_repartido_entre_muchas_ips_se_frena_por_usuario(client, ana, detras_de_un_proxy):
    """20 IPs distintas, 1 fallo cada una: ninguna llega a 5, pero la cuenta acumula 20 fallos."""
    for i in range(20):
        assert _login(client, "ana", ip=f"198.51.100.{i + 1}").status_code == 401
    r = _login(client, "ana", CLAVE_BUENA, ip="198.51.100.200")                # IP nueva, contraseña correcta
    assert r.status_code == 429


def test_un_login_correcto_de_la_victima_no_limpia_el_contador_del_usuario(client, ana, detras_de_un_proxy):
    for i in range(19):
        _login(client, "ana", ip=f"198.51.100.{i + 1}")
    assert _login(client, "ana", CLAVE_BUENA, ip="203.0.113.10").status_code == 200   # entra (19 < 20)
    _login(client, "ana", ip="198.51.100.150")                                         # fallo número 20
    assert _login(client, "ana", CLAVE_BUENA, ip="203.0.113.11").status_code == 429    # no se había reiniciado


def test_probar_muchos_usuarios_desde_una_ip_se_frena_por_ip(client, sin_limite_de_login_por_ip):
    """Relleno de credenciales: 30 usuarios distintos, cada uno con un solo intento."""
    assert [_login(client, f"usuario{i}").status_code for i in range(30)] == [401] * 30
    assert _login(client, "otro").status_code == 429


def test_el_bloqueo_termina_con_la_ventana(client, ana, monkeypatch):
    class Reloj:
        t = 5000.0

        def __call__(self):
            return self.t

    reloj = Reloj()
    monkeypatch.setattr(limitador, "almacen", AlmacenMemoria(reloj=reloj))
    [_login(client) for _ in range(5)]
    assert _login(client, clave=CLAVE_BUENA).status_code == 429
    reloj.t += config.LOGIN_LOCKOUT_SECONDS - 1
    assert _login(client, clave=CLAVE_BUENA).status_code == 429
    reloj.t += 2
    assert _login(client, clave=CLAVE_BUENA).status_code == 200


def test_el_numero_de_fallos_es_configurable(client, ana, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", 2)
    assert [_login(client).status_code for _ in range(3)] == [401, 401, 429]


def test_un_solo_aviso_en_el_log_por_bloqueo(client, ana, caplog):
    with caplog.at_level(logging.WARNING, logger="trading-api"):
        for _ in range(12):
            _login(client)
    assert sum("Login bloqueado" in r.message for r in caplog.records) == 1


def test_un_usuario_con_texto_enorme_se_rechaza_antes_de_guardar_nada(client):
    """El nombre forma parte de la clave del contador: no puede ser texto arbitrario de cualquier tamaño."""
    assert _login(client, "x" * 5000).status_code == 422
    assert all("xxxxxxxx" not in clave for clave in limitador.almacen._datos)


# ----------------------------------------------- sin diferencias de tiempo (enumeración)

def test_siempre_se_verifica_un_hash_exista_o_no_el_usuario(client, ana, monkeypatch):
    """Antes un usuario inexistente respondía en 4 ms y uno real en ~300 ms: el tiempo delataba las cuentas."""
    comparados = []
    original = verify_password

    def espia(plano, hash_):
        comparados.append(hash_)
        return original(plano, hash_)

    monkeypatch.setattr("app.routers.users.verify_password", espia)

    _login(client, "fantasma")
    assert comparados == [HASH_FICTICIO]
    comparados.clear()
    _login(client, "ana")
    assert len(comparados) == 1 and comparados[0] != HASH_FICTICIO and comparados[0].startswith("$2")


def test_el_hash_ficticio_es_un_bcrypt_valido_con_el_mismo_coste_que_los_reales():
    assert HASH_FICTICIO.startswith("$2") and HASH_FICTICIO.split("$")[2] == hash_password("x").split("$")[2]
    assert verify_password("cualquier-cosa", HASH_FICTICIO) is False


# ------------------------------------------------------------ contraseñas límite

def test_contrasena_de_mas_de_72_bytes_en_el_registro_da_422_y_no_500(client):
    r = client.post("/usuarios/registro", json={"username": "emoji", "email": "e@example.com", "password": "😀" * 50})
    assert r.status_code == 422
    assert "72 bytes" in r.text


def test_el_limite_de_72_bytes_es_exacto(client):
    ok = client.post("/usuarios/registro", json={"username": "enie", "email": "n@example.com", "password": "ñ" * 36})
    assert ok.status_code == 201                                  # 72 bytes
    mal = client.post("/usuarios/registro", json={"username": "enie2", "email": "n2@example.com", "password": "ñ" * 37})
    assert mal.status_code == 422                                 # 74 bytes
    assert _login(client, "enie", "ñ" * 36).status_code == 200    # y la de 72 bytes puede entrar


@pytest.mark.parametrize("clave,esperado", [
    ("😀" * 50, 401),              # más de 72 bytes: no puede ser la contraseña de nadie; antes daba 500
    ("x" * 129, 422),              # demasiado larga
    ("x" * 1_000_000, 422),        # antes se aceptaba un cuerpo de megabytes y daba 500
    ("", 422),
])
def test_login_con_contrasenas_extremas_no_da_500(client, ana, clave, esperado):
    assert _login(client, "ana", clave).status_code == esperado


def test_login_con_mas_de_72_bytes_cuenta_como_intento_fallido(client, ana):
    for _ in range(5):
        assert _login(client, "ana", "😀" * 50).status_code == 401
    assert _login(client, "ana", CLAVE_BUENA).status_code == 429


def test_verify_password_no_lanza_con_entradas_invalidas():
    assert verify_password("😀" * 50, hash_password("correcta")) is False
    assert verify_password("correcta", "esto-no-es-un-hash") is False
    assert verify_password("correcta", hash_password("correcta")) is True


def test_el_usuario_no_distingue_mayusculas_en_el_login(client, ana):
    """El registro guarda el usuario en minúsculas, pero el login comparaba el texto tal cual."""
    assert _login(client, "ANA", CLAVE_BUENA).status_code == 200
    [_login(client, "Ana") for _ in range(5)]
    assert _login(client, "ana", CLAVE_BUENA).status_code == 429     # mismas cuentas, mismo contador


def test_el_login_correcto_sigue_devolviendo_el_mismo_formato(client, ana):
    r = _login(client, "ana", CLAVE_BUENA)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer" and cuerpo["access_token"]
    assert set(cuerpo["usuario"]) == {"id", "username", "email", "rol"}
    assert cuerpo["usuario"]["rol"] == "usuario"
