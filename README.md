# Trading API v2

API REST completa para gestionar trades de trading con autenticación JWT.

## Features
- ✅ Registro y login de usuarios
- ✅ Autenticación con JWT
- ✅ CRUD de trades (protegido por usuario)
- ✅ Precios en tiempo real (CoinGecko API)
- ✅ Análisis de P&L con precios actuales
- ✅ Tests con Pytest
- ✅ Deploy en Render.com

## Tecnologías
- Python 3.12
- FastAPI
- SQLite
- JWT (python-jose)
- bcrypt (passlib)
- Pytest
- httpx

## Endpoints

### Autenticación
- `POST /usuarios/registro` - Registrar usuario
- `POST /usuarios/login` - Login (devuelve JWT)

### Trades (requiere JWT)
- `POST /trades/` - Crear trade
- `GET /trades/` - Listar trades del usuario
- `GET /trades/{id}` - Obtener trade
- `PATCH /trades/{id}` - Actualizar trade
- `DELETE /trades/{id}` - Eliminar trade

### Precios (público)
- `GET /precios/{coin_id}` - Precio actual
- `GET /precios/multiples?coins=btc,eth` - Múltiples precios
- `GET /precios/buscar/{query}` - Buscar moneda

### Análisis (requiere JWT)
- `GET /analisis/pnl-en-vivo` - P&L con precios actuales

## Instalación

```bash
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
uvicorn app.main:app --reload