# tests/test_usuarios.py

def test_registro_usuario(client):
    """Test de registro de usuario"""
    response = client.post("/usuarios/registro", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpassword123"
    })
    
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert "id" in data

def test_registro_username_duplicado(client):
    """Test de registro con username duplicado"""
    # Registrar primer usuario
    client.post("/usuarios/registro", json={
        "username": "duplicateuser",
        "email": "dup1@example.com",
        "password": "password123"
    })
    
    # Intentar registrar con el mismo username
    response = client.post("/usuarios/registro", json={
        "username": "duplicateuser",
        "email": "dup2@example.com",
        "password": "password123"
    })
    
    assert response.status_code == 400
    assert "Username ya registrado" in response.json()["detail"]

def test_login_exitoso(client):
    """Test de login exitoso"""
    # Primero registrar
    client.post("/usuarios/registro", json={
        "username": "logintest",
        "email": "login@example.com",
        "password": "password123"
    })
    
    # Luego login
    response = client.post("/usuarios/login", json={
        "username": "logintest",
        "password": "password123"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_password_incorrecta(client):
    """Test de login con password incorrecta"""
    client.post("/usuarios/registro", json={
        "username": "wrongpass",
        "email": "wrongpass@example.com",
        "password": "correctpassword"
    })
    
    response = client.post("/usuarios/login", json={
        "username": "wrongpass",
        "password": "wrongpassword"
    })
    
    assert response.status_code == 401