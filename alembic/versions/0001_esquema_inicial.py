"""Esquema inicial (adopta el esquema que ya existía)

Antes las tablas se creaban al importar la aplicación con CREATE TABLE IF NOT EXISTS.
Esta migración es IDEMPOTENTE a propósito: en una base que ya tiene esas tablas (producción)
no hace nada ni toca los datos, y en una base vacía crea el esquema completo.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DINERO = sa.Numeric(18, 8)
TIMESTAMP_AHORA = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(20), nullable=False),
        sa.Column("email", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=TIMESTAMP_AHORA),
        sa.UniqueConstraint("username", name="usuarios_username_key"),
        sa.UniqueConstraint("email", name="usuarios_email_key"),
        if_not_exists=True,
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("activo", sa.String(10), nullable=False),
        sa.Column("precio", DINERO, nullable=False),
        sa.Column("cantidad", DINERO, nullable=False),
        sa.Column("fecha", sa.DateTime(), nullable=False),
        sa.CheckConstraint("tipo IN ('compra', 'venta')", name="trades_tipo_check"),
        sa.CheckConstraint("precio > 0", name="trades_precio_check"),
        sa.CheckConstraint("cantidad > 0", name="trades_cantidad_check"),
        if_not_exists=True,
    )

    # coin_id nace con 10 caracteres, como estaba en producción; la migración 0002 lo ensancha.
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coin_id", sa.String(10), nullable=False),
        sa.Column("precio_alerta", DINERO, nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=TIMESTAMP_AHORA),
        sa.CheckConstraint("precio_alerta > 0", name="watchlist_precio_alerta_check"),
        if_not_exists=True,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binance_order_id", sa.BigInteger()),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'NEW'")),
        sa.Column("quantity", DINERO, nullable=False),
        sa.Column("price", DINERO),
        sa.Column("stop_price", DINERO),
        sa.Column("executed_qty", DINERO, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=TIMESTAMP_AHORA),
        sa.Column("updated_at", sa.DateTime(), server_default=TIMESTAMP_AHORA),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="orders_side_check"),
        sa.CheckConstraint("order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS')", name="orders_order_type_check"),
        if_not_exists=True,
    )

    for nombre, tabla, columna in [
        ("idx_trades_usuario_id", "trades", "usuario_id"),
        ("idx_trades_activo", "trades", "activo"),
        ("idx_trades_fecha", "trades", "fecha"),
        ("idx_orders_usuario", "orders", "usuario_id"),
        ("idx_orders_symbol", "orders", "symbol"),
        ("idx_orders_status", "orders", "status"),
    ]:
        op.create_index(nombre, tabla, [columna], if_not_exists=True)


def downgrade() -> None:
    """DESTRUCTIVO: borra las cuatro tablas y todos sus datos. Solo para entornos de desarrollo."""
    for tabla in ("orders", "watchlist", "trades", "usuarios"):
        op.drop_table(tabla, if_exists=True)
