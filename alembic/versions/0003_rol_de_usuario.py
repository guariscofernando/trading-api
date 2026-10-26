"""Añade usuarios.rol ('usuario' | 'admin')

Todos los usuarios existentes quedan como 'usuario'. Para crear el primer administrador:
    python scripts/gestionar_roles.py promover <username>

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("rol", sa.String(20), nullable=False, server_default="usuario"))
    op.create_check_constraint("usuarios_rol_check", "usuarios", "rol IN ('usuario', 'admin')")


def downgrade() -> None:
    op.drop_constraint("usuarios_rol_check", "usuarios", type_="check")
    op.drop_column("usuarios", "rol")
