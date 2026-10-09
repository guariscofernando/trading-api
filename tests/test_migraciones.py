# tests/test_migraciones.py
"""
Migraciones de Alembic. Estos tests reconstruyen el esquema de la base de pruebas, así que
cada uno la deja de nuevo en `head` al terminar (fixture `restaurar_esquema`).
"""
import threading

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.database import MIGRACIONES_LOCK_ID, Base, engine
from tests.conftest import alembic_config

# Esquema tal y como lo creaba el código anterior al ORM (create_trading.init_db): es lo que
# hoy existe en producción. Se conserva aquí para probar que la migración lo adopta sin perder datos.
ESQUEMA_ANTERIOR = """
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    username VARCHAR(20) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo VARCHAR(10) NOT NULL CHECK(tipo IN ('compra', 'venta')),
    activo VARCHAR(10) NOT NULL,
    precio NUMERIC(18, 8) NOT NULL CHECK(precio > 0),
    cantidad NUMERIC(18, 8) NOT NULL CHECK(cantidad > 0),
    fecha TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    coin_id VARCHAR(10) NOT NULL,
    precio_alerta NUMERIC(18, 8) NOT NULL CHECK(precio_alerta > 0),
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    binance_order_id BIGINT,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK(side IN ('BUY', 'SELL')),
    order_type VARCHAR(20) NOT NULL CHECK(order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS')),
    status VARCHAR(30) NOT NULL DEFAULT 'NEW',
    quantity NUMERIC(18, 8) NOT NULL,
    price NUMERIC(18, 8),
    stop_price NUMERIC(18, 8),
    executed_qty NUMERIC(18, 8) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trades_usuario_id ON trades(usuario_id);
CREATE INDEX IF NOT EXISTS idx_trades_activo ON trades(activo);
CREATE INDEX IF NOT EXISTS idx_trades_fecha ON trades(fecha);
CREATE INDEX IF NOT EXISTS idx_orders_usuario ON orders(usuario_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
"""

DATOS_DE_PRODUCCION = """
INSERT INTO usuarios (username, email, password_hash) VALUES ('ana','ana@x.com','h1'),('beto','beto@x.com','h2');
INSERT INTO trades (usuario_id,tipo,activo,precio,cantidad,fecha)
    VALUES (1,'compra','BTC',50000.12345678,0.5,'2026-01-15 10:30'),(2,'venta','ETH',3000,2,'2026-02-01 09:00');
INSERT INTO watchlist (usuario_id,coin_id,precio_alerta) VALUES (1,'bitcoin',70000);
INSERT INTO orders (usuario_id,binance_order_id,symbol,side,order_type,status,quantity,price)
    VALUES (1,123456789012,'BTCUSDT','BUY','LIMIT','NEW',0.001,60000);
"""


def _borrar_todo():
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS orders, watchlist, trades, usuarios, alembic_version CASCADE"))


def _huella_de_datos():
    with engine.connect() as c:
        return c.execute(text(
            "SELECT md5((SELECT string_agg(u::text,'|' ORDER BY id) FROM usuarios u)"
            "||(SELECT string_agg(t::text,'|' ORDER BY id) FROM trades t)"
            "||(SELECT string_agg(o::text,'|' ORDER BY id) FROM orders o))"
        )).scalar_one()


def _version():
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _largo_coin_id():
    columnas = {c["name"]: c for c in inspect(engine).get_columns("watchlist")}
    return columnas["coin_id"]["type"].length


@pytest.fixture
def restaurar_esquema():
    yield
    _borrar_todo()
    command.upgrade(alembic_config(), "head")


# ------------------------------------------------------------------ esquema

def test_el_esquema_migrado_coincide_con_los_modelos():
    """Si alguien cambia app/models.py sin crear su migración, este test falla."""
    with engine.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion, opts={"compare_type": True}),
                                       Base.metadata)
    assert diferencias == [], f"Los modelos y las migraciones difieren: {diferencias}"


