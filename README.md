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
- ✅ Gestión de riesgo: tamaño de posición por riesgo fijo, stop-loss/take-profit, límites y análisis de riesgo del portafolio
- ✅ Backtesting de estrategias (cruce de medias, RSI) con comisiones, slippage y gestión de riesgo
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

**Variables obligatorias:** `SECRET_KEY`, `ALGORITHM`, `DATABASE_URL`, `APP_NAME`, `APP_VERSION` y `APP_DESCRIPTION`. Si falta alguna, la aplicación no arranca y el error indica cuáles faltan. `DEBUG` es opcional (por defecto `false`).

**Validaciones en producción** (`ENVIRONMENT=production`): `SECRET_KEY` debe tener al menos 32 caracteres y no puede ser un valor de ejemplo, y `CORS_ORIGINS` debe listar orígenes concretos (no vacío ni `*`). Para generar una clave: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

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

> **Aislamiento por usuario:** todos los endpoints de `/trades` (búsqueda, CSV, estadísticas, resúmenes y P&L) devuelven únicamente los trades del usuario autenticado.

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
| GET | `/usuarios/{user_id}` | 🔒 | Obtener el propio perfil (404 si el ID es de otro usuario) |

### Trades — `/trades`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/trades/` | 🔒 | Crear trade (envía notificación por WebSocket) |
| GET | `/trades/` | 🔒 | Listar trades propios. Query: `skip`, `limit` (máx. 100), `tipo`, `activo` |
| GET | `/trades/paginado` | 🔒 | Paginación con orden. Query: `page`, `per_page`, `orden`, `direccion` |
| GET | `/trades/{id}` | 🔒 | Obtener un trade propio (404 si es de otro usuario) |
| PATCH | `/trades/{id}` | 🔒 | Actualizar trade (solo el dueño) |
| DELETE | `/trades/{id}` | 🔒 | Eliminar trade (solo el dueño) |
| GET | `/trades/buscar` | 🔒 | Búsqueda avanzada. Query: `activo`, `tipo`, `precio_min`, `precio_max`, `fecha_desde`, `fecha_hasta` |
| GET | `/trades/exportar/csv` | 🔒 | Exporta trades a CSV |
| GET | `/trades/estadisticas` | 🔒 | Totales, volumen, precios promedio y activos operados |
| GET | `/trades/resumen/pnl` | 🔒 | P&L por flujo de caja (ventas − compras) |
| GET | `/trades/resumen/mejor-trade` | 🔒 | Venta de mayor valor |
| GET | `/trades/resumen/por-fecha` | 🔒 | Trades en un rango. Query: `desde`, `hasta` |
| GET | `/trades/resumen/por-activo/{activo}` | 🔒 | Compras, ventas, P&L y precios promedio de un activo |

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
| GET | `/precios/cache/stats` | 🔒 | Estadísticas del caché |
| DELETE | `/precios/cache/clear` | 🔒 | Limpiar el caché |

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

### Riesgo — `/riesgo`

Todo es **solo spot, posiciones largas y sin apalancamiento**. Los porcentajes van en "puntos" (`1.0` = 1 %).

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/riesgo/limites` | 🔒 | Límites por defecto (1 % de riesgo por trade, posición máx. 25 %, pérdida diaria 3 %, drawdown 20 %, 5 posiciones) |
| POST | `/riesgo/tamano-posicion` | 🔒 | Unidades a comprar para arriesgar como máximo `riesgo_pct` del capital si salta el stop |
| POST | `/riesgo/niveles-salida` | 🔒 | Precios de stop-loss y take-profit (por % o por ratio riesgo/beneficio) |
| POST | `/riesgo/evaluar-trade` | 🔒 | Comprueba una operación propuesta contra los límites. **No ejecuta ni registra nada** |
| GET | `/riesgo/portafolio?capital=` | 🔒 | Exposición, concentración, win rate, profit factor y drawdown de **tus** trades registrados |

`tamano-posicion` calcula `cantidad = (capital × riesgo_pct) / (entrada − stop)`, la limita por el tamaño máximo de posición y
por el saldo disponible, y trunca (nunca redondea hacia arriba). `limitado_por` indica cuál de los tres límites fue el que mandó.

```bash
curl -X POST http://localhost:8000/riesgo/tamano-posicion \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"capital": 10000, "entrada": 100, "stop": 95, "riesgo_pct": 1}'
# -> {"cantidad": 20.0, "valor_posicion": 2000.0, "riesgo_monetario": 100.0, "limitado_por": "riesgo", ...}
```

`/riesgo/portafolio` usa costo promedio ponderado y **no usa precios de mercado**: mide lo ya realizado y la exposición a costo.
Si hay ventas por encima de la posición registrada solo cuenta la parte cubierta por compras previas y lo indica en `advertencias`.

### Backtest — `/backtest`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/backtest/estrategias` | 🔒 | Estrategias disponibles y sus parámetros por defecto |
| POST | `/backtest/` | 🔒 | Simula una estrategia y devuelve métricas, operaciones y curva de equity |

