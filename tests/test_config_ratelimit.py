# tests/test_config_ratelimit.py
"""Configuración del rate limit: validación al arrancar y avisos de producción."""
import pytest

from app.config import Config, _entero


def _cfg(**cambios):
    cfg = Config()
    cfg.ENVIRONMENT = "development"
    cfg.SECRET_KEY = "una-clave-de-prueba-suficientemente-larga-123456"
    cfg.ALGORITHM = "HS256"
    cfg.DATABASE_URL, cfg.APP_NAME, cfg.APP_VERSION, cfg.APP_DESCRIPTION = "postgresql://u:p@h/x_test", "T", "1", "t"
    cfg.CORS_ORIGINS = ["https://mi-frontend.example.com"]
    for campo, valor in cambios.items():
        setattr(cfg, campo, valor)
    return cfg


def test_valores_por_defecto():
    cfg = _cfg()
    cfg.validate()
    assert (cfg.RATE_LIMIT_REQUESTS, cfg.RATE_LIMIT_WINDOW) == (100, 60)
    assert (cfg.LOGIN_RATE_LIMIT, cfg.REGISTER_RATE_LIMIT) == (20, 10)
    assert (cfg.LOGIN_MAX_FAILURES, cfg.LOGIN_LOCKOUT_SECONDS) == (5, 900)
    assert cfg.TRUSTED_PROXY_COUNT == 0 and cfg.REDIS_URL == ""


@pytest.mark.parametrize("campo", ["RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW", "LOGIN_RATE_LIMIT",
                                   "REGISTER_RATE_LIMIT", "LOGIN_MAX_FAILURES", "LOGIN_LOCKOUT_SECONDS"])
@pytest.mark.parametrize("valor", [0, -1])
def test_limites_menores_que_uno_se_rechazan_con_el_nombre_de_la_variable(campo, valor):
    with pytest.raises(RuntimeError, match=campo):
        _cfg(**{campo: valor}).validate()


@pytest.mark.parametrize("valor", [-1, 11])
def test_proxies_de_confianza_fuera_de_rango(valor):
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_COUNT"):
        _cfg(TRUSTED_PROXY_COUNT=valor).validate()


@pytest.mark.parametrize("url", ["redis://localhost:6379/0", "rediss://usuario:clave@host:6380/1", "unix:///tmp/redis.sock"])
def test_urls_de_redis_validas(url):
    _cfg(REDIS_URL=url).validate()


@pytest.mark.parametrize("url", ["localhost:6379", "http://localhost", "mysql://x"])
def test_url_de_redis_invalida_falla_al_arrancar(url):
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        _cfg(REDIS_URL=url).validate()


def test_variable_no_numerica_dice_cual_es(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "uno")
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_COUNT"):
        _entero("TRUSTED_PROXY_COUNT", 0)


def test_en_desarrollo_no_hay_avisos():
    assert _cfg().avisos_produccion() == []


def test_en_produccion_avisa_de_proxies_y_de_redis():
    avisos = _cfg(ENVIRONMENT="production").avisos_produccion()
    assert len(avisos) == 2
    assert any("TRUSTED_PROXY_COUNT" in a for a in avisos) and any("REDIS_URL" in a for a in avisos)


def test_en_produccion_bien_configurada_no_avisa():
    cfg = _cfg(ENVIRONMENT="production", TRUSTED_PROXY_COUNT=1, REDIS_URL="rediss://h:6380")
    assert cfg.avisos_produccion() == []


# ----------------------------------------------------------------- arranque de uvicorn

def _comandos_uvicorn():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    for archivo in ("Dockerfile", "app/Procfile"):
        for linea in (raiz / archivo).read_text(encoding="utf-8").splitlines():
            if "uvicorn app.main:app" in linea and not linea.lstrip().startswith("#"):
                yield archivo, linea


def test_uvicorn_se_arranca_sin_reescribir_la_ip_del_cliente():
    """
    Con FORWARDED_ALLOW_IPS='*' uvicorn sustituye la IP del cliente por la entrada MÁS A LA IZQUIERDA de
    X-Forwarded-For (la escribe el cliente) y el rate limit se evade cambiando una cabecera. Con
    --no-proxy-headers la única IP válida es la que calcula la aplicación (TRUSTED_PROXY_COUNT).
    """
    comandos = list(_comandos_uvicorn())
    assert {a for a, _ in comandos} == {"Dockerfile"}, "no se encontró el comando de arranque (o reapareció un Procfile)"
    for archivo, linea in comandos:
        assert "--no-proxy-headers" in linea, f"{archivo} no usa --no-proxy-headers: {linea}"


# ------------------------------------------------------------------ paper trading

def test_valores_por_defecto_de_paper_trading():
    from decimal import Decimal as D
    cfg = _cfg()
    cfg.validate()
    assert (cfg.PAPER_INITIAL_BALANCE, cfg.PAPER_COMMISSION_PCT, cfg.PAPER_SLIPPAGE_PCT) == (D(10000), D("0.1"), D("0.05"))
    assert (cfg.PAPER_ORDERS_PER_MINUTE, cfg.PAPER_RESETS_PER_HOUR) == (30, 3)


@pytest.mark.parametrize("campo,valor", [
    ("PAPER_INITIAL_BALANCE", 0), ("PAPER_INITIAL_BALANCE", 10**11),
    ("PAPER_COMMISSION_PCT", -1), ("PAPER_COMMISSION_PCT", 10), ("PAPER_SLIPPAGE_PCT", 10),
    ("PAPER_ORDERS_PER_MINUTE", 0), ("PAPER_RESETS_PER_HOUR", 0),
])
def test_config_de_paper_trading_invalida_impide_arrancar(campo, valor):
    from decimal import Decimal as D
    valor = D(valor) if campo.startswith(("PAPER_INITIAL", "PAPER_COMM", "PAPER_SLIP")) else valor
    with pytest.raises(RuntimeError, match=campo):
        _cfg(**{campo: valor}).validate()


@pytest.mark.parametrize("nombre,valor", [("PAPER_INITIAL_BALANCE", "abc"), ("PAPER_SLIPPAGE_PCT", "NaN"),
                                          ("PAPER_COMMISSION_PCT", "Infinity")])
def test_decimales_no_numericos_o_no_finitos_se_rechazan_al_leerlos(monkeypatch, nombre, valor):
    from app.config import _decimal
    monkeypatch.setenv(nombre, valor)
    with pytest.raises(RuntimeError, match=nombre):
        _decimal(nombre, "1")
