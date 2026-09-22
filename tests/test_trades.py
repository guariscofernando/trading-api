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

"""
Exercise: Write tests for:
Update a trade (PATCH)
Attempt to update another user's trade (must return 403)
Validate that the /trades/resumen/pnl endpoint works
"""

def test_actualizar_trade(client, auth_headers):
    """Test de actualizar un trade"""
    
    # Crear un trade
    create_response = client.post("/trades/", json={
        "tipo": "venta",
        "activo": "SOL",
        "precio": 100,
        "cantidad": 10
    }, headers=auth_headers)
    
    trade_id = create_response.json()["id"]
    
    # Actualizar
    update_response = client.patch(f"/trades/{trade_id}", json={
        "tipo": "compra",
        "activo": "SOL",
        "precio": 150,
        "cantidad": 12
    }, headers=auth_headers)
    assert update_response.status_code == 200
    
    # Verificar que fue actualizado
    get_response = client.get(f"/trades/{trade_id}", headers=auth_headers)
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["tipo"] == "compra"
    assert data["activo"] == "SOL"
    assert data["precio"] == 150

def test_actualizar_trade_de_otro_usuario(client, auth_headers):
    """Un usuario no puede actualizar el trade de otro"""

    # Usuario A crea un trade
    create_response = client.post("/trades/", json={
        "tipo": "venta",
        "activo": "SOL",
        "precio": 100,
        "cantidad": 10
    }, headers=auth_headers)
    trade_id = create_response.json()["id"]

    # Usuario B se registra y loguea
    client.post("/usuarios/registro", json={
        "username": "otro_usuario",
        "email": "otro@test.com",
        "password": "otraPassword123"
    })
    login_otro = client.post("/usuarios/login", json={
        "username": "otro_usuario",
        "password": "otraPassword123"
    })
    token_otro = login_otro.json()["access_token"]
    headers_otro = {"Authorization": f"Bearer {token_otro}"}

    # Usuario B intenta actualizar el trade de Usuario A
    update_response = client.patch(f"/trades/{trade_id}", json={
        "tipo": "compra",
        "activo": "SOL",
        "precio": 150,
        "cantidad": 12
    }, headers=headers_otro)

    assert update_response.status_code == 403

def test_calcular_pnl(client, auth_headers):
    """Test del endpoint de PnL"""

    # Compra de 1 BTC a 50000
    client.post("/trades/", json={
        "tipo": "compra",
        "activo": "BTC",
        "precio": 50000,
        "cantidad": 1
    }, headers=auth_headers)

    # Venta de 1 BTC a 55000
    client.post("/trades/", json={
        "tipo": "venta",
        "activo": "BTC",
        "precio": 55000,
        "cantidad": 1
    }, headers=auth_headers)

    response = client.get("/trades/resumen/pnl")

    assert response.status_code == 200
    data = response.json()

    # PnL esperado: -50000 (compra) + 55000 (venta) = 5000
    assert data["pnl_total"] == 5000
    assert data["total_trades"] == 2
    assert "BTC" in data["por_activo"]
    assert data["por_activo"]["BTC"]["pnl"] == 5000

def test_pnl_sin_trades(client):
    """PnL cuando no hay trades registrados"""
    response = client.get("/trades/resumen/pnl")
    assert response.status_code == 200
    data = response.json()
    assert data["pnl_total"] == 0
    assert data["por_activo"] == {}
    assert data["total_trades"] == 0