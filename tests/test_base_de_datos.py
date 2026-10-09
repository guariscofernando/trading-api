# tests/test_base_de_datos.py
"""Capa de datos con SQLAlchemy: pool de conexiones, transacciones, DAOs y configuración."""
import threading
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from app.config import Config
from app.dao.OrderDAO import OrderDAO
from app.dao.TradeDAO import TradeDAO, _a_datetime
from app.dao.UserDAO import UserDAO
from app.dao.WatchlistDAO import WatchlistDAO
from app.database import engine, normalizar_url, session_scope
from app.models import Usuario


@pytest.fixture
def conexiones_nuevas():
    """Cuenta las conexiones REALES que se abren hacia PostgreSQL (las del pool no cuentan)."""
    contador = {"n": 0}

    def al_conectar(*_):
        contador["n"] += 1

    engine.dispose()                      # pool vacío: parte de cero
    event.listen(engine, "connect", al_conectar)
    yield contador
    event.remove(engine, "connect", al_conectar)


@pytest.fixture
def usuario(db_limpia):
    uid = UserDAO().crear_usuario_db("ana", "ana@example.com", "hash")
    assert uid is not None
    return uid


def _trade(uid, **cambios):
    datos = dict(usuario_id=uid, tipo="compra", activo="BTC", precio=100.0, cantidad=1.0, fecha="2026-01-15 10:30")
    datos.update(cambios)
    return TradeDAO().crear_trade_db(**datos)


# ------------------------------------------------------------------------ pool

def test_el_pool_reutiliza_la_conexion_en_lugar_de_abrir_una_por_consulta(usuario, conexiones_nuevas):
    """Antes cada llamada a un DAO hacía psycopg2.connect: 100 consultas = 100 conexiones."""
    dao = UserDAO()
    for _ in range(100):
        assert dao.obtener_usuario_por_id(usuario)["username"] == "ana"
    assert conexiones_nuevas["n"] <= 2
    assert engine.pool.checkedout() == 0


def test_el_pool_aguanta_concurrencia_sin_superar_su_limite(usuario, conexiones_nuevas):
    errores, dao = [], UserDAO()

    def trabajar():
        try:
            for _ in range(10):
                assert dao.obtener_usuario_por_id(usuario) is not None
        except Exception as e:  # pragma: no cover
            errores.append(e)

    hilos = [threading.Thread(target=trabajar) for _ in range(40)]
    [h.start() for h in hilos]
    [h.join(timeout=30) for h in hilos]

    assert errores == []
    assert conexiones_nuevas["n"] <= engine.pool.size() + engine.pool._max_overflow
    assert engine.pool.checkedout() == 0          # ninguna conexión quedó "colgada"


def test_una_excepcion_devuelve_la_conexion_al_pool(usuario):
    antes = engine.pool.checkedout()
    for _ in range(25):                           # más intentos que conexiones del pool
        assert UserDAO().crear_usuario_db("ana", "otro@example.com", "h") is None
    assert engine.pool.checkedout() == antes
    assert UserDAO().obtener_usuario_por_id(usuario) is not None


# ------------------------------------------------------------ transacciones

def test_session_scope_revierte_todo_si_hay_un_error(db_limpia):
    with pytest.raises(RuntimeError):
        with session_scope() as sesion:
            sesion.add(Usuario(username="fantasma", email="f@example.com", password_hash="h"))
            sesion.flush()
            raise RuntimeError("fallo a mitad de la transacción")
    assert UserDAO().obtener_usuario_por_username("fantasma") is None


def test_session_scope_confirma_si_todo_va_bien(db_limpia):
    with session_scope() as sesion:
        sesion.add(Usuario(username="real", email="r@example.com", password_hash="h"))
    assert UserDAO().obtener_usuario_por_username("real") is not None


# --------------------------------------------------------------------- usuarios

