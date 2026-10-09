"""Ensancha watchlist.coin_id de 10 a 64 caracteres

Los IDs de CoinGecko superan los 10 caracteres ('binancecoin', 'wrapped-bitcoin',
'staked-ether'...) y el INSERT fallaba con "value too long for type character varying(10)".
Ampliar un VARCHAR en PostgreSQL no reescribe la tabla ni bloquea lecturas.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "watchlist", "coin_id",
        existing_type=sa.String(10), type_=sa.String(64), existing_nullable=False,
    )


def downgrade() -> None:
    # Falla (a propósito) si ya hay IDs de más de 10 caracteres: no se truncan datos en silencio.
    op.alter_column(
        "watchlist", "coin_id",
        existing_type=sa.String(64), type_=sa.String(10), existing_nullable=False,
    )
