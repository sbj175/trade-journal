"""
SQLAlchemy 2.0 declarative models for all OptionLedger tables.

Every table from db_manager.initialize_database() and _add_transaction_columns()
is represented here.  Column types, defaults, constraints, and indexes match
the existing schema exactly so that SQLAlchemy can coexist with the legacy
sqlite3 code during the incremental migration.
"""

import uuid
from datetime import datetime, date as date_type
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base class with to_dict() for JSON serialization compatibility
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base with a generic to_dict() helper."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all columns to a plain dict (mirrors dict(sqlite3.Row))."""
        result = {}
        for col in self.__table__.columns:
            value = getattr(self, col.key)
            if isinstance(value, (datetime, date_type)):
                value = value.isoformat()
            result[col.key] = value
        return result


# ---------------------------------------------------------------------------
# User table (multi-tenant)
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=True)
    display_name = Column(String, nullable=True)
    auth_provider = Column(String(20), nullable=True)  # 'supabase' or None for default user
    is_active = Column(Boolean, default=True)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())


# ---------------------------------------------------------------------------
# Account & balance tables
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"

    account_number = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_name = Column(String)
    account_type = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())

    # relationships
    positions = relationship("Position", back_populates="account")

    __table_args__ = (
        Index("idx_accounts_active", "is_active"),
    )


class AccountBalance(Base):
    __tablename__ = "account_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_number = Column(String)
    cash_balance = Column(Float)
    net_liquidating_value = Column(Float)
    margin_equity = Column(Float)
    equity_buying_power = Column(Float)
    derivative_buying_power = Column(Float)
    day_trading_buying_power = Column(Float)
    maintenance_requirement = Column(Float)
    timestamp = Column(String, server_default=func.now())

    __table_args__ = (
        Index("idx_account_balances_account", "account_number"),
        Index("idx_account_balances_timestamp", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Positions (current broker positions)
# ---------------------------------------------------------------------------

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_number = Column(String, ForeignKey("accounts.account_number"), nullable=False)
    symbol = Column(String, nullable=False)
    underlying = Column(String)
    instrument_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    quantity_direction = Column(String)
    average_open_price = Column(Float)
    close_price = Column(Float)
    market_value = Column(Float)
    cost_basis = Column(Float)
    realized_day_gain = Column(Float)
    unrealized_pnl = Column(Float)
    pnl_percent = Column(Float)
    updated_at = Column(String, server_default=func.now())
    # migration-added columns
    opened_at = Column(String)
    expires_at = Column(String)
    strike_price = Column(Float)
    option_type = Column(String)
    chain_id = Column(String)
    strategy_type = Column(String)

    # relationships
    account = relationship("Account", back_populates="positions")

    __table_args__ = (
        Index("idx_positions_account", "account_number"),
        Index("idx_positions_underlying", "underlying"),
        Index("idx_positions_symbol", "symbol"),
        Index("idx_positions_instrument_type", "instrument_type"),
        Index("idx_positions_chain_id", "chain_id"),
    )


# ---------------------------------------------------------------------------
# Order system
# ---------------------------------------------------------------------------

class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_number = Column(String)
    underlying = Column(String)
    order_type = Column(String)
    strategy_type = Column(String)
    order_date = Column(String)
    status = Column(String)
    total_quantity = Column(Integer)
    total_pnl = Column(Float)
    has_assignment = Column(Boolean, default=False)
    has_expiration = Column(Boolean, default=False)
    has_exercise = Column(Boolean, default=False)
    linked_order_id = Column(String)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())

    # relationships
    order_positions = relationship("OrderPosition", back_populates="order")

    __table_args__ = (
        Index("idx_orders_account", "account_number"),
        Index("idx_orders_underlying", "underlying"),
        Index("idx_orders_date", "order_date"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_account_underlying", "account_number", "underlying"),
    )


class OrderPosition(Base):
    __tablename__ = "order_positions"

    position_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    order_id = Column(String, ForeignKey("orders.order_id"))
    account_number = Column(String)
    symbol = Column(String)
    underlying = Column(String)
    instrument_type = Column(String)
    option_type = Column(String)
    strike = Column(Float)
    expiration = Column(String)
    quantity = Column(Integer)
    opening_price = Column(Float)
    closing_price = Column(Float)
    opening_transaction_id = Column(String)
    closing_transaction_id = Column(String)
    opening_action = Column(String)
    closing_action = Column(String)
    status = Column(String)
    pnl = Column(Float)
    # migration-added columns
    opening_order_id = Column(String)
    closing_order_id = Column(String)
    opening_amount = Column(Float)
    closing_amount = Column(Float)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())

    # relationships
    order = relationship("Order", back_populates="order_positions")


# ---------------------------------------------------------------------------
# Order chains
# ---------------------------------------------------------------------------

class OrderChain(Base):
    __tablename__ = "order_chains"

    chain_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    underlying = Column(String)
    account_number = Column(String)
    opening_order_id = Column(String)
    strategy_type = Column(String)
    opening_date = Column(String)
    closing_date = Column(String)
    chain_status = Column(String)
    order_count = Column(Integer)
    total_pnl = Column(Float)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())
    # migration-added columns
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    leg_count = Column(Integer, default=1)
    original_quantity = Column(Integer)
    remaining_quantity = Column(Integer)
    has_assignment = Column(Boolean, default=False)
    assignment_date = Column(String)

    # relationships
    members = relationship("OrderChainMember", back_populates="chain")
    cache_entries = relationship("OrderChainCache", back_populates="chain")

    __table_args__ = (
        Index("idx_order_chains_account", "account_number"),
        Index("idx_order_chains_underlying", "underlying"),
        Index("idx_order_chains_status", "chain_status"),
        Index("idx_order_chains_opening_date", "opening_date"),
        Index("idx_order_chains_account_underlying", "account_number", "underlying"),
    )