def test_usuario_duplicado_devuelve_none_por_username_y_por_email(usuario):
    dao = UserDAO()
    assert dao.crear_usuario_db("ana", "nueva@example.com", "h") is None
    assert dao.crear_usuario_db("nueva", "ana@example.com", "h") is None
    assert dao.crear_usuario_db("nueva", "nueva@example.com", "h") is not None


def test_usuario_se_devuelve_como_dict_con_las_mismas_claves_de_antes(usuario):
    u = UserDAO().obtener_usuario_por_id(usuario)
    assert set(u) == {"id", "username", "email", "password_hash", "creado_en"}
    assert isinstance(u["creado_en"], datetime)
    assert UserDAO().obtener_usuario_por_id(999999) is None
    assert UserDAO().obtener_usuario_por_email("ana@example.com")["id"] == usuario


def test_borrar_un_usuario_borra_sus_datos_on_delete_cascade(usuario):
    _trade(usuario)
    WatchlistDAO().agregar_db(usuario, "bitcoin", 1)
    with engine.begin() as c:
        c.execute(text("DELETE FROM usuarios WHERE id = :i"), {"i": usuario})
    assert TradeDAO().obtener_trades_db(usuario_id=usuario) == []
    assert WatchlistDAO().obtener_por_usuario_db(usuario) == []


# ----------------------------------------------------------------------- trades

def test_trades_devuelve_floats_y_datetime_como_antes(usuario):
    _trade(usuario, precio=50000.12345678, cantidad=0.5)
    (t,) = TradeDAO().obtener_trades_db(usuario_id=usuario)
    assert isinstance(t["precio"], float) and t["precio"] == 50000.12345678
    assert isinstance(t["cantidad"], float)
    assert t["fecha"] == datetime(2026, 1, 15, 10, 30)


def test_trades_filtros_y_orden(usuario):
    _trade(usuario, activo="BTC", fecha="2026-01-01 10:00")
    _trade(usuario, activo="ETH", tipo="venta", fecha="2026-01-03 10:00")
    _trade(usuario, activo="BTC", fecha="2026-01-02 10:00")
    dao = TradeDAO()
    assert [t["fecha"].day for t in dao.obtener_trades_db(usuario_id=usuario, limit=10)] == [3, 2, 1]
    assert len(dao.obtener_trades_db(usuario_id=usuario, activo="btc")) == 2     # insensible a mayúsculas
    assert len(dao.obtener_trades_db(usuario_id=usuario, tipo="venta")) == 1
    assert len(dao.obtener_trades_db(usuario_id=usuario, skip=1, limit=1)) == 1


def test_trades_paginado_y_orden_invalido_cae_en_fecha(usuario):
    for i in range(5):
        _trade(usuario, precio=10.0 + i, fecha=f"2026-01-0{i + 1} 10:00")
    dao = TradeDAO()
    pagina, total = dao.obtener_trades_paginado_db(usuario, page=2, per_page=2, orden="precio", direccion="asc")
    assert total == 5 and [t["precio"] for t in pagina] == [12.0, 13.0]
    pagina, _ = dao.obtener_trades_paginado_db(usuario, orden="no_existe; DROP TABLE trades", direccion="desc")
    assert pagina[0]["fecha"].day == 5


def test_fechas_aceptan_texto_date_y_datetime():
    assert _a_datetime("2026-01-15 10:30") == datetime(2026, 1, 15, 10, 30)
    assert _a_datetime("2026-01-15") == datetime(2026, 1, 15, 0, 0)
    assert _a_datetime(date(2026, 1, 15), fin_de_dia=True).hour == 23
    assert _a_datetime(datetime(2026, 1, 15, 8, 5)) == datetime(2026, 1, 15, 8, 5)
    for malo in ("ayer", "2026-13-45", ""):
        with pytest.raises(ValueError):
            _a_datetime(malo)


def test_rango_de_fechas_incluye_todo_el_dia_final(usuario):
    _trade(usuario, fecha="2026-01-31 23:59")
    dao = TradeDAO()
    assert len(dao.trades_por_fecha_db("2026-01-01", "2026-01-31", usuario_id=usuario)) == 1
    assert len(dao.trades_por_fecha_db("2026-01-01", "2026-01-30", usuario_id=usuario)) == 0
    assert len(dao.buscar_trades_db(usuario, fecha_desde=date(2026, 1, 31), fecha_hasta=date(2026, 1, 31))) == 1


