"""Añade usuarios.token_version (revocación de sesiones)

Cada token lleva la versión del usuario al emitirse; al cerrar sesión o cambiar la contraseña la versión sube y
los tokens anteriores dejan de valer al instante, sin esperar a que caduquen. Los usuarios existentes quedan en 0
y los tokens ya emitidos (sin versión) se tratan como versión 0: siguen valiendo hasta que se revoquen o caduquen.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("token_version", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("usuarios", "token_version")
