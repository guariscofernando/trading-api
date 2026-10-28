# tests/test_despliegue.py
"""Guardas sobre los archivos de despliegue: errores aquí solo se notan en producción."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _dockerfile():
    return (RAIZ / "Dockerfile").read_text()


def _cmd():
    return re.search(r"^CMD (.+)$", _dockerfile(), re.M).group(1)


def test_el_contenedor_migra_antes_de_arrancar():
    cmd = _cmd()
    assert cmd.index("alembic upgrade head") < cmd.index("uvicorn")
    assert "&&" in cmd                      # si la migración falla, no se sirve tráfico


def test_uvicorn_no_confia_en_cabeceras_de_proxy_y_usa_un_solo_worker():
    cmd = _cmd()
    assert "--no-proxy-headers" in cmd and "--workers 1" in cmd


def test_el_puerto_sale_de_la_plataforma_y_el_healthcheck_lo_sigue():
    assert "${PORT:-8000}" in _cmd()
    assert "PORT" in re.search(r"^HEALTHCHECK.*\n\s+CMD (.+)$", _dockerfile(), re.M).group(1)


def test_no_quedan_procfiles_que_se_salten_las_migraciones():
    assert list(RAIZ.rglob("Procfile")) == []


def test_la_base_de_docker_compose_solo_escucha_en_localhost():
    compose = (RAIZ / "docker-compose.yml").read_text()
    assert '"5432:5432"' not in compose and "127.0.0.1:5432:5432" in compose


def test_dockerignore_excluye_los_secretos():
    lineas = (RAIZ / ".dockerignore").read_text().split()
    assert ".env" in lineas and ".git/" in lineas


def test_el_script_de_roles_viaja_en_la_imagen():
    assert "scripts/" not in (RAIZ / ".dockerignore").read_text()