class OrderChainMember(Base):
    __tablename__ = "order_chain_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    chain_id = Column(String, ForeignKey("order_chains.chain_id"))
    order_id = Column(String, ForeignKey("orders.order_id"))
    sequence_number = Column(Integer)

    # relationships
    chain = relationship("OrderChain", back_populates="members")

    __table_args__ = (
        UniqueConstraint("chain_id", "order_id"),
        Index("idx_chain_members_chain", "chain_id"),
        Index("idx_chain_members_order", "order_id"),
        Index("idx_chain_members_sequence", "chain_id", "sequence_number"),
    )


class OrderChainCache(Base):
    __tablename__ = "order_chain_cache"

    chain_id = Column(String, ForeignKey("order_chains.chain_id"), primary_key=True)
    order_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    order_data = Column(Text)  # JSON blob

    # relationships
    chain = relationship("OrderChain", back_populates="cache_entries")


# ---------------------------------------------------------------------------
# Raw transactions
# ---------------------------------------------------------------------------

class RawTransaction(Base):
    __tablename__ = "raw_transactions"

    id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_number = Column(String, nullable=False)
    order_id = Column(String)
    transaction_type = Column(String)
    transaction_sub_type = Column(String)
    description = Column(String)
    executed_at = Column(String)
    transaction_date = Column(String)
    action = Column(String)
    symbol = Column(String)
    instrument_type = Column(String)
    underlying_symbol = Column(String)
    quantity = Column(Float)
    price = Column(Float)
    value = Column(Float)
    regulatory_fees = Column(Float)
    clearing_fees = Column(Float)
    commission = Column(Float)
    net_value = Column(Float)
    is_estimated_fee = Column(Boolean)
    created_at = Column(String, server_default=func.now())

    __table_args__ = (
        Index("idx_raw_transactions_order", "order_id"),
        Index("idx_raw_transactions_account", "account_number"),
        Index("idx_raw_transactions_symbol", "symbol"),
        Index("idx_raw_transactions_executed_at", "executed_at"),
        Index("idx_raw_transactions_action", "action"),
    )


# ---------------------------------------------------------------------------
# Sync metadata
# ---------------------------------------------------------------------------

class SyncMetadata(Base):
    __tablename__ = "sync_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    key = Column(String, nullable=False)
    value = Column(String, nullable=False)
    updated_at = Column(String, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_sync_metadata_user_key"),
    )


# ---------------------------------------------------------------------------
# Quote cache
# ---------------------------------------------------------------------------

class QuoteCache(Base):
    __tablename__ = "quote_cache"

    symbol = Column(String, primary_key=True)
    mark = Column(Float)
    bid = Column(Float)
    ask = Column(Float)
    last = Column(Float)
    change = Column(Float)
    change_percent = Column(Float)
    volume = Column(Integer)
    prev_close = Column(Float)
    day_high = Column(Float)
    day_low = Column(Float)
    iv = Column(Float)
    ivr = Column(Float)
    iv_percentile = Column(Float)
    updated_at = Column(String, server_default=func.now())

    __table_args__ = (
        Index("idx_quote_cache_symbol", "symbol"),
        Index("idx_quote_cache_updated", "updated_at"),
    )


# ---------------------------------------------------------------------------
# Strategy targets
# ---------------------------------------------------------------------------

class StrategyTarget(Base):
    __tablename__ = "strategy_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    strategy_name = Column(String, nullable=False)
    profit_target_pct = Column(Float, nullable=False)
    loss_target_pct = Column(Float, nullable=False)
    updated_at = Column(String, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "strategy_name", name="uq_strategy_targets_user_name"),
    )


