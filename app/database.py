# app/database.py
"""
Acceso a PostgreSQL con SQLAlchemy 2.0 (síncrono).

- Un único `engine` por proceso con un POOL de conexiones: ya no se abre una conexión
  nueva (TCP + TLS) en cada consulta.
- `pool_pre_ping` descarta conexiones muertas antes de usarlas (Neon escala a cero y
  corta las inactivas) y `pool_recycle` las renueva periódicamente.
- `session_scope()` = una transacción: confirma al salir bien y revierte ante cualquier error.
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import config


# Identifica el bloqueo de PostgreSQL (advisory lock) que serializa las migraciones entre instancias.
MIGRACIONES_LOCK_ID = 727_274_001


def normalizar_url(url: str) -> str:
    """Algunos proveedores entregan 'postgres://', esquema que SQLAlchemy ya no acepta."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


class Base(DeclarativeBase):
    """Base de los modelos (app/models.py). Alembic usa su `metadata`."""


# create_engine es perezoso: no abre ninguna conexión al importar el módulo.
engine = create_engine(
    normalizar_url(config.DATABASE_URL),
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_timeout=config.DB_POOL_TIMEOUT,
    pool_recycle=config.DB_POOL_RECYCLE,
    pool_pre_ping=True,
)

# expire_on_commit=False: los DAOs devuelven diccionarios ya construidos, no objetos ligados a la sesión.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión transaccional: commit si todo va bien, rollback si hay una excepción, siempre close."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
