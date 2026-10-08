# tests/conftest.py
"""
Fixtures de pytest. Los tests corren contra una base PostgreSQL REAL de pruebas.

Cómo configurarlo:
    export TEST_DATABASE_URL=postgresql://usuario:password@localhost:5432/trading_test
    pytest

Seguridad: el nombre de la base DEBE terminar en "_test". Antes de cada test se
vacían todas las tablas, así que nunca se debe apuntar a una base con datos reales.
"""
import os
import pytest
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.connections.trading_db_conn import TradingConnection  # noqa: E402
from app.middleware import RateLimitMiddleware  # noqa: E402
from dotenv import load_dotenv

load_dotenv()

# 1) Elegir la base de pruebas y validarla ANTES de importar la app:
#    importar app.main crea las tablas en la base configurada.
_test_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
if not _test_url:
    pytest.exit(
        "Define TEST_DATABASE_URL (p. ej. postgresql://usuario:password@localhost:5432/trading_test)",
        returncode=2,
    )

_db_name = _test_url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
if not _db_name.endswith("_test"):
    pytest.exit(
        f"Por seguridad los tests solo corren sobre una base cuyo nombre termine en '_test' "
        f"(recibido: '{_db_name}'). Los tests vacían las tablas.",
        returncode=2,
    )

os.environ["DATABASE_URL"] = _test_url

# 2) Protección real: la app ya se importó (arriba) y leyó DATABASE_URL del entorno/.env
#    ANTES de la línea anterior, así que el override de arriba llega tarde. Lo que vale
#    es la base a la que la app REALMENTE se conecta; si no termina en "_test", los
#    TRUNCATE de _vaciar_tablas() borrarían datos reales.
from app.config import config  # noqa: E402

_db_real = (config.DATABASE_URL or "").split("?")[0].rstrip("/").rsplit("/", 1)[-1]
if not _db_real.endswith("_test"):
    pytest.exit(
        f"La app está conectada a '{_db_real}', que no termina en '_test'; los tests la vaciarían. "
        f"Ejecuta: DATABASE_URL=$TEST_DATABASE_URL pytest",
        returncode=2,
    )

TABLAS = ("orders", "watchlist", "trades", "usuarios")


def _vaciar_tablas():
    conn = TradingConnection().get_connection()
    try:
        cur = conn.cursor()
        # Solo las tablas que existan (algunas se crean bajo demanda)
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s)",
            (list(TABLAS),),
        )
        existentes = [fila[0] for fila in cur.fetchall()]
        if existentes:
            cur.execute("TRUNCATE " + ", ".join(existentes) + " RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()


def _reiniciar_rate_limit(aplicacion):
    """El rate limiter guarda estado en memoria: lo limpiamos entre tests."""
    capa = getattr(aplicacion, "middleware_stack", None)
    while capa is not None:
        if isinstance(capa, RateLimitMiddleware):
            capa.requests.clear()
            return
        capa = getattr(capa, "app", None)


@pytest.fixture
def client():
    _vaciar_tablas()
    with TestClient(app) as c:
        _reiniciar_rate_limit(app)
        yield c
    _vaciar_tablas()


def crear_usuario_y_login(client, username, email, password="password-de-prueba-123"):
    """Registra un usuario y devuelve (headers_de_auth, user_id)."""
    r = client.post("/usuarios/registro", json={
        "username": username, "email": email, "password": password
    })
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]
    r = client.post("/usuarios/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, user_id


@pytest.fixture
def auth_headers(client):
    """Headers del usuario principal de los tests."""
    headers, _ = crear_usuario_y_login(
        client, "tradetester", "trade@example.com", password="tradepassword"
    )
    return headers


@pytest.fixture
def usuario_a(client):
    headers, user_id = crear_usuario_y_login(client, "usuario_a", "a@example.com")
    return {"headers": headers, "id": user_id}


@pytest.fixture
def usuario_b(client):
    headers, user_id = crear_usuario_y_login(client, "usuario_b", "b@example.com")
    return {"headers": headers, "id": user_id}