Estrategias: `cruce_medias` (`rapida`, `lenta`) y `rsi` (`periodo`, `sobreventa`, `sobrecompra`).
Los datos se indican con **una** de dos fuentes: `precios` (lista de cierres, de 30 a 5.000) o `coin_id` de CoinGecko
(precios diarios, `dias` de 30 a 365).

```bash
curl -X POST http://localhost:8000/backtest/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"estrategia": "cruce_medias", "parametros_estrategia": {"rapida": 10, "lenta": 30},
       "coin_id": "bitcoin", "dias": 365, "capital_inicial": 10000,
       "riesgo_por_trade_pct": 1, "stop_loss_pct": 5, "comision_pct": 0.1, "slippage_pct": 0.05}'
```

**Reglas del simulador** (para no producir resultados mejores que la realidad):

- **Sin mirar el futuro:** la señal calculada con datos hasta la barra *i* se ejecuta al precio de la barra *i+1*; una señal en la última barra no se ejecuta.
- Una posición a la vez, solo largos, sin apalancamiento. Comisión y slippage en contra en cada lado.
- El tamaño de cada operación sale de la misma lógica de `/riesgo/tamano-posicion`. Con los valores por defecto
  (riesgo 1 %, stop 5 %, posición máx. 25 %) la estrategia pasa buena parte del tiempo con poco capital invertido: es la consecuencia de las reglas de riesgo.
- Stop-loss y take-profit se evalúan **al cierre** de cada barra (solo hay precios de cierre): si el precio ya saltó el nivel, se sale al cierre, que puede ser peor que el stop.
  Por eso la pérdida real puede superar el riesgo configurado.
- Tras un stop/take-profit no se vuelve a entrar hasta que la señal se apague y se vuelva a encender.
- Si el drawdown de la cuenta alcanza `drawdown_max_pct`, se cierra la posición y se detiene la operativa hasta el final.
- Una posición abierta al terminar los datos se cierra al último precio.

**Métricas:** retorno total y anualizado (solo con 1 año o más de datos), buy & hold de referencia, drawdown máximo, Sharpe
(sin tasa libre de riesgo, anualizado con `periodos_por_ano`, 365 por defecto), nº de operaciones, win rate, profit factor,
mejor/peor operación y tiempo en el mercado. `advertencias` avisa, por ejemplo, cuando hay menos de 30 operaciones y las estadísticas no son fiables.

> ⚠️ Un backtest describe el pasado y, si ajustas los parámetros mirando los mismos datos, está sobreajustado. No es una promesa de resultados futuros ni asesoría financiera.

### Sistema — `/system`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/system/metrics` | 🔒 | Memoria, CPU y contador de peticiones |
| GET | `/system/endpoints` | 🔒 | Lista de todos los endpoints registrados |

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

Los tests corren contra una base PostgreSQL **real de pruebas**. El nombre de la base debe terminar en `_test`
(si no, pytest se niega a ejecutar) porque antes de cada test se vacían las tablas.

```bash
# crear la base de pruebas (una sola vez)
docker-compose up -d db
docker-compose exec db psql -U trading_user -d postgres -c "CREATE DATABASE trading_test;"

# correr los tests: DATABASE_URL debe apuntar a la base *_test
export DATABASE_URL=postgresql://trading_user:trading_password@localhost:5432/trading_test
pytest
```

Si `DATABASE_URL` (o el `.env`) apunta a una base cuyo nombre no termina en `_test`, pytest se niega a ejecutar para no vaciar datos reales.
Los tests de riesgo y backtesting usan series sintéticas con resultados calculados a mano; no necesitan red.

Además de las variables de la sección [Configuración](#configuración) (`SECRET_KEY`, `ALGORITHM`, etc.), no se necesita
conexión a Binance ni a CoinGecko para correr la suite.

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