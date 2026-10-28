"""Paper trading: billetera, posiciones y trades simulados

Tablas nuevas (no tocan datos existentes). Todo el dinero es NUMERIC(18,8); las reglas básicas
(saldo >= 0, cantidades y precios > 0, side BUY/SELL, una posición por usuario y moneda,
un client_order_id por usuario) las garantiza la base, no solo el código.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

DINERO = sa.Numeric(18, 8)


def upgrade() -> None:
    op.create_table(
        "paper_wallet",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("balance_usdt", DINERO, nullable=False),
        sa.Column("saldo_inicial", DINERO, nullable=False),
        sa.Column("creado_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("balance_usdt >= 0", name="paper_wallet_balance_check"),
    )
    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coin_id", sa.String(64), nullable=False),
        sa.Column("cantidad", DINERO, nullable=False),
        sa.Column("precio_medio", DINERO, nullable=False),
        sa.Column("actualizado_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("usuario_id", "coin_id", name="uq_paper_positions_usuario_coin"),
        sa.CheckConstraint("cantidad > 0", name="paper_positions_cantidad_check"),
        sa.CheckConstraint("precio_medio > 0", name="paper_positions_precio_check"),
    )
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("usuario_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coin_id", sa.String(64), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("cantidad", DINERO, nullable=False),
        sa.Column("precio", DINERO, nullable=False),
        sa.Column("valor", DINERO, nullable=False),
        sa.Column("comision", DINERO, nullable=False),
        sa.Column("pnl_realizado", DINERO),
        sa.Column("client_order_id", sa.String(64)),
        sa.Column("ejecutado_en", sa.DateTime, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("usuario_id", "client_order_id", name="uq_paper_trades_cliente"),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="paper_trades_side_check"),
        sa.CheckConstraint("cantidad > 0", name="paper_trades_cantidad_check"),
        sa.CheckConstraint("precio > 0", name="paper_trades_precio_check"),
        sa.CheckConstraint("comision >= 0", name="paper_trades_comision_check"),
    )
    op.create_index("idx_paper_trades_usuario_fecha", "paper_trades", ["usuario_id", "ejecutado_en"])


def downgrade() -> None:
    # Borra las tablas de paper trading y TODOS sus datos (es dinero simulado, pero no se recupera).
    op.drop_index("idx_paper_trades_usuario_fecha", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_table("paper_positions")
    op.drop_table("paper_wallet")
