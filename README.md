# Trading API Pro

API REST para gestionar trades de criptomonedas, con autenticación JWT, análisis de P&L usando precios en vivo (CoinGecko), notificaciones por WebSocket e integración con Binance Testnet.

## Features

- ✅ Registro y login de usuarios (bcrypt + JWT)
- ✅ CRUD de trades protegido por usuario
- ✅ Búsqueda avanzada, paginación con ordenamiento y exportación a CSV
- ✅ Precios en tiempo real (CoinGecko) con caché en memoria
- ✅ Análisis de P&L con precios actuales, recomendaciones y reporte completo
- ✅ Watchlist con alertas de precio objetivo
- ✅ Dashboard consolidado y reporte en PDF
- ✅ WebSockets: precios, chat y notificaciones en tiempo real por usuario
- ✅ Integración con Binance Testnet (precios, balance y órdenes)
- ✅ Métricas del sistema y listado de endpoints
- ✅ Tests con Pytest
- ✅ Deploy en Render.com

## Tecnologías

- Python 3.12
- FastAPI
- PostgreSQL 16 (vía Docker / docker-compose) con psycopg2
- Binance Testnet (python-binance)
- JWT (python-jose)
- bcrypt (passlib)
- httpx (cliente para CoinGecko)
- FPDF (reportes PDF)
- psutil (métricas)
- Pytest

## Instalación

### Requisitos previos

- Python 3.12 (solo si vas a correr la API fuera de Docker)
- Git
- Docker con el servicio activo (en Windows, abrir **Docker Desktop** antes de continuar)

### Pasos

1. Clonar el repositorio:

```bash
git clone <URL_DEL_REPOSITORIO>
cd <NOMBRE_DEL_PROYECTO>
```

2. Crear y activar el entorno virtual, e instalar las dependencias:

```bash
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
```