def test_buscar_combina_filtros_y_aisla_usuarios(usuario):
    otro = UserDAO().crear_usuario_db("beto", "beto@example.com", "h")
    _trade(usuario, activo="BTC", precio=100.0)
    _trade(usuario, activo="BTC", precio=900.0)
    _trade(otro, activo="BTC", precio=500.0)
    dao = TradeDAO()
    assert len(dao.buscar_trades_db(usuario)) == 2                                   # no ve los de beto
    assert [t["precio"] for t in dao.buscar_trades_db(usuario, precio_min=200)] == [900.0]
    assert [t["precio"] for t in dao.buscar_trades_db(usuario, precio_max=200)] == [100.0]


def test_actualizar_y_eliminar_informan_si_algo_cambio(usuario):
    tid = _trade(usuario)
    dao = TradeDAO()
    assert dao.actualizar_trade_db(tid, precio=250.0, activo="ETH") is True
    assert dao.obtener_trade_db(tid)["precio"] == 250.0 and dao.obtener_trade_db(tid)["activo"] == "ETH"
    assert dao.actualizar_trade_db(tid) is False                       # nada que actualizar
    assert dao.actualizar_trade_db(tid, precio=None) is False
    assert dao.actualizar_trade_db(999999, precio=1.0) is False        # no existe
    assert dao.eliminar_trade_db(tid) is True
    assert dao.eliminar_trade_db(tid) is False
    assert dao.obtener_trade_db(tid) is None


def test_actualizar_rechaza_campos_que_no_son_editables(usuario):
    """El método construía el UPDATE con los nombres de campo recibidos: ahora hay lista blanca."""
    tid = _trade(usuario)
    for campo in ("usuario_id", "id", "fecha", "precio = 1; DROP TABLE trades; --"):
        with pytest.raises(ValueError):
            TradeDAO().actualizar_trade_db(tid, **{campo: 1})
    assert TradeDAO().obtener_trade_db(tid)["usuario_id"] == usuario


def test_la_base_rechaza_datos_invalidos_por_los_check(usuario):
    from sqlalchemy.exc import IntegrityError
    for malo in (dict(tipo="regalo"), dict(precio=0), dict(cantidad=-1)):
        with pytest.raises(IntegrityError):
            _trade(usuario, **malo)


@pytest.mark.parametrize("ataque", ["BTC'; DROP TABLE trades; --", "' OR '1'='1", "BTC%' --"])
def test_los_parametros_viajan_enlazados_no_hay_inyeccion_sql(usuario, ataque):
    _trade(usuario)
    dao = TradeDAO()
    assert dao.obtener_trades_db(usuario_id=usuario, activo=ataque) == []
    assert dao.buscar_trades_db(usuario, activo=ataque, tipo=ataque) == []
    assert UserDAO().obtener_usuario_por_username(ataque) is None
    assert len(dao.obtener_trades_db(usuario_id=usuario)) == 1          # la tabla sigue ahí


def test_trades_con_usuario_incluye_username_y_email(usuario):
    _trade(usuario)
    (t,) = TradeDAO().obtener_trades_con_usuario_db(usuario_id=usuario)
    assert t["username"] == "ana" and t["email"] == "ana@example.com" and isinstance(t["precio"], float)


# -------------------------------------------------------------------- watchlist

def test_watchlist_guarda_ids_largos_y_devuelve_decimal(usuario):
    dao = WatchlistDAO()
    for coin in ("bitcoin", "binancecoin", "wrapped-bitcoin", "x" * 64):
        dao.agregar_db(usuario, coin, 123.45)
    items = dao.obtener_por_usuario_db(usuario)
    assert len(items) == 4 and {"bitcoin", "binancecoin", "wrapped-bitcoin", "x" * 64} == {i["coin_id"] for i in items}
    assert items[0]["id"] > items[-1]["id"]                              # más recientes primero
    assert isinstance(items[0]["precio_alerta"], Decimal) and items[0]["precio_alerta"] == Decimal("123.45")