# ---------------------------------------------------------------------------
# Position lots (V3 lot-based tracking)
# ---------------------------------------------------------------------------

class PositionLot(Base):
    __tablename__ = "position_lots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    transaction_id = Column(String, nullable=False, unique=True)
    account_number = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    underlying = Column(String)
    instrument_type = Column(String)
    option_type = Column(String)
    strike = Column(Float)
    expiration = Column(String)
    quantity = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_date = Column(String, nullable=False)
    remaining_quantity = Column(Integer, nullable=False)
    original_quantity = Column(Integer)
    chain_id = Column(String)
    leg_index = Column(Integer, default=0)
    opening_order_id = Column(String)
    derived_from_lot_id = Column(Integer, ForeignKey("position_lots.id"))
    derivation_type = Column(String)
    status = Column(String, default="OPEN")
    created_at = Column(String, server_default=func.now())

    # self-referential relationship
    derived_from = relationship("PositionLot", remote_side=[id], backref="derived_lots")
    closings = relationship("LotClosing", back_populates="lot", foreign_keys="LotClosing.lot_id")

    __table_args__ = (
        Index("idx_lots_account_symbol", "account_number", "symbol"),
        Index("idx_lots_entry_date", "entry_date"),
        Index("idx_lots_chain", "chain_id"),
        Index("idx_lots_status", "status"),
        Index("idx_lots_derived", "derived_from_lot_id"),
        Index("idx_lots_underlying", "underlying"),
    )


# ---------------------------------------------------------------------------
# Lot closings
# ---------------------------------------------------------------------------

class LotClosing(Base):
    __tablename__ = "lot_closings"

    closing_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    lot_id = Column(Integer, ForeignKey("position_lots.id"), nullable=False)
    closing_order_id = Column(String, nullable=False)
    closing_transaction_id = Column(String)
    quantity_closed = Column(Integer, nullable=False)
    closing_price = Column(Float, nullable=False)
    closing_date = Column(String, nullable=False)
    closing_type = Column(String, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    resulting_lot_id = Column(Integer, ForeignKey("position_lots.id"))
    created_at = Column(String, server_default=func.now())

    # relationships
    lot = relationship("PositionLot", back_populates="closings", foreign_keys=[lot_id])
    resulting_lot = relationship("PositionLot", foreign_keys=[resulting_lot_id])

    __table_args__ = (
        Index("idx_lot_closings_lot", "lot_id"),
        Index("idx_lot_closings_order", "closing_order_id"),
        Index("idx_lot_closings_date", "closing_date"),
    )


# ---------------------------------------------------------------------------
# Position groups (Ledger page)
# ---------------------------------------------------------------------------

class PositionGroup(Base):
    __tablename__ = "position_groups"

    group_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    account_number = Column(String, nullable=False)
    underlying = Column(String, nullable=False)
    strategy_label = Column(String)
    status = Column(String, default="OPEN")
    source_chain_id = Column(String)
    opening_date = Column(String)
    closing_date = Column(String)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())

    # relationships
    group_lots = relationship("PositionGroupLot", back_populates="group",
                              cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_position_groups_account", "account_number"),
        Index("idx_position_groups_underlying", "underlying"),
        Index("idx_position_groups_status", "status"),
        Index("idx_position_groups_source_chain", "source_chain_id"),
    )


class PositionGroupLot(Base):
    __tablename__ = "position_group_lots"

    group_id = Column(String, ForeignKey("position_groups.group_id", ondelete="CASCADE"),
                      primary_key=True)
    transaction_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(String, server_default=func.now())

    # relationships
    group = relationship("PositionGroup", back_populates="group_lots")

    __table_args__ = (
        Index("idx_position_group_lots_txn", "transaction_id"),
    )


# ---------------------------------------------------------------------------
# Order comments
# ---------------------------------------------------------------------------

class OrderComment(Base):
    __tablename__ = "order_comments"

    order_id = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    comment = Column(String, nullable=False)
    updated_at = Column(String, server_default=func.now())


# ---------------------------------------------------------------------------
# Position notes
# ---------------------------------------------------------------------------

class PositionNote(Base):
    __tablename__ = "position_notes"

    note_key = Column(String, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    note = Column(String, nullable=False)
    updated_at = Column(String, server_default=func.now())


# ---------------------------------------------------------------------------
# User credentials (per-user Tastytrade OAuth, encrypted at rest)
# ---------------------------------------------------------------------------

class UserCredential(Base):
    __tablename__ = "user_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(50), default="tastytrade")
    encrypted_provider_secret = Column(Text)
    encrypted_refresh_token = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(String, server_default=func.now())
    updated_at = Column(String, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_credentials_user_provider"),
    )