3. Crear un archivo `.env` en la raíz del proyecto con las variables descritas en la sección [Configuración](#configuración).

4. Levantar la base de datos y la API. Hay dos formas:

**Opción A — Base de datos en Docker y API local (recomendada para desarrollo)**

```bash
docker-compose up -d db
uvicorn app.main:app --reload
```

La API se conecta a PostgreSQL en `localhost:5432` usando el `DATABASE_URL` del `.env`.

**Opción B — Todo en Docker**

```bash
docker-compose up --build
```

Levanta la base de datos y la API juntas; la imagen de la API se construye con el `Dockerfile` del proyecto (Python 3.12). En este caso **no** hay que ejecutar `uvicorn`, porque el puerto de la API (`API_PORT`, por defecto 8000) ya estaría ocupado por el contenedor.

> En ambos casos la base de datos debe estar corriendo antes de iniciar la API. Las tablas se crean automáticamente al arrancar la aplicación.

La API queda disponible en `http://localhost:8000` y la documentación interactiva (Swagger) en `http://localhost:8000/docs`.

## Configuración

Crea un archivo `.env` en la raíz del proyecto (no lo subas al repositorio; asegúrate de que esté en `.gitignore`). Ejemplo:

```env
# Entorno
ENVIRONMENT=development
DEBUG=true
API_PORT=8000

# App
APP_NAME=Trading API Pro
APP_VERSION=4.0.0
APP_DESCRIPTION=API completa para gestión de trades con autenticación JWT
ENCODE=utf-8

# JWT
SECRET_KEY=cambia-esto-en-produccion
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Base de datos (Docker)
POSTGRES_USER=trading_user
POSTGRES_PASSWORD=trading_password
POSTGRES_DB=trading_db
DATABASE_URL=postgresql://trading_user:trading_password@localhost:5432/trading_db

# CORS (orígenes separados por coma)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Binance Testnet
BINANCE_TESTNET=true
BINANCE_API_KEY=tu_api_key_testnet
BINANCE_SECRET_KEY=tu_secret_key_testnet

# CoinGecko
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_API_KEY=tu_api_key_coingecko
```

| Variable | Descripción |
|----------|-------------|
| `ENVIRONMENT` | `development` o `production`. En producción se deshabilitan `/docs`, `/redoc` y `/openapi.json` |
| `SECRET_KEY` | Clave para firmar los JWT. **Cambiarla en producción** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del token de acceso |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciales de la base que crea `docker-compose` |
| `DATABASE_URL` | Cadena de conexión. Para correr la API fuera de Docker usa `localhost`; dentro del compose se sobrescribe con el host `db` |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma |
| `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` | Claves de Binance **Testnet** (se generan en [testnet.binance.vision](https://testnet.binance.vision)) |
| `COINGECKO_API_KEY` | API key de CoinGecko |

**Variables obligatorias:** `SECRET_KEY`, `ALGORITHM`, `DATABASE_URL`, `DEBUG`, `APP_NAME`, `APP_VERSION` y `APP_DESCRIPTION`. Si falta alguna, la aplicación no arranca o falla al usar la autenticación.

**Variables con valor por defecto:** `ENVIRONMENT` (`development`), `ENCODE` (`utf-8`), `BINANCE_TESTNET` (`true`), `COINGECKO_BASE_URL`, `ACCESS_TOKEN_EXPIRE_MINUTES` (`60`). Si no configuras las claves de Binance se muestra una advertencia al iniciar y los endpoints de `/binance` y `/orders` no funcionarán.

Las variables `POSTGRES_*` y `API_PORT` las usa `docker-compose`.

## Autenticación

Los endpoints protegidos requieren un token JWT en el header:

```
Authorization: Bearer <access_token>
```

Para obtenerlo:

```bash
# 1. Registro
curl -X POST http://localhost:8000/usuarios/registro \
  -H "Content-Type: application/json" \
  -d '{"username": "juan", "email": "juan@mail.com", "password": "secreto123"}'

# 2. Login
curl -X POST http://localhost:8000/usuarios/login \
  -H "Content-Type: application/json" \
  -d '{"username": "juan", "password": "secreto123"}'
```

La respuesta del login incluye `access_token`, `token_type` y los datos básicos del usuario.

## Endpoints

La columna **Auth** indica si el endpoint requiere JWT (🔒) o es público (🌐).

### General

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | 🌐 | Mensaje de bienvenida y versión |
| GET | `/health` | 🌐 | Health check (usado por Docker) |
| GET | `/info` | 🌐 | Información de la API |

La API aplica un límite de **100 peticiones por 60 segundos** (rate limit) y registra cada petición mediante un middleware de logging. Los archivos estáticos se sirven desde `/static`.

### Usuarios — `/usuarios`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/usuarios/registro` | 🌐 | Registrar usuario |
| POST | `/usuarios/login` | 🌐 | Login, devuelve JWT |
| GET | `/usuarios/me` | 🔒 | Info del usuario autenticado |
| GET | `/usuarios/{user_id}` | 🌐 | Obtener usuario por ID |

### Trades — `/trades`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/trades/` | 🔒 | Crear trade (envía notificación por WebSocket) |
| GET | `/trades/` | 🔒 | Listar trades propios. Query: `skip`, `limit` (máx. 100), `tipo`, `activo` |
| GET | `/trades/paginado` | 🔒 | Paginación con orden. Query: `page`, `per_page`, `orden`, `direccion` |
| GET | `/trades/{id}` | 🌐 | Obtener un trade |
| PATCH | `/trades/{id}` | 🔒 | Actualizar trade (solo el dueño) |
| DELETE | `/trades/{id}` | 🔒 | Eliminar trade (solo el dueño) |
| GET | `/trades/buscar` | 🌐 | Búsqueda avanzada. Query: `activo`, `tipo`, `precio_min`, `precio_max`, `fecha_desde`, `fecha_hasta` |
| GET | `/trades/exportar/csv` | 🌐 | Exporta trades a CSV |
| GET | `/trades/estadisticas` | 🌐 | Totales, volumen, precios promedio y activos operados |
| GET | `/trades/resumen/pnl` | 🌐 | P&L por flujo de caja (ventas − compras) |
| GET | `/trades/resumen/mejor-trade` | 🌐 | Venta de mayor valor |
| GET | `/trades/resumen/por-fecha` | 🌐 | Trades en un rango. Query: `desde`, `hasta` |
| GET | `/trades/resumen/por-activo/{activo}` | 🌐 | Compras, ventas, P&L y precios promedio de un activo |

**Ejemplo: crear trade**

```bash
curl -X POST http://localhost:8000/trades/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"tipo": "compra", "activo": "btc", "precio": 50000, "cantidad": 0.1}'
```

```json
{
  "id": 1,
  "usuario_id": 1,
  "tipo": "compra",
  "activo": "BTC",
  "precio": 50000,
  "cantidad": 0.1,
  "fecha": "2026-01-15 10:30"
}
```

`tipo` acepta `compra` o `venta`. El campo `activo` se normaliza a mayúsculas.

### Precios (CoinGecko) — `/precios`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/precios/{coin_id}` | 🌐 | Precio actual. Query: `moneda` (default `usd`), `use_cache` (default `true`) |
| GET | `/precios/multiples?coins=bitcoin,ethereum` | 🌐 | Precios de varias monedas. Query: `coins`, `moneda` |
| GET | `/precios/buscar/{query}` | 🌐 | Buscar moneda por nombre (máx. 10 resultados) |
| GET | `/precios/cache/stats` | 🌐 | Estadísticas del caché |
| DELETE | `/precios/cache/clear` | 🌐 | Limpiar el caché |

Los `coin_id` son los IDs de CoinGecko (`bitcoin`, `ethereum`, etc.). El precio individual se cachea 30 segundos.

### Análisis — `/analisis`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/analisis/pnl-en-vivo` | 🔒 | P&L por activo y total con precios actuales (caché 60 s) |
| GET | `/analisis/recomendaciones` | 🔒 | Sugerencia por activo según su P&L |
| GET | `/analisis/reporte-completo` | 🔒 | Estadísticas, P&L, mejor y peor activo |
| POST | `/analisis/watchlist` | 🔒 | Agregar moneda con precio de alerta |
| GET | `/analisis/watchlist` | 🔒 | Ver watchlist del usuario |

**Cálculo de P&L:** para cada activo se calcula la cantidad neta (compras − ventas), el costo neto y el valor actual (`cantidad × precio actual`). El P&L es `valor_actual − costo_total`.

**Recomendaciones:**

| P&L del activo | Sugerencia |
|----------------|------------|
| ≤ −10% | posible oportunidad de compra |
| ≥ +20% | considerar tomar ganancias |
| otro | sin recomendación |

Solo se evalúan activos con posición abierta (`cantidad > 0`).

**Símbolos soportados** para mapear a CoinGecko: `BTC`, `ETH`, `SOL`, `ADA`, `DOT`. Cualquier otro activo se busca usando su símbolo en minúsculas como `coin_id`.

**Ejemplo: agregar a la watchlist**

```bash
curl -X POST http://localhost:8000/analisis/watchlist \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"coin_id": "bitcoin", "precio_alerta": 70000}'
```

### Dashboard — `/dashboard`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/dashboard/completo` | 🔒 | Resumen, P&L por activo y últimos 5 trades (caché 30 s) |
| GET | `/dashboard/reporte/pdf` | 🔒 | Descarga el reporte en PDF |

### Binance Testnet — `/binance` y `/orders`

> Todo opera sobre **Binance Testnet**, no sobre una cuenta real.

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/binance/ping` | 🌐 | Verifica conexión con Binance |
| GET | `/binance/server-time` | 🌐 | Hora del servidor de Binance |
| GET | `/binance/balance` | 🔒 | Balance de la cuenta testnet |
| GET | `/binance/price/{symbol}` | 🌐 | Precio de un par (`btc` → `BTCUSDT`) |
| GET | `/binance/prices` | 🌐 | Precios de varios pares |
| GET | `/binance/symbol-info/{symbol}` | 🌐 | Información de un par |
| POST | `/orders/` | 🔒 | Colocar orden `MARKET`, `LIMIT` o `STOP_LOSS` |
| GET | `/orders/open` | 🔒 | Órdenes abiertas. Query opcional: `symbol` |
| DELETE | `/orders/{order_id}?symbol=BTCUSDT` | 🔒 | Cancelar una orden |

**Ejemplo: orden límite**

```bash
curl -X POST http://localhost:8000/orders/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "BUY", "order_type": "LIMIT", "quantity": 0.001, "price": 60000}'
```

Campos según el tipo de orden: `MARKET` usa `quantity`; `LIMIT` agrega `price`; `STOP_LOSS` agrega `stop_price`.

### Sistema — `/system`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/system/metrics` | 🌐 | Memoria, CPU y contador de peticiones |
| GET | `/system/endpoints` | 🌐 | Lista de todos los endpoints registrados |

## WebSockets

| Ruta | Auth | Descripción |
|------|------|-------------|
| `/ws/precios` | 🌐 | Precios **simulados** de BTC, ETH y SOL cada 5 s |
| `/ws/precios-reales` | 🌐 | Precios reales de CoinGecko (bitcoin, ethereum, solana) cada 30 s |
| `/ws/chat` | 🌐 | Chat simple: reenvía cada mensaje a todos los clientes |
| `/ws/notificaciones?token=<jwt>` | 🔒 | Notificaciones personales del usuario |

### Notificaciones

Conexión de ejemplo:

```
ws://localhost:8000/ws/notificaciones?token=<access_token>
```

Si el token es inválido o el usuario no existe, el servidor cierra la conexión con código `1008`.

Tipos de mensaje que se pueden recibir:

| `tipo` | Cuándo se envía |
|--------|-----------------|
| `conexion` | Al conectarse correctamente |
| `nuevo_trade` | Al crear un trade con `POST /trades/` |
| `precio_objetivo` | Un precio de la watchlist alcanzó o superó su `precio_alerta` |
| `pnl_significativo` | El P&L de un activo llegó a ±10% o más |

Las alertas de precio y P&L se revisan en background cada 60 segundos, solo para usuarios con una conexión activa.

## Tests

```bash
pytest
```

## Deploy

La API está desplegada en Render.com.
> https://trading-api-o9u2.onrender.com/

Y en Railway.com
> https://trading-api-production-4205.up.railway.app/docs

## Notas

- La información de precios proviene de CoinGecko y puede estar sujeta a límites de uso (rate limits); por eso se usa caché.
- Este proyecto es educativo y no constituye asesoría financiera.

# Trading API Pro

API REST para gestionar trades de criptomonedas, con autenticación JWT, análisis de P&L usando precios en vivo (CoinGecko), notificaciones por WebSocket e integración con Binance Testnet.

## Features

- ✅ Registro y login de usuarios (bcrypt + JWT)
- ✅ CRUD de trades protegido por usuario
- ✅ Búsqueda avanzada, paginación con ordenamiento y exportación a CSV
- ✅ Precios en tiempo real (CoinGecko) con caché en memoria
- ✅ Análisis de P&L con precios actuales, recomendaciones y reporte completo
- ✅ Watchlist con alertas de precio objetivo
- ✅ Dashboard consolidado y reporte en PDF
- ✅ WebSockets: precios, chat y notificaciones en tiempo real por usuario
- ✅ Integración con Binance Testnet (precios, balance y órdenes)
- ✅ Métricas del sistema y listado de endpoints
- ✅ Tests con Pytest
- ✅ Deploy en Render.com

## Tecnologías

- Python 3.12
- FastAPI
- PostgreSQL 16 (Docker / docker-compose en local, [Neon](https://neon.tech) en producción) con psycopg2
- Binance Testnet (python-binance)
- JWT (python-jose)
- bcrypt (passlib)
- httpx (cliente para CoinGecko)
- FPDF (reportes PDF)
- psutil (métricas)
- Pytest

## Instalación

### Requisitos previos

- Python 3.12 (solo si vas a correr la API fuera de Docker)
- Git
- Docker con el servicio activo (en Windows, abrir **Docker Desktop** antes de continuar)

### Pasos

1. Clonar el repositorio:

```bash
git clone <URL_DEL_REPOSITORIO>
cd <NOMBRE_DEL_PROYECTO>
```

2. Crear y activar el entorno virtual, e instalar las dependencias:

```bash
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
```

3. Crear un archivo `.env` en la raíz del proyecto con las variables descritas en la sección [Configuración](#configuración).

4. Levantar la base de datos y la API. Hay dos formas:

**Opción A — Base de datos en Docker y API local (recomendada para desarrollo)**

```bash
docker-compose up -d db
uvicorn app.main:app --reload
```

La API se conecta a PostgreSQL en `localhost:5432` usando el `DATABASE_URL` del `.env`.

**Opción B — Todo en Docker**

```bash
docker-compose up --build
```

Levanta la base de datos y la API juntas; la imagen de la API se construye con el `Dockerfile` del proyecto (Python 3.12). En este caso **no** hay que ejecutar `uvicorn`, porque el puerto de la API (`API_PORT`, por defecto 8000) ya estaría ocupado por el contenedor.

> En ambos casos la base de datos debe estar corriendo antes de iniciar la API. Las tablas se crean automáticamente al arrancar la aplicación.

La API queda disponible en `http://localhost:8000` y la documentación interactiva (Swagger) en `http://localhost:8000/docs`.

## Configuración

Crea un archivo `.env` en la raíz del proyecto (no lo subas al repositorio; asegúrate de que esté en `.gitignore`). Ejemplo:

```env
# Entorno
ENVIRONMENT=development
DEBUG=true
API_PORT=8000

# App
APP_NAME=Trading API Pro
APP_VERSION=4.0.0
APP_DESCRIPTION=API completa para gestión de trades con autenticación JWT
ENCODE=utf-8

# JWT
SECRET_KEY=cambia-esto-en-produccion
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Base de datos (Docker)
POSTGRES_USER=trading_user
POSTGRES_PASSWORD=trading_password
POSTGRES_DB=trading_db
DATABASE_URL=postgresql://trading_user:trading_password@localhost:5432/trading_db

# CORS (orígenes separados por coma)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Binance Testnet
BINANCE_TESTNET=true
BINANCE_API_KEY=tu_api_key_testnet
BINANCE_SECRET_KEY=tu_secret_key_testnet

# CoinGecko
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_API_KEY=tu_api_key_coingecko
```

| Variable | Descripción |
|----------|-------------|
| `ENVIRONMENT` | `development` o `production`. En producción se deshabilitan `/docs`, `/redoc` y `/openapi.json` |
| `SECRET_KEY` | Clave para firmar los JWT. **Cambiarla en producción** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del token de acceso |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciales de la base que crea `docker-compose` |
| `DATABASE_URL` | Cadena de conexión. Para correr la API fuera de Docker usa `localhost`; dentro del compose se sobrescribe con el host `db` |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma |
| `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` | Claves de Binance **Testnet** (se generan en [testnet.binance.vision](https://testnet.binance.vision)) |
| `COINGECKO_API_KEY` | API key de CoinGecko |

**Variables obligatorias:** `SECRET_KEY`, `ALGORITHM`, `DATABASE_URL`, `DEBUG`, `APP_NAME`, `APP_VERSION` y `APP_DESCRIPTION`. Si falta alguna, la aplicación no arranca o falla al usar la autenticación.

**Variables con valor por defecto:** `ENVIRONMENT` (`development`), `ENCODE` (`utf-8`), `BINANCE_TESTNET` (`true`), `COINGECKO_BASE_URL`, `ACCESS_TOKEN_EXPIRE_MINUTES` (`60`). Si no configuras las claves de Binance se muestra una advertencia al iniciar y los endpoints de `/binance` y `/orders` no funcionarán.

Las variables `POSTGRES_*` y `API_PORT` las usa `docker-compose`.

## Autenticación

Los endpoints protegidos requieren un token JWT en el header:

```
Authorization: Bearer <access_token>
```

Para obtenerlo:

```bash
# 1. Registro
curl -X POST http://localhost:8000/usuarios/registro \
  -H "Content-Type: application/json" \
  -d '{"username": "juan", "email": "juan@mail.com", "password": "secreto123"}'

# 2. Login
curl -X POST http://localhost:8000/usuarios/login \
  -H "Content-Type: application/json" \
  -d '{"username": "juan", "password": "secreto123"}'
```

La respuesta del login incluye `access_token`, `token_type` y los datos básicos del usuario.

## Endpoints

La columna **Auth** indica si el endpoint requiere JWT (🔒) o es público (🌐).

### General

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | 🌐 | Mensaje de bienvenida y versión |
| GET | `/health` | 🌐 | Health check (usado por Docker) |
| GET | `/info` | 🌐 | Información de la API |

La API aplica un límite de **100 peticiones por 60 segundos** (rate limit) y registra cada petición mediante un middleware de logging. Los archivos estáticos se sirven desde `/static`.

### Usuarios — `/usuarios`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/usuarios/registro` | 🌐 | Registrar usuario |
| POST | `/usuarios/login` | 🌐 | Login, devuelve JWT |
| GET | `/usuarios/me` | 🔒 | Info del usuario autenticado |
| GET | `/usuarios/{user_id}` | 🌐 | Obtener usuario por ID |

### Trades — `/trades`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/trades/` | 🔒 | Crear trade (envía notificación por WebSocket) |
| GET | `/trades/` | 🔒 | Listar trades propios. Query: `skip`, `limit` (máx. 100), `tipo`, `activo` |
| GET | `/trades/paginado` | 🔒 | Paginación con orden. Query: `page`, `per_page`, `orden`, `direccion` |
| GET | `/trades/{id}` | 🌐 | Obtener un trade |
| PATCH | `/trades/{id}` | 🔒 | Actualizar trade (solo el dueño) |
| DELETE | `/trades/{id}` | 🔒 | Eliminar trade (solo el dueño) |
| GET | `/trades/buscar` | 🌐 | Búsqueda avanzada. Query: `activo`, `tipo`, `precio_min`, `precio_max`, `fecha_desde`, `fecha_hasta` |
| GET | `/trades/exportar/csv` | 🌐 | Exporta trades a CSV |
| GET | `/trades/estadisticas` | 🌐 | Totales, volumen, precios promedio y activos operados |
| GET | `/trades/resumen/pnl` | 🌐 | P&L por flujo de caja (ventas − compras) |
| GET | `/trades/resumen/mejor-trade` | 🌐 | Venta de mayor valor |
| GET | `/trades/resumen/por-fecha` | 🌐 | Trades en un rango. Query: `desde`, `hasta` |
| GET | `/trades/resumen/por-activo/{activo}` | 🌐 | Compras, ventas, P&L y precios promedio de un activo |

**Ejemplo: crear trade**

```bash
curl -X POST http://localhost:8000/trades/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"tipo": "compra", "activo": "btc", "precio": 50000, "cantidad": 0.1}'
```

```json
{
  "id": 1,
  "usuario_id": 1,
  "tipo": "compra",
  "activo": "BTC",
  "precio": 50000,
  "cantidad": 0.1,
  "fecha": "2026-01-15 10:30"
}
```

`tipo` acepta `compra` o `venta`. El campo `activo` se normaliza a mayúsculas.

### Precios (CoinGecko) — `/precios`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/precios/{coin_id}` | 🌐 | Precio actual. Query: `moneda` (default `usd`), `use_cache` (default `true`) |
| GET | `/precios/multiples?coins=bitcoin,ethereum` | 🌐 | Precios de varias monedas. Query: `coins`, `moneda` |
| GET | `/precios/buscar/{query}` | 🌐 | Buscar moneda por nombre (máx. 10 resultados) |
| GET | `/precios/cache/stats` | 🌐 | Estadísticas del caché |
| DELETE | `/precios/cache/clear` | 🌐 | Limpiar el caché |

Los `coin_id` son los IDs de CoinGecko (`bitcoin`, `ethereum`, etc.). El precio individual se cachea 30 segundos.

### Análisis — `/analisis`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/analisis/pnl-en-vivo` | 🔒 | P&L por activo y total con precios actuales (caché 60 s) |
| GET | `/analisis/recomendaciones` | 🔒 | Sugerencia por activo según su P&L |
| GET | `/analisis/reporte-completo` | 🔒 | Estadísticas, P&L, mejor y peor activo |
| POST | `/analisis/watchlist` | 🔒 | Agregar moneda con precio de alerta |
| GET | `/analisis/watchlist` | 🔒 | Ver watchlist del usuario |

**Cálculo de P&L:** para cada activo se calcula la cantidad neta (compras − ventas), el costo neto y el valor actual (`cantidad × precio actual`). El P&L es `valor_actual − costo_total`.

**Recomendaciones:**

| P&L del activo | Sugerencia |
|----------------|------------|
| ≤ −10% | posible oportunidad de compra |
| ≥ +20% | considerar tomar ganancias |
| otro | sin recomendación |

Solo se evalúan activos con posición abierta (`cantidad > 0`).

**Símbolos soportados** para mapear a CoinGecko: `BTC`, `ETH`, `SOL`, `ADA`, `DOT`. Cualquier otro activo se busca usando su símbolo en minúsculas como `coin_id`.

**Ejemplo: agregar a la watchlist**

```bash
curl -X POST http://localhost:8000/analisis/watchlist \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"coin_id": "bitcoin", "precio_alerta": 70000}'
```

### Dashboard — `/dashboard`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/dashboard/completo` | 🔒 | Resumen, P&L por activo y últimos 5 trades (caché 30 s) |
| GET | `/dashboard/reporte/pdf` | 🔒 | Descarga el reporte en PDF |

### Binance Testnet — `/binance` y `/orders`

> Todo opera sobre **Binance Testnet**, no sobre una cuenta real.

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/binance/ping` | 🌐 | Verifica conexión con Binance |
| GET | `/binance/server-time` | 🌐 | Hora del servidor de Binance |
| GET | `/binance/balance` | 🔒 | Balance de la cuenta testnet |
| GET | `/binance/price/{symbol}` | 🌐 | Precio de un par (`btc` → `BTCUSDT`) |
| GET | `/binance/prices` | 🌐 | Precios de varios pares |
| GET | `/binance/symbol-info/{symbol}` | 🌐 | Información de un par |
| POST | `/orders/` | 🔒 | Colocar orden `MARKET`, `LIMIT` o `STOP_LOSS` |
| GET | `/orders/open` | 🔒 | Órdenes abiertas. Query opcional: `symbol` |
| DELETE | `/orders/{order_id}?symbol=BTCUSDT` | 🔒 | Cancelar una orden |

**Ejemplo: orden límite**

```bash
curl -X POST http://localhost:8000/orders/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "BUY", "order_type": "LIMIT", "quantity": 0.001, "price": 60000}'
```

Campos según el tipo de orden: `MARKET` usa `quantity`; `LIMIT` agrega `price`; `STOP_LOSS` agrega `stop_price`.

### Sistema — `/system`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/system/metrics` | 🌐 | Memoria, CPU y contador de peticiones |
| GET | `/system/endpoints` | 🌐 | Lista de todos los endpoints registrados |

## WebSockets

| Ruta | Auth | Descripción |
|------|------|-------------|
| `/ws/precios` | 🌐 | Precios **simulados** de BTC, ETH y SOL cada 5 s |
| `/ws/precios-reales` | 🌐 | Precios reales de CoinGecko (bitcoin, ethereum, solana) cada 30 s |
| `/ws/chat` | 🌐 | Chat simple: reenvía cada mensaje a todos los clientes |
| `/ws/notificaciones?token=<jwt>` | 🔒 | Notificaciones personales del usuario |

### Notificaciones

Conexión de ejemplo:

```
ws://localhost:8000/ws/notificaciones?token=<access_token>
```

Si el token es inválido o el usuario no existe, el servidor cierra la conexión con código `1008`.

Tipos de mensaje que se pueden recibir:

| `tipo` | Cuándo se envía |
|--------|-----------------|
| `conexion` | Al conectarse correctamente |
| `nuevo_trade` | Al crear un trade con `POST /trades/` |
| `precio_objetivo` | Un precio de la watchlist alcanzó o superó su `precio_alerta` |
| `pnl_significativo` | El P&L de un activo llegó a ±10% o más |

Las alertas de precio y P&L se revisan en background cada 60 segundos, solo para usuarios con una conexión activa.

## Tests

```bash
pytest
```

## Deploy

La API se puede desplegar en plataformas como Render o Railway usando el `Dockerfile` del proyecto.

- **URL de producción Render:** `https://trading-api-o9u2.onrender.com/`
- **URL de producción Railway:** `https://trading-api-production-4205.up.railway.app/`
- **Variables de entorno:** el `.env` no se sube al repositorio, así que hay que cargar las variables desde el panel de la plataforma (las mismas de la sección [Configuración](#configuración)). En producción:
  - `ENVIRONMENT=production` (deshabilita `/docs`, `/redoc` y `/openapi.json`)
  - `DATABASE_URL` con la connection string de tu base en [Neon](https://neon.tech) (PostgreSQL administrado). Debe incluir `?sslmode=require`. Si falta esta variable o apunta a `localhost` (la base local de Docker), la app no arranca
  - `SECRET_KEY` distinta a la de desarrollo
  - `CORS_ORIGINS` con la URL de tu frontend
  - `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` y `BINANCE_TESTNET=true`
- **Región:** Binance bloquea conexiones desde ciertas regiones (por ejemplo, servidores en EE. UU.). Si el arranque falla con el error `Service unavailable from a restricted location`, elige una región de Europa o Asia para el servicio. Probado: Railway en Países Bajos y Render en Frankfurt. En Render la región no se puede cambiar en un servicio existente: hay que crear uno nuevo.

## Notas

- La información de precios proviene de CoinGecko y puede estar sujeta a límites de uso (rate limits); por eso se usa caché.
- Este proyecto es educativo y no constituye asesoría financiera.