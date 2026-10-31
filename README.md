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
- ✅ Rate limit por IP real (también detrás de proxies y con WebSockets) y bloqueo del login contra fuerza bruta
- ✅ Métricas del sistema y listado de endpoints
- ✅ Tests con Pytest
- ✅ Deploy en Render.com

## Tecnologías

- Python 3.12
- FastAPI
- PostgreSQL 16 (Docker / docker-compose en local, [Neon](https://neon.tech) en producción)
- SQLAlchemy 2.0 (ORM síncrono con pool de conexiones) + Alembic (migraciones), con psycopg2 como driver
- Redis (opcional: necesario para varios procesos o instancias; comparte el rate limit, el chat, las notificaciones y el caché)
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
alembic upgrade head          # crea/actualiza las tablas (ver "Base de datos y migraciones")
uvicorn app.main:app --reload
```

La API se conecta a PostgreSQL en `localhost:5432` usando el `DATABASE_URL` del `.env`.

**Opción B — Todo en Docker**

```bash
docker-compose up --build
```

Levanta la base de datos y la API juntas; la imagen de la API se construye con el `Dockerfile` del proyecto (Python 3.12) y **aplica las migraciones automáticamente antes de arrancar**. En este caso **no** hay que ejecutar `uvicorn`, porque el puerto de la API (`API_PORT`, por defecto 8000) ya estaría ocupado por el contenedor.

> En ambos casos la base de datos debe estar corriendo antes de iniciar la API. Con la opción A tienes que ejecutar `alembic upgrade head` tú (la app ya no crea tablas al arrancar).

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
| `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW` | Peticiones permitidas por IP en cada ventana de tantos segundos (por defecto `100` cada `60`) |
| `LOGIN_RATE_LIMIT` | `POST /usuarios/login` por IP y minuto (por defecto `20`) |
| `REGISTER_RATE_LIMIT` | `POST /usuarios/registro` por IP y hora (por defecto `10`) |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_SECONDS` | Fallos de login por (IP, usuario) antes de bloquear (por defecto `5`) y duración del bloqueo en segundos (por defecto `900`) |
| `TRUSTED_PROXY_COUNT` | Proxies de confianza entre el cliente y la app (por defecto `0`). **Imprescindible detrás de Render/Railway/Cloudflare**; ver [Rate limit y protección del login](#rate-limit-y-protección-del-login) |
| `REDIS_URL` | `redis://...` o `rediss://...` para compartir entre procesos e instancias los contadores del rate limit, el chat, las notificaciones y el vaciado del caché (opcional; vacío = memoria del proceso, solo válido con un proceso) |
| `BINANCE_TESTNET` | `true` (por defecto) opera en la testnet. Solo acepta `true/false`, `1/0`, `yes/no`, `on/off`: cualquier otro valor (p. ej. un typo) **impide arrancar** en vez de interpretarse |
| `BINANCE_ALLOW_LIVE` | `false` por defecto. `BINANCE_TESTNET=false` (dinero REAL) exige además `BINANCE_ALLOW_LIVE=true`; sin él la app no arranca |
| `MARKET_RATE_LIMIT` | Consultas de mercado públicas por IP y minuto (por defecto `30`; ver [Límites por abuso](#límites-por-abuso)) |
| `REPORT_RATE_LIMIT` | Informes PDF por usuario y minuto (por defecto `10`) |
| `WATCHLIST_MAX_ITEMS` | Monedas máximas en la watchlist de cada usuario (por defecto `50`) |
| `ALERT_COOLDOWN_SECONDS` | Segundos mínimos entre dos alertas iguales por WebSocket (por defecto `3600`) |
| `WEB_CONCURRENCY` | Procesos (workers) de uvicorn (por defecto `1`). Con más de uno **`REDIS_URL` es obligatorio**: la app no arranca sin él |
| `DB_POOL_SIZE` | Conexiones que cada proceso mantiene abiertas hacia PostgreSQL (por defecto `5`) |
| `DB_MAX_OVERFLOW` | Conexiones extra que se pueden abrir en picos (por defecto `10`) |
| `DB_POOL_TIMEOUT` | Segundos que una petición espera una conexión libre antes de fallar (por defecto `10`) |
| `DB_POOL_RECYCLE` | Segundos tras los que se renueva una conexión (por defecto `300`; útil con Neon, que corta las inactivas) |
| `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` | Claves de Binance **Testnet** (se generan en [testnet.binance.vision](https://testnet.binance.vision)) |
| `COINGECKO_API_KEY` | API key de CoinGecko |

**Variables obligatorias:** `SECRET_KEY`, `ALGORITHM`, `DATABASE_URL`, `APP_NAME`, `APP_VERSION` y `APP_DESCRIPTION`. Si falta alguna, la aplicación no arranca y el error indica cuáles faltan. `DEBUG` es opcional (por defecto `false`).

**Validaciones en producción** (`ENVIRONMENT=production`): `SECRET_KEY` debe tener al menos 32 caracteres y no puede ser un valor de ejemplo, y `CORS_ORIGINS` debe listar orígenes concretos (no vacío ni `*`). Para generar una clave: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

**Variables con valor por defecto:** `ENVIRONMENT` (`development`), `ENCODE` (`utf-8`), `BINANCE_TESTNET` (`true`), `COINGECKO_BASE_URL`, `ACCESS_TOKEN_EXPIRE_MINUTES` (`60`). Si no configuras las claves de Binance se muestra una advertencia al iniciar y los endpoints de `/binance` y `/orders` no funcionarán.

Las variables `POSTGRES_*` y `API_PORT` las usa `docker-compose`.

## Base de datos y migraciones

El acceso a datos usa **SQLAlchemy 2.0** (`app/models.py`, `app/database.py`) con un **pool de conexiones**: las conexiones se reutilizan
en vez de abrir una nueva (TCP + TLS) en cada consulta. El esquema se gestiona con **Alembic** (`alembic/versions/`).

```bash
alembic upgrade head                              # aplica las migraciones pendientes
alembic current                                   # versión actual de la base
alembic revision --autogenerate -m "describe el cambio"   # tras cambiar app/models.py
alembic upgrade head --sql                        # muestra el SQL sin ejecutarlo
```

- Si cambias `app/models.py`, **crea su migración**: los tests fallan si los modelos y las migraciones difieren.
- La migración `0001` adopta el esquema que ya existía: en una base con las tablas creadas por la versión anterior **no modifica nada**; en una base vacía crea todo.
  La `0002` ensancha `watchlist.coin_id` a 64 caracteres (los IDs de CoinGecko no cabían en 10).
  La `0003` añade `usuarios.rol` (`usuario` | `admin`); los usuarios existentes quedan como `usuario`.
  La `0004` crea las tablas del paper trading (`paper_wallet`, `paper_positions`, `paper_trades`); no toca datos existentes.
  La `0005` añade `paper_orders` (órdenes pendientes LIMIT/STOP).
- Con varias instancias arrancando a la vez, Alembic las serializa con un bloqueo de PostgreSQL: una migra y las demás esperan.
- `alembic downgrade base` **borra todas las tablas y sus datos**; solo para desarrollo.
- **Dimensionar el pool:** el máximo de conexiones hacia la base es `(DB_POOL_SIZE + DB_MAX_OVERFLOW) × número de procesos`.
  Debe quedar por debajo del límite de tu plan de PostgreSQL (en Neon gratuito es bajo: reduce los valores si ves errores de conexión).
- `DATABASE_URL` acepta tanto `postgresql://` como `postgres://` (algunos proveedores entregan este último).

## Rate limit y protección del login

**Límites por IP** (ventana fija; configurables, ver la tabla de variables):

| Qué | Límite por defecto |
|-----|--------------------|
| Cualquier petición (y cada conexión WebSocket nueva) | 100 cada 60 s |
| `POST /usuarios/login` | 20 por minuto |
| `POST /usuarios/cambiar-password` | `LOGIN_RATE_LIMIT` por minuto, más el bloqueo por fallos del login |
| `POST /usuarios/registro` | 10 por hora |

Al superarlo la API responde `429` con `Retry-After` (segundos a esperar). Las respuestas normales llevan `X-RateLimit-Limit`, `X-RateLimit-Remaining` y
`X-RateLimit-Reset`. `/health` no gasta cupo. Una conexión WebSocket rechazada recibe un `403` en el handshake.

**Bloqueo del login por intentos fallidos.** Se cuentan los fallos en tres cubos y basta con que uno llegue a su tope para recibir `429` hasta que termine
el bloqueo (`LOGIN_LOCKOUT_SECONDS`):

| Cubo | Tope (con `LOGIN_MAX_FAILURES=5`) | Frena |
|------|-----------------------------------|-------|
| IP + usuario | 5 | probar contraseñas de una cuenta |
| usuario | 20 | un ataque repartido entre muchas IPs |
| IP | 30 | probar muchos usuarios desde una IP |

- Los fallos de usuarios que **no existen** cuentan igual, así el `429` no revela qué cuentas existen. El login también tarda lo mismo exista o no el usuario.
- Durante un bloqueo **ni la contraseña correcta entra**. Un login correcto reinicia solo el cubo (IP + usuario), no el del usuario.
- Compromiso conocido: con el cubo «usuario», alguien con muchas IPs puede bloquear una cuenta ajena durante `LOGIN_LOCKOUT_SECONDS`. Es el precio de frenar ataques distribuidos;
  desde su propia IP la víctima nunca queda bloqueada por un tercero a través del cubo «IP + usuario».
- El nombre de usuario no distingue mayúsculas en el login, y las contraseñas de más de 72 bytes se rechazan en el registro (límite de bcrypt).

### Configurar `TRUSTED_PROXY_COUNT` (importante en producción)

Detrás de un proxy (Render, Railway, Cloudflare...) el «cliente» que ve la app es el proxy, y **todos los usuarios compartirían un único cupo**.
Para usar la IP real hay que decirle a la app cuántos proxies de confianza hay entre el cliente e ella:

- `TRUSTED_PROXY_COUNT=0` (por defecto): `X-Forwarded-For` se **ignora por completo**. Es lo seguro en local o sin proxy.
- `TRUSTED_PROXY_COUNT=N`: la IP del cliente es la entrada N contando **desde la derecha** de `X-Forwarded-For` (cada proxy de confianza añade la dirección de
  quien le habló). Lo que haya a la izquierda lo escribe el cliente y se ignora, así que falsificar la cabecera no sirve para evadir el límite.
- Si la cabecera tiene menos entradas que `N` o no contiene una IP, se usa la dirección del socket.
- Las IPv6 se agrupan por `/64` (un cliente suele controlar un `/64` entero) y las IPv4 mapeadas en IPv6 cuentan como IPv4.

**Cómo saber qué valor poner:** el número depende de tu infraestructura y no se puede deducir desde el código. Despliega con `TRUSTED_PROXY_COUNT=1`, haz una petición
desde tu casa y mira la línea `→ GET /... ip=<dirección>` del log: si `<dirección>` es tu IP pública, está bien; si es siempre la misma para todos o es una IP
de la plataforma, prueba con `2` (por ejemplo, Cloudflare delante de otro proxy). Con un valor demasiado alto la app usará una entrada que escribe el cliente.
Con `ENVIRONMENT=production` y `TRUSTED_PROXY_COUNT=0` la app deja un aviso en el log al arrancar.

> ⚠️ **No uses `FORWARDED_ALLOW_IPS=*` ni `--forwarded-allow-ips='*'` con uvicorn.** Algunas guías lo recomiendan, pero uvicorn pasaría a tomar la entrada **más a la
> izquierda** de `X-Forwarded-For` (la escribe el cliente) y bastaría cambiar esa cabecera para evadir el rate limit y el bloqueo del login. El `Dockerfile` y el `Procfile`
> arrancan con `--no-proxy-headers` para que uvicorn no toque la IP del cliente; la única que cuenta es la que calcula `TRUSTED_PROXY_COUNT`.

### Varios procesos o instancias

Cada WebSocket vive en el proceso que lo aceptó. Con `REDIS_URL` todo mensaje pasa por un bus pub/sub de Redis (`app/services/bus.py`): se publica una vez y **cada proceso, el
emisor incluido, lo entrega a sus propias conexiones**, así que no hay duplicados. Cubre el chat, las notificaciones personales (p. ej. un trade creado por HTTP en un proceso
llega al WebSocket abierto en otro) y el vaciado del caché de precios (`DELETE /precios/cache/clear` lo vacía en todos).

- Si Redis falla la API **no se cae**: los mensajes se entregan solo a las conexiones de ese proceso y la suscripción se reintenta con espera creciente (hasta 30 s) hasta recuperarse.
- Las alertas de precio y P&L se revisan en cada proceso para sus usuarios conectados, con un turno por usuario compartido vía Redis para que no se envíen duplicadas.
- El motor de órdenes pendientes del paper trading ya era seguro con varios procesos (ver [Paper trading](#paper-trading--paper)).
- El tope de conexiones de chat por usuario (`CHAT_MAX_CONNECTIONS_PER_USER`) cuenta **todos los procesos** (app/services/conexiones.py). Cada conexión es un registro en Redis con caducidad (90 s) que se
  renueva mientras la conexión vive y se libera al cerrar: si un proceso muere sin cerrar sus conexiones, sus cupos vencen solos. Si Redis falla, el tope pasa a contarse por proceso hasta que vuelva.
  El límite de mensajes también es global (mismo limitador de Redis).
- Las suscripciones usan una conexión dedicada de Redis por proceso (además de la del limitador).

### Límites por abuso

Además del límite general por IP, las rutas que gastan una cuota externa o CPU tienen el suyo (mismo limitador: memoria o Redis; si falla, se deja pasar y se avisa en el log):

| Qué | Límite | Clave |
|-----|--------|-------|
| Datos de mercado públicos (`/precios/*`, `/binance/ping`, `/binance/server-time`, `/binance/price`, `/binance/prices`, `/binance/symbol-info`) | `MARKET_RATE_LIMIT` por minuto | IP (compartido entre todas esas rutas) |
| Informe PDF (`/dashboard/reporte/pdf`) | `REPORT_RATE_LIMIT` por minuto | usuario |
| Watchlist (`POST /analisis/watchlist`) | `WATCHLIST_MAX_ITEMS` monedas (409 al superarlo) | usuario; se comprueba bajo bloqueo, así que altas simultáneas no lo exceden |

Cada consulta nueva de mercado gasta cuota de CoinGecko o Binance; sin tope, un script la agota para todos. Las peticiones inválidas (422) **también cuentan**, para que escanear identificadores no salga gratis.

**Validación de entradas que acaban en servicios externos:** `coin_id` (`^[a-z0-9][a-z0-9-]{0,63}$`), `moneda` (2-10 letras), símbolos de Binance (2-20 alfanuméricos), búsqueda (1-50 caracteres sencillos) y
`/precios/multiples` (máximo 20 monedas, 1000 caracteres, sin repetidas). Lo que no cumple da 422 **sin tocar la red**. Los `coin_id` de la watchlist se pasan a minúsculas.

**Cabeceras de seguridad:** todas las respuestas (también 401, 404, 422, 429 y las de CORS) llevan `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` y `Referrer-Policy: no-referrer`
(las URLs de los WebSockets llevan `?token=`). Las de la API añaden `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` y `Cache-Control: no-store` (si la ruta no puso la suya), y en producción
`Strict-Transport-Security` (un año). `/static`, `/docs` y `/redoc` quedan fuera de CSP y no-store. El `HSTS` se envía también detrás de un proxy que termina el HTTPS: el navegador lo recibe por HTTPS.

**Caché:** el caché en memoria está acotado a 5000 entradas: al llenarse descarta primero lo vencido y después lo más antiguo, para que un visitante no pueda agotar la memoria inventando claves.

### Una instancia o varias (Redis)

- **Sin `REDIS_URL`** los contadores viven en la memoria del proceso: correcto con **una sola instancia y un solo worker** (como viene configurado).
- Con **varias instancias o workers** cada una contaría por su cuenta y el límite real se multiplicaría. Ahí hay que definir `REDIS_URL` (por ejemplo, un Redis
  administrado de tu plataforma) para compartir los contadores. Cada operación es atómica.
- Si Redis falla, la API **no se cae**: usa contadores locales por instancia durante unos segundos, deja un aviso en el log y vuelve a intentar Redis. Mientras
  tanto la protección es «por instancia».
- Con Redis, el límite se aplica **a cada petición** y añade una ida y vuelta de red (con tiempos de espera de 0,3 s).
- Los límites no sustituyen a una protección en el borde (Cloudflare, WAF) contra un ataque de denegación de servicio volumétrico: el tráfico llega igualmente hasta la app.

## Roles (administradores)

Hay dos roles: `usuario` (por defecto) y `admin`. Solo los administradores pueden ver/vaciar el caché (`/precios/cache/*`) y ver `/system/*` (marcados con 👑); los demás
reciben **403**. El rol se lee de la base en **cada petición**, así que quitárselo a alguien surte efecto al instante, aunque conserve su token.

La API pública **nunca** asigna roles: el registro ignora cualquier campo `rol`. El primer admin se crea desde una shell de la instancia, después de que esa persona se registre:

```bash
python scripts/gestionar_roles.py promover ana    # -> admin
python scripts/gestionar_roles.py degradar ana    # -> usuario
python scripts/gestionar_roles.py listar          # quiénes son admin
```

(`docker compose exec api python scripts/gestionar_roles.py promover ana` si usas Docker.) Tras promover, `ana` no tiene que volver a iniciar sesión.
`GET /usuarios/me` y el login devuelven el campo `rol`.

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

La columna **Auth** indica si el endpoint requiere JWT (🔒), es público (🌐) o exige además el rol de administrador (👑, ver [Roles](#roles-administradores)).

> **Aislamiento por usuario:** todos los endpoints de `/trades` (búsqueda, CSV, estadísticas, resúmenes y P&L) devuelven únicamente los trades del usuario autenticado.

### General

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/` | 🌐 | Mensaje de bienvenida y versión |
| GET | `/health` | 🌐 | Health check (usado por Docker) |
| GET | `/info` | 🌐 | Información de la API |

La API aplica un límite de peticiones por IP (por defecto **100 por 60 segundos**; ver [Rate limit y protección del login](#rate-limit-y-protección-del-login)) y registra cada petición mediante un middleware de logging. Los archivos estáticos se sirven desde `/static`.

### Usuarios — `/usuarios`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/usuarios/registro` | 🌐 | Registrar usuario |
| POST | `/usuarios/login` | 🌐 | Login, devuelve JWT |
| POST | `/usuarios/logout` | 🔒 | Cierra todas tus sesiones: revoca los tokens y cierra tus WebSockets |
| POST | `/usuarios/cambiar-password` | 🔒 | Exige la contraseña actual, revoca las sesiones y devuelve un token nuevo |
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
| GET | `/trades/buscar` | 🔒 | Búsqueda avanzada. Query: `activo`, `tipo`, `precio_min`, `precio_max`, `fecha_desde`, `fecha_hasta` (formato `YYYY-MM-DD`, ambas inclusive; si no es una fecha válida responde 422) |
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
| GET | `/precios/cache/stats` | 👑 | Estadísticas del caché (solo admin) |
| DELETE | `/precios/cache/clear` | 👑 | Limpiar el caché (solo admin) |

Los `coin_id` son los IDs de CoinGecko (`bitcoin`, `ethereum`, etc.). El precio individual se cachea 30 segundos.

### Análisis — `/analisis`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/analisis/pnl-en-vivo` | 🔒 | P&L por activo y total con precios actuales (caché 60 s) |
| GET | `/analisis/recomendaciones` | 🔒 | Sugerencia por activo según su P&L |
| GET | `/analisis/reporte-completo` | 🔒 | Estadísticas, P&L, mejor y peor activo |
| POST | `/analisis/watchlist` | 🔒 | Agregar moneda con precio de alerta |
| GET | `/analisis/watchlist` | 🔒 | Ver watchlist del usuario |
| DELETE | `/analisis/watchlist/{id}` | 🔒 | Quitar una moneda de tu watchlist (404 si no existe o es de otro usuario) |

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

### Paper trading — `/paper`

Operar con dinero **simulado** (USDT) a precios reales de CoinGecko. Todas las rutas son 🔒 y cada usuario solo ve y mueve lo suyo.

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/paper/orden` | 🔒 | Orden de mercado `{"coin_id", "side": "BUY"\|"SELL", "cantidad", "client_order_id"?}` |
| GET | `/paper/billetera` | 🔒 | Saldo, posiciones valoradas, equity y P&L (realizado y no realizado) |
| GET | `/paper/posiciones` | 🔒 | Posiciones abiertas con su valor actual |
| GET | `/paper/historial` | 🔒 | Órdenes ejecutadas, la más reciente primero. Query: `skip`, `limit` (máx. 100) |
| POST | `/paper/ordenes` | 🔒 | Orden pendiente `{"coin_id", "side", "tipo": "LIMIT"\|"STOP", "cantidad", "precio", "client_order_id"?}` |
| GET | `/paper/ordenes` | 🔒 | Órdenes pendientes y su resultado. Query: `estado` (`ABIERTA`, `EJECUTADA`, `CANCELADA`, `RECHAZADA`), `skip`, `limit` |
| DELETE | `/paper/ordenes/{id}` | 🔒 | Cancela una orden abierta propia |
| POST | `/paper/reiniciar` | 🔒 | Borra posiciones, órdenes pendientes e historial y devuelve el saldo inicial |

Reglas:

- Solo órdenes de **mercado**, al contado y **solo largos** (sin ventas en corto ni apalancamiento).
- **El precio lo pone el servidor**, nunca el cliente (CoinGecko, con hasta 60 s de antigüedad por la caché). Si no hay precio fiable, la orden se rechaza con 503.
- Cada ejecución paga **slippage en contra** (`PAPER_SLIPPAGE_PCT`) y **comisión** (`PAPER_COMMISSION_PCT`); el precio medio de la posición incluye las comisiones de compra,
  así que el P&L realizado cuadra exactamente con el saldo. Los redondeos nunca favorecen al usuario.
- Dinero siempre `Decimal` con 8 decimales (`NUMERIC(18,8)`); la cantidad admite como máximo 8 decimales.
- **Atomicidad:** cada orden es una transacción que bloquea la billetera del usuario (`SELECT ... FOR UPDATE`): órdenes simultáneas no pueden gastar el mismo saldo ni vender dos veces lo mismo.
- **Idempotencia:** con `client_order_id`, reintentar la misma orden devuelve la original (200, `"repetida": true`) en vez de ejecutarla otra vez; usarlo con una orden distinta da 409.
- Códigos: 201 ejecutada, 404 moneda desconocida, 409 saldo/posición insuficiente, 422 datos inválidos, 429 demasiadas órdenes, 503 sin precio.
- `valoracion_completa: false` en la billetera significa que faltó el precio de alguna moneda y el equity **no** incluye esa posición.
- **Órdenes pendientes (`/paper/ordenes`):** un motor en segundo plano revisa los precios cada `PAPER_MATCH_INTERVAL_SECONDS` (15 s) y ejecuta las órdenes que el precio dispara:
  - `LIMIT`: compra a `precio` o menos, venta a `precio` o más. Se rellena **al precio límite** (sin mejora de precio y sin slippage).
  - `STOP`: compra si el precio **sube** hasta `precio` (entrada por ruptura), venta si **baja** hasta `precio` (stop-loss). Al dispararse se ejecuta como orden de mercado, con slippage. Un STOP que ya está disparado al crearlo se rechaza (422).
  - **No reservan saldo ni posición:** se comprueban al ejecutarse; si no alcanza, la orden queda `RECHAZADA` con su `motivo` y no se reintenta.
  - Máximo `PAPER_MAX_OPEN_ORDERS` (20) abiertas por usuario. Las ejecuta el motor, así que pueden tardar hasta un intervalo más el retraso de la caché de CoinGecko (60 s); un pico de precio más corto que eso no las dispara.
  - El motor es **seguro con varios procesos**: cada orden se bloquea con `SKIP LOCKED` y se vuelve a comprobar su estado dentro del bloqueo, así que nunca se ejecuta dos veces (ni se ejecuta y cancela a la vez). `PAPER_MATCHING_ENABLED=false` lo desactiva en un proceso.
- Límites por usuario: `PAPER_ORDERS_PER_MINUTE` y `PAPER_RESETS_PER_HOUR`. Saldo inicial: `PAPER_INITIAL_BALANCE`.

### Sistema — `/system`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/system/metrics` | 👑 | Memoria, CPU y contador de peticiones |
| GET | `/system/endpoints` | 👑 | Lista de todos los endpoints registrados |

## WebSockets

| Ruta | Auth | Descripción |
|------|------|-------------|
| `/ws/precios` | 🌐 | Precios **simulados** de BTC, ETH y SOL cada 5 s |
| `/ws/precios-reales` | 🌐 | Precios reales de CoinGecko (bitcoin, ethereum, solana) cada 30 s |
| `/ws/chat?token=<jwt>` | 🔒 | Chat entre usuarios con sesión, con límite de mensajes (ver abajo) |
| `/ws/notificaciones?token=<jwt>` | 🔒 | Notificaciones personales del usuario |

### Chat

```
ws://localhost:8000/ws/chat?token=<access_token>
```

- Sin token válido el servidor rechaza la conexión antes de aceptarla (cierre `1008`; el navegador lo ve como un 403).
- Cada mensaje se reenvía como `{"tipo": "mensaje", "usuario": "ana", "mensaje": "hola"}`. El autor sale **del token**, no de lo que escriba el cliente.
- **Límite por usuario** (no por conexión): `CHAT_MAX_MESSAGES` mensajes cada `CHAT_WINDOW_SECONDS` (por defecto 10 cada 10 s). Los que sobran se descartan y el cliente
  recibe `{"tipo": "error", "mensaje": "...", "reintentar_en": N}`; la conexión sigue abierta.
- Un mensaje de más de `CHAT_MAX_LENGTH` caracteres (500) cierra la conexión con código `1009`. Los vacíos se ignoran.
- Máximo `CHAT_MAX_CONNECTIONS_PER_USER` conexiones simultáneas por usuario (3), sumando todos los procesos si hay `REDIS_URL`.
- El token solo se comprueba al conectar: si caduca con el chat abierto, la conexión sigue hasta que se cierre.
- Los mensajes **no se guardan**: solo los reciben quienes están conectados en ese momento.
- El token viaja en la URL, así que el servidor **tapa `token=...` en los logs de uvicorn** (`OcultarTokenEnLogs`). Cuida que un proxy o CDN delante tampoco registre
  la URL completa de los WebSockets.

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

Las alertas de precio y P&L se revisan en background cada 60 segundos, solo para usuarios con una conexión activa. Una misma alerta (usuario, tipo y moneda/activo) se envía como mucho
una vez cada `ALERT_COOLDOWN_SECONDS` (por defecto 3600): antes, mientras la condición se cumplía, el aviso se repetía cada minuto. Con Redis el cooldown es global.

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
El esquema de los tests se crea con `alembic upgrade head`, es decir, con las mismas migraciones que producción.
Los tests de riesgo y backtesting usan series sintéticas con resultados calculados a mano; no necesitan red.

Los tests del rate limit prueban el almacén Redis con `fakeredis` y, **si defines `TEST_REDIS_URL`**, también contra un Redis real
(`export TEST_REDIS_URL=redis://localhost:6379/15`; sin ella esos casos se omiten). Usa una instancia o base de **pruebas**: esos tests borran las claves `trading-api:rl:*`.

Además de las variables de la sección [Configuración](#configuración) (`SECRET_KEY`, `ALGORITHM`, etc.), no se necesita
conexión a Binance ni a CoinGecko para correr la suite.

## Deploy

La API se puede desplegar en plataformas como Render o Railway usando el `Dockerfile` del proyecto.

- **URL de producción Render:** `https://trading-api-o9u2.onrender.com/`
- **URL de producción Railway:** `https://trading-api-production-4205.up.railway.app/`
- **Migraciones:** el contenedor ejecuta `alembic upgrade head` antes de iniciar `uvicorn`, así que cada despliegue deja el esquema al día. Si la migración falla, el despliegue falla en vez de servir tráfico con un esquema incorrecto. Antes del primer despliegue con esta versión conviene hacer un backup (en Neon, una *branch* de la base).
- **Puerto y workers:** el contenedor escucha en `$PORT` (lo define la plataforma; en local, 8000) y arranca `WEB_CONCURRENCY` procesos (por defecto **1**).
  Para usar más hace falta `REDIS_URL` (si no, la app **se niega a arrancar**): con Redis el chat, las notificaciones y el vaciado del caché llegan a las conexiones de todos los procesos
  e instancias (ver [Varios procesos](#varios-procesos-o-instancias)).
- **No hay `Procfile`:** la plataforma debe usar el `Dockerfile`. Un `Procfile` arrancaría uvicorn sin migrar y con las opciones por defecto.
- **Primer administrador:** tras el primer despliegue, regístrate y promuévete desde una shell de la instancia: `python scripts/gestionar_roles.py promover <usuario>` (ver [Roles](#roles-administradores)).
- **Integración continua:** `.github/workflows/tests.yml` corre toda la suite (PostgreSQL y Redis reales, Python 3.12) y construye la imagen en cada PR y en cada push a `main`. Conviene activar en GitHub *Settings → Branches* la regla de exigir que pase antes de fusionar.
- **Variables de entorno:** el `.env` no se sube al repositorio, así que hay que cargar las variables desde el panel de la plataforma (las mismas de la sección [Configuración](#configuración)). En producción:
  - `ENVIRONMENT=production` (deshabilita `/docs`, `/redoc` y `/openapi.json`)
  - `DATABASE_URL` con la connection string de tu base en [Neon](https://neon.tech) (PostgreSQL administrado). Debe incluir `?sslmode=require`. Si falta esta variable o apunta a `localhost` (la base local de Docker), la app no arranca
  - `SECRET_KEY` distinta a la de desarrollo
  - `CORS_ORIGINS` con la URL de tu frontend
  - `TRUSTED_PROXY_COUNT` con el número de proxies delante de la app (si lo dejas en `0`, todos los usuarios compartirán un solo cupo de rate limit)
  - `REDIS_URL` solo si ejecutas más de una instancia o `WEB_CONCURRENCY` mayor que 1
  - `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` y `BINANCE_TESTNET=true` (dinero real exige además `BINANCE_ALLOW_LIVE=true`)
- **Región:** Binance bloquea conexiones desde ciertas regiones (por ejemplo, servidores en EE. UU.). Si el arranque falla con el error `Service unavailable from a restricted location`, elige una región de Europa o Asia para el servicio. Probado: Railway en Países Bajos y Render en Frankfurt. En Render la región no se puede cambiar en un servicio existente: hay que crear uno nuevo.

## Notas

- La información de precios proviene de CoinGecko y puede estar sujeta a límites de uso (rate limits); por eso se usa caché.
- Este proyecto es educativo y no constituye asesoría financiera.