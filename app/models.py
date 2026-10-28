# app/models.py
"""
Modelos SQLAlchemy. Reproducen EXACTAMENTE el esquema que ya existe en producción
(nombres de tablas, columnas, tipos, CHECK, claves foráneas con ON DELETE CASCADE e
índices), con una excepción deliberada: watchlist.coin_id es VARCHAR(64) (antes 10),
que se aplica con la migración 0002.

Los CHECK llevan el nombre que PostgreSQL les asignaba automáticamente, para que una base
creada con el código anterior y una creada con Alembic sean idénticas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DINERO = Numeric(18, 8)


def a_dict(objeto) -> dict:
    """Fila -> dict con las columnas (misma forma que devolvían los DAOs con psycopg2)."""
    return {c.key: getattr(objeto, c.key) for c in objeto.__table__.columns}


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())
    # 'usuario' (por defecto) o 'admin'. Nunca se asigna desde la API pública: ver scripts/gestionar_roles.py.
    rol: Mapped[str] = mapped_column(String(20), nullable=False, server_default="usuario")

    __table_args__ = (CheckConstraint("rol IN ('usuario', 'admin')", name="usuarios_rol_check"),)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("tipo IN ('compra', 'venta')", name="trades_tipo_check"),
        CheckConstraint("precio > 0", name="trades_precio_check"),
        CheckConstraint("cantidad > 0", name="trades_cantidad_check"),
        Index("idx_trades_usuario_id", "usuario_id"),
        Index("idx_trades_activo", "activo"),
        Index("idx_trades_fecha", "fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    activo: Mapped[str] = mapped_column(String(10), nullable=False)
    precio: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        CheckConstraint("precio_alerta > 0", name="watchlist_precio_alerta_check"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    coin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    precio_alerta: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    creado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="orders_side_check"),
        CheckConstraint("order_type IN ('MARKET', 'LIMIT', 'STOP_LOSS')", name="orders_order_type_check"),
        Index("idx_orders_usuario", "usuario_id"),
        Index("idx_orders_symbol", "symbol"),
        Index("idx_orders_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    binance_order_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NEW'"))
    quantity: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(DINERO)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(DINERO)
    executed_qty: Mapped[Optional[Decimal]] = mapped_column(DINERO, server_default=text("0"))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())


class PaperWallet(Base):
    """Saldo simulado en USDT de un usuario (una fila por usuario)."""
    __tablename__ = "paper_wallet"
    __table_args__ = (CheckConstraint("balance_usdt >= 0", name="paper_wallet_balance_check"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True)
    balance_usdt: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    saldo_inicial: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    creado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())


class PaperPosition(Base):
    """Posición abierta (solo largos): una fila por usuario y moneda; se borra al llegar a cantidad 0."""
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("usuario_id", "coin_id", name="uq_paper_positions_usuario_coin"),
        CheckConstraint("cantidad > 0", name="paper_positions_cantidad_check"),
        CheckConstraint("precio_medio > 0", name="paper_positions_precio_check"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    coin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    precio_medio: Mapped[Decimal] = mapped_column(DINERO, nullable=False)   # incluye las comisiones de compra
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())


class PaperTrade(Base):
    """Cada ejecución simulada. `client_order_id` (opcional) hace idempotentes los reintentos."""
    __tablename__ = "paper_trades"
    __table_args__ = (
        UniqueConstraint("usuario_id", "client_order_id", name="uq_paper_trades_cliente"),
        CheckConstraint("side IN ('BUY', 'SELL')", name="paper_trades_side_check"),
        CheckConstraint("cantidad > 0", name="paper_trades_cantidad_check"),
        CheckConstraint("precio > 0", name="paper_trades_precio_check"),
        CheckConstraint("comision >= 0", name="paper_trades_comision_check"),
        Index("idx_paper_trades_usuario_fecha", "usuario_id", "ejecutado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    coin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    precio: Mapped[Decimal] = mapped_column(DINERO, nullable=False)          # precio ejecutado (con slippage)
    valor: Mapped[Decimal] = mapped_column(DINERO, nullable=False)           # cantidad x precio, sin comisión
    comision: Mapped[Decimal] = mapped_column(DINERO, nullable=False)
    pnl_realizado: Mapped[Optional[Decimal]] = mapped_column(DINERO)         # solo en ventas
    client_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    ejecutado_en: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())
