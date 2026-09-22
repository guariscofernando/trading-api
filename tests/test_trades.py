# tests/test_trades.py

def test_raiz(client):
    """Test del endpoint raíz"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "mensaje" in data

def test_health_check(client):
    """Test del health check"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_crear_trade_con_auth(client, auth_headers):
    """Test de crear trade con autenticación"""
    
    response = client.post(
        "/trades/",
        json={
            "tipo": "compra",
            "activo": "BTC",
            "precio": 50000,
            "cantidad": 0.5
        }, headers=auth_headers)
    
    assert response.status_code == 201
    data = response.json()
    assert data["tipo"] == "compra"
    assert data["activo"] == "BTC"
    assert data["precio"] == 50000

def test_crear_trade_sin_auth(client):
    """Test de crear trade sin autenticación (debe fallar)"""
    response = client.post(
        "/trades/",
        json={
            "tipo": "compra",
            "activo": "BTC",
            "precio": 50000,
            "cantidad": 0.5
        }
    )
    
    assert response.status_code == 401  # Unauthorized: falta el token

def test_crear_trade_invalido(client, auth_headers):
    """Test de crear trade con datos inválidos"""
    
    response = client.post(
        "/trades/",
        json={
            "tipo": "invalido",
            "activo": "BTC",
            "precio": -100,
            "cantidad": 0
        }, headers=auth_headers)
    
    assert response.status_code == 422  # Validation error

def test_listar_trades(client, auth_headers):
    """Test de listar trades del usuario"""
    
    # Crear algunos trades
    for i in range(3):
        client.post("/trades/", json={
            "tipo": "compra",
            "activo": "ETH",
            "precio": 3000 + i * 100,
            "cantidad": 1
        }, headers=auth_headers)
    
    # Listar trades
    response = client.get("/trades/", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

def test_eliminar_trade(client, auth_headers):
    """Test de eliminar un trade"""
    
    # Crear un trade
    create_response = client.post("/trades/", json={
        "tipo": "venta",
        "activo": "SOL",
        "precio": 100,
        "cantidad": 10
    }, headers=auth_headers)
    
    trade_id = create_response.json()["id"]
    
    # Eliminar
    delete_response = client.delete(f"/trades/{trade_id}", headers=auth_headers)
    assert delete_response.status_code == 200
    
    # Verificar que fue eliminado
    get_response = client.get(f"/trades/{trade_id}", headers=auth_headers)
    assert get_response.status_code == 404