# alembic/env.py
"""
Entorno de Alembic. Usa la misma DATABASE_URL que la aplicación (app/config.py).

- Conexión sin pool (NullPool): las migraciones abren y cierran la suya.
- Bloqueo de PostgreSQL (advisory lock): si varias instancias arrancan a la vez (despliegue
  con réplicas), solo una migra y las demás esperan y luego ven el esquema ya actualizado.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import config as app_config
from app.database import MIGRACIONES_LOCK_ID, Base, normalizar_url
import app.models  # noqa: F401  (registra los modelos en Base.metadata)

config = context.config

# Desde la línea de comandos se configura el log; desde pytest/código se conserva el de la aplicación.
if config.config_file_name is not None and not config.attributes.get("conservar_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
URL = normalizar_url(app_config.DATABASE_URL)


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (alembic upgrade head --sql)."""
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    motor = create_engine(URL, poolclass=NullPool)
    # El candado vive en su propia conexión mientras la migración corre en otra.
    with motor.connect() as conexion_candado:
        conexion_candado.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRACIONES_LOCK_ID})
        try:
            with motor.connect() as conexion:
                context.configure(connection=conexion, target_metadata=target_metadata, compare_type=True)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            conexion_candado.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRACIONES_LOCK_ID})
            conexion_candado.commit()
    motor.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