# ----------------------------------------------------------------------- orders

def test_ordenes_crear_filtrar_y_actualizar(usuario):
    dao = OrderDAO()
    oid = dao.crear_order_db(usuario, 123456789012, "BTCUSDT", "BUY", "LIMIT", "NEW", 0.001, price=60000)
    dao.crear_order_db(usuario, 2, "ETHUSDT", "SELL", "MARKET", "FILLED", 1)

    (orden,) = dao.obtener_orders_db(usuario_id=usuario, symbol="BTCUSDT")
    assert orden["id"] == oid and orden["binance_order_id"] == 123456789012      # BIGINT íntegro
    assert orden["status"] == "NEW" and orden["executed_qty"] == 0
    assert isinstance(orden["quantity"], Decimal) and isinstance(orden["created_at"], datetime)
    assert len(dao.obtener_orders_db(usuario_id=usuario, status="FILLED")) == 1
    assert len(dao.obtener_orders_db(usuario_id=usuario)) == 2

    assert dao.actualizar_order_status_db(123456789012, "FILLED", "0.00100000") is True   # Binance envía texto
    despues = dao.obtener_orders_db(usuario_id=usuario, symbol="BTCUSDT")[0]
    assert despues["status"] == "FILLED" and despues["executed_qty"] == Decimal("0.001")
    assert despues["updated_at"] >= despues["created_at"]
    assert dao.actualizar_order_status_db(111, "FILLED") is False                          # no existe


def test_ordenes_rechazan_valores_fuera_de_los_check(usuario):
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        OrderDAO().crear_order_db(usuario, 1, "BTCUSDT", "HOLD", "LIMIT", "NEW", 1)


# ---------------------------------------------------------- API y configuración

def test_buscar_y_por_fecha_validan_las_fechas_con_422(client, auth_headers):
    for ruta in ("/trades/buscar?fecha_hasta=2026-99-99", "/trades/resumen/por-fecha?desde=ayer"):
        assert client.get(ruta, headers=auth_headers).status_code == 422
    assert client.get("/trades/resumen/por-fecha?desde=2026-01-01", headers=auth_headers).status_code == 200


def test_normalizar_url_acepta_el_esquema_postgres_de_algunos_proveedores():
    assert normalizar_url("postgres://u:p@h/db?sslmode=require") == "postgresql://u:p@h/db?sslmode=require"
    assert normalizar_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def _config_valida(**cambios):
    cfg = Config()
    cfg.ENVIRONMENT = "development"
    cfg.SECRET_KEY, cfg.ALGORITHM = "una-clave-de-prueba-suficientemente-larga-123456", "HS256"
    cfg.DATABASE_URL, cfg.APP_NAME, cfg.APP_VERSION, cfg.APP_DESCRIPTION = "postgresql://u:p@h/x_test", "T", "1", "t"
    cfg.CORS_ORIGINS = ["http://localhost:3000"]
    for k, v in cambios.items():
        setattr(cfg, k, v)
    return cfg


def test_configuracion_del_pool_se_valida():
    _config_valida().validate()
    for campo, valor in (("DB_POOL_SIZE", 0), ("DB_POOL_TIMEOUT", 0), ("DB_POOL_RECYCLE", -5), ("DB_MAX_OVERFLOW", -1)):
        with pytest.raises(RuntimeError, match=campo):
            _config_valida(**{campo: valor}).validate()


def test_variable_de_pool_no_numerica_falla_con_mensaje_claro(monkeypatch):
    from app.config import _entero
    monkeypatch.setenv("DB_POOL_SIZE", "muchas")
    with pytest.raises(RuntimeError, match="DB_POOL_SIZE"):
        _entero("DB_POOL_SIZE", 5)
