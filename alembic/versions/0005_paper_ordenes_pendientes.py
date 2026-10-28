"""Paper trading: órdenes pendientes LIMIT y STOP

Tabla nueva (no toca datos existentes). El estado, el tipo, el lado y los importes los valida la base.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

DINERO = sa.Numeric(18, 8)


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coin_id", sa.String(64), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("tipo", sa.String(5), nullable=False),
        sa.Column("cantidad", DINERO, nullable=False),
        sa.Column("precio", DINERO, nullable=False),
        sa.Column("estado", sa.String(10), nullable=False, server_default="ABIERTA"),
        sa.Column("motivo", sa.String(200)),
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("paper_trades.id", ondelete="SET NULL")),
        sa.Column("client_order_id", sa.String(64)),
        sa.Column("creada_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.Column("cerrada_en", sa.DateTime),
        sa.UniqueConstraint("usuario_id", "client_order_id", name="uq_paper_orders_cliente"),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="paper_orders_side_check"),
        sa.CheckConstraint("tipo IN ('LIMIT', 'STOP')", name="paper_orders_tipo_check"),
        sa.CheckConstraint("estado IN ('ABIERTA', 'EJECUTADA', 'CANCELADA', 'RECHAZADA')", name="paper_orders_estado_check"),
        sa.CheckConstraint("cantidad > 0", name="paper_orders_cantidad_check"),
        sa.CheckConstraint("precio > 0", name="paper_orders_precio_check"),
    )
    op.create_index("idx_paper_orders_abiertas", "paper_orders", ["estado", "coin_id"])
    op.create_index("idx_paper_orders_usuario", "paper_orders", ["usuario_id", "id"])


def downgrade() -> None:
    # Borra las órdenes pendientes y su historial (dinero simulado, pero no se recupera).
    op.drop_index("idx_paper_orders_usuario", table_name="paper_orders")
    op.drop_index("idx_paper_orders_abiertas", table_name="paper_orders")
    op.drop_table("paper_orders")