def test_la_base_queda_en_la_ultima_version():
    assert _version() == "0002"
    assert _largo_coin_id() == 64


# --------------------------------------------- adopción de una base existente

def test_base_existente_con_datos_se_migra_sin_perder_nada(restaurar_esquema):
    _borrar_todo()
    with engine.begin() as c:
        c.execute(text(ESQUEMA_ANTERIOR))
        c.execute(text(DATOS_DE_PRODUCCION))
    antes = _huella_de_datos()

    command.upgrade(alembic_config(), "head")

    assert _huella_de_datos() == antes, "la migración modificó datos existentes"
    assert _version() == "0002"
    assert _largo_coin_id() == 64
    with engine.connect() as c:
        assert c.execute(text("SELECT coin_id FROM watchlist")).scalar_one() == "bitcoin"
        assert c.execute(text("SELECT count(*) FROM trades")).scalar_one() == 2
    # y además el esquema resultante es el mismo que el de una base nueva
    with engine.connect() as conexion:
        assert compare_metadata(MigrationContext.configure(conexion, opts={"compare_type": True}),
                                Base.metadata) == []


def test_ejecutar_dos_veces_no_hace_nada(restaurar_esquema):
    command.upgrade(alembic_config(), "head")
    command.upgrade(alembic_config(), "head")
    assert _version() == "0002"


def test_base_vacia_se_crea_completa(restaurar_esquema):
    _borrar_todo()
    command.upgrade(alembic_config(), "head")
    tablas = set(inspect(engine).get_table_names())
    assert {"usuarios", "trades", "watchlist", "orders", "alembic_version"} <= tablas
    indices = {i["name"] for t in ("trades", "orders") for i in inspect(engine).get_indexes(t)}
    assert {"idx_trades_usuario_id", "idx_trades_activo", "idx_trades_fecha",
            "idx_orders_usuario", "idx_orders_symbol", "idx_orders_status"} <= indices


# ---------------------------------------------------------------- downgrade

def test_downgrade_de_0002_funciona_si_no_hay_ids_largos(restaurar_esquema):
    command.downgrade(alembic_config(), "0001")
    assert _version() == "0001" and _largo_coin_id() == 10


def test_downgrade_de_0002_falla_en_voz_alta_si_hay_ids_largos_y_no_trunca(restaurar_esquema):
    with engine.begin() as c:
        c.execute(text("INSERT INTO usuarios (username,email,password_hash) VALUES ('u','u@x.com','h')"))
        c.execute(text("INSERT INTO watchlist (usuario_id,coin_id,precio_alerta) VALUES (1,'wrapped-bitcoin',1)"))
    with pytest.raises(DBAPIError):
        command.downgrade(alembic_config(), "0001")
    with engine.connect() as c:                    # el dato largo sigue intacto
        assert c.execute(text("SELECT coin_id FROM watchlist")).scalar_one() == "wrapped-bitcoin"
    assert _largo_coin_id() == 64


# ------------------------------------------------------------ bloqueo entre instancias

def test_las_migraciones_esperan_si_otra_instancia_esta_migrando():
    """Con el candado tomado por otra conexión, `upgrade` debe quedarse esperando hasta que se libere."""
    terminado = threading.Event()
    errores = []

    def migrar():
        try:
            command.upgrade(alembic_config(), "head")
        except Exception as e:  # pragma: no cover
            errores.append(e)
        finally:
            terminado.set()

    with engine.connect() as otra_instancia:
        otra_instancia.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRACIONES_LOCK_ID})
        hilo = threading.Thread(target=migrar, daemon=True)
        hilo.start()
        assert not terminado.wait(timeout=1.5), "la migración no respetó el candado"
        otra_instancia.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRACIONES_LOCK_ID})
        otra_instancia.commit()

    assert terminado.wait(timeout=15), "la migración no continuó tras liberar el candado"
    hilo.join(timeout=5)
    assert errores == []
