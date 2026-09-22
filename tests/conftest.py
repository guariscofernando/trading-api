# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.connections.trading_db_conn import TradingConnection
from app.connections.intensive_review_db_conn import IntensiveReviewConnection

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(TradingConnection, "DB_PATH", str(tmp_path / "trading_test.db"))
    monkeypatch.setattr(IntensiveReviewConnection, "DB_PATH", str(tmp_path / "review_test.db"))

    TradingConnection().init_db()
    IntensiveReviewConnection().init_db()

    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers(client):
    client.post("/usuarios/registro", json={
        "username": "tradetester",
        "email": "trade@example.com",
        "password": "tradepassword"
    })
    response = client.post("/usuarios/login", json={
        "username": "tradetester",
        "password": "tradepassword"
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}