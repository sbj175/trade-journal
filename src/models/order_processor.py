"""
Order Processing Engine — dataclasses and thin delegator.

Defines Transaction, Order, Chain, and OrderType dataclasses used throughout
the pipeline.  ``OrderProcessor`` is a convenience wrapper that delegates to
``order_assembler`` (Stage 2) and ``position_ledger`` (Stage 3).
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Set, Tuple, TYPE_CHECKING
from enum import Enum
import logging
from collections import defaultdict

if TYPE_CHECKING:
    from src.models.lot_manager import LotManager

logger = logging.getLogger(__name__)


class OrderType(Enum):
    OPENING = "OPENING"
    ROLLING = "ROLLING"
    CLOSING = "CLOSING"


@dataclass
class Transaction:
    """Represents a single transaction/fill"""
    id: str
    account_number: str
    order_id: str
    symbol: str
    underlying_symbol: str
    action: str  # BTO, STO, BTC, STC
    quantity: int
    price: float
    executed_at: datetime
    transaction_type: str
    transaction_sub_type: str
    description: str
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[date] = None
    commission: float = 0.0
    regulatory_fees: float = 0.0
    clearing_fees: float = 0.0
    value: float = 0.0
    net_value: float = 0.0

    @property
    def is_opening(self) -> bool:
        return 'TO_OPEN' in (self.action or '')

    @property
    def is_closing(self) -> bool:
        return ('TO_CLOSE' in (self.action or '') or
                self.is_expiration or
                self.is_assignment or
                self.is_exercise)

    @property
    def is_expiration(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'EXPIR' in sub_type

    @property
    def is_assignment(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'ASSIGNMENT' in sub_type

    @property
    def is_exercise(self) -> bool:
        sub_type = (self.transaction_sub_type or '').upper()
        return 'EXERCISE' in sub_type

    @property
    def is_buy(self) -> bool:
        return 'BUY' in (self.action or '')

    @property
    def is_sell(self) -> bool:
        return 'SELL' in (self.action or '')

    @property
    def is_cash_settlement(self) -> bool:
        desc = (self.description or '').lower()
        return 'cash settlement' in desc


@dataclass
class Order:
    """Represents an order (group of transactions)"""
    order_id: str
    account_number: str
    underlying: str
    executed_at: datetime
    order_type: OrderType
    transactions: List[Transaction] = field(default_factory=list)

    @property
    def opening_transactions(self) -> List[Transaction]:
        return [t for t in self.transactions if t.is_opening]

    @property
    def closing_transactions(self) -> List[Transaction]:
        return [t for t in self.transactions if t.is_closing]

    @property
    def symbols(self) -> Set[str]:
        return {t.symbol for t in self.transactions}


@dataclass
class Chain:
    """Represents a derived order chain"""
    chain_id: str
    underlying: str
    account_number: str
    orders: List[Order] = field(default_factory=list)
    status: str = "OPEN"  # OPEN or CLOSED

    @property
    def opening_date(self) -> Optional[date]:
        if self.orders:
            return self.orders[0].executed_at.date()
        return None

    @property
    def closing_date(self) -> Optional[date]:
        if self.status == "CLOSED" and self.orders:
            return self.orders[-1].executed_at.date()
        return None


class OrderProcessor:
    """Order processing engine — thin delegator to pipeline stages.

    Delegates to ``order_assembler.assemble_orders()`` (Stage 2) and
    ``position_ledger.process_lots()`` (Stage 3).  Chain derivation is
    handled separately by Stage 4 (``chain_graph.derive_chains()``).
    """

    def __init__(self, db_manager, lot_manager: 'LotManager'):
        self.db = db_manager
        self.lot_manager = lot_manager

    def process_transactions(self, raw_transactions: List[Dict]) -> None:
        """Convert raw transactions into lots via the pipeline.

        Callers that need chains should use ``chain_graph.derive_chains()``
        after calling this method.
        """
        from src.pipeline.order_assembler import assemble_orders
        from src.pipeline.position_ledger import process_lots

        logger.info(f"Processing {len(raw_transactions)} transactions")

        assembly = assemble_orders(raw_transactions)
        process_lots(
            assembly.orders,
            assembly.assignment_stock_transactions,
            self.lot_manager,
            self.db,
        )
