"""
Order Assembler — Stage 2 of the OPT-121 pipeline redesign.

Stateless functions that convert raw transaction dicts into classified Order objects.
Extracted from OrderProcessor._preprocess_transactions(), _group_transactions(),
_normalize_transactions(), _classify_order(), and _create_orders().

All functions are pure — no DB access, no position tracking, no side effects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Tuple
from collections import defaultdict
import logging

# Re-export dataclasses from order_processor (no duplication during migration)
from src.models.order_processor import Transaction, Order, OrderType

logger = logging.getLogger(__name__)

__all__ = [
    "Transaction",
    "Order",
    "OrderType",
    "AssemblyResult",
    "preprocess_transactions",
    "group_transactions",
    "normalize_transactions",
    "classify_order",
    "create_orders",
    "assemble_orders",
]


@dataclass
class AssemblyResult:
    """Output of assemble_orders(): orders + side-channel data."""
    orders: List[Order] = field(default_factory=list)
    assignment_stock_transactions: List[Dict] = field(default_factory=list)


def preprocess_transactions(
    raw_transactions: List[Dict],
) -> Tuple[List[Transaction], List[Dict]]:
    """Convert raw transaction dicts to Transaction objects.

    Returns (transactions, assignment_stock_transactions).
    Unlike OrderProcessor._preprocess_transactions(), assignment stock transactions
    are returned explicitly instead of stored on an instance variable.
    """
    transactions: List[Transaction] = []
    assignment_stock_transactions: List[Dict] = []

    # Pre-scan: group Symbol Change transactions so close/open legs share order IDs
    symbol_change_overrides: Dict[str, Dict] = {}
    sym_change_txs = [
        tx
        for tx in raw_transactions
        if tx.get("transaction_sub_type") == "Symbol Change"
    ]
    if sym_change_txs:
        sc_groups: Dict[Tuple, List[Dict]] = defaultdict(list)
        for tx in sym_change_txs:
            acct = tx.get("account_number", "")
            old_under = tx.get("underlying_symbol", "")
            date_str = tx.get("executed_at", "")[:10]
            sc_groups[(acct, old_under, date_str)].append(tx)

        for (acct, old_under, date_str), txs in sc_groups.items():
            close_txs = [
                t for t in txs if "TO_CLOSE" in (t.get("action") or "")
            ]
            open_txs = [
                t for t in txs if "TO_OPEN" in (t.get("action") or "")
            ]

            # Derive new underlying from open legs' symbol
            new_under = old_under
            if open_txs:
                sym = open_txs[0].get("symbol", "")
                if sym:
                    new_under = sym.split()[0]

            close_oid = f"SYMCHG_CLOSE_{acct}_{old_under}_{date_str}"
            open_oid = f"SYMCHG_OPEN_{acct}_{new_under}_{date_str}"

            for t in close_txs:
                symbol_change_overrides[str(t.get("id", ""))] = {
                    "order_id": close_oid,
                    "underlying_symbol": old_under,
                }
            for t in open_txs:
                symbol_change_overrides[str(t.get("id", ""))] = {
                    "order_id": open_oid,
                    "underlying_symbol": new_under,
                }

            if open_txs or close_txs:
                logger.info(
                    f"Symbol change: {old_under} -> {new_under}, "
                    f"{len(close_txs)} close legs, {len(open_txs)} open legs"
                )

    for raw_tx in raw_transactions:
        # Skip non-trading transactions (no symbol)
        # But keep assignment/exercise transactions even if action is None
        if not raw_tx.get("symbol"):
            continue

        # Skip transactions with no action, except assignment/exercise/expiration
        sub_type = raw_tx.get("transaction_sub_type", "").upper()
        if (
            not raw_tx.get("action")
            and "ASSIGNMENT" not in sub_type
            and "EXERCISE" not in sub_type
            and "EXPIR" not in sub_type
        ):
            continue

        # Skip stock transactions that result from assignment/exercise (they have no order_id)
        # These are automatic stock transactions and shouldn't create chains
        # But keep expiration/assignment/exercise option transactions
        # Capture these for derived lot creation (returned explicitly)
        instrument_type = str(raw_tx.get("instrument_type", ""))
        if (
            "EQUITY" in instrument_type
            and "EQUITY_OPTION" not in instrument_type
            and not raw_tx.get("order_id")
            and raw_tx.get("action")
        ):
            assignment_stock_transactions.append(raw_tx)
            continue

        # Generate order ID — use symbol change override if available
        tx_id_str = str(raw_tx.get("id", ""))
        sc_override = symbol_change_overrides.get(tx_id_str)
        if sc_override:
            order_id = sc_override["order_id"]
        else:
            order_id = raw_tx.get("order_id")
            if not order_id:
                # Generate ID for system events like expiration
                executed_at = raw_tx.get("executed_at", "")
                symbol = raw_tx.get("symbol", "")
                action = raw_tx.get("action", "")
                order_id = f"SYSTEM_{raw_tx.get('transaction_sub_type', 'UNKNOWN')}_{executed_at}_{symbol}_{action}"
                order_id = order_id.replace(" ", "_").replace(":", "")

        # Parse option details from symbol if needed
        symbol = raw_tx.get("symbol", "")
        option_type = None
        strike = None
        expiration = None

        instrument_type_str = str(raw_tx.get("instrument_type") or "")
        if (
            "OPTION" in instrument_type_str.upper() or "option" in instrument_type_str
        ) and " " in symbol:
            parts = symbol.split()
            if len(parts) >= 2:
                option_part = parts[1]
                if len(option_part) >= 8:
                    # Extract date
                    date_str = option_part[:6]
                    try:
                        expiration = datetime.strptime(
                            "20" + date_str, "%Y%m%d"
                        ).date()
                    except Exception:
                        pass

                    # Extract type
                    if len(option_part) > 6:
                        option_type = (
                            "Call" if option_part[6] == "C" else "Put"
                        )

                    # Extract strike
                    if len(option_part) > 7:
                        try:
                            strike = float(option_part[7:]) / 1000
                        except Exception:
                            pass

        # Create Transaction object
        tx = Transaction(
            id=str(raw_tx.get("id", "")),
            account_number=raw_tx.get("account_number", ""),
            order_id=order_id,
            symbol=symbol,
            underlying_symbol=(
                sc_override["underlying_symbol"]
                if sc_override
                else raw_tx.get(
                    "underlying_symbol",
                    symbol.split()[0] if symbol and " " in symbol else symbol,
                )
            ),
            action=raw_tx.get("action") or "",
            quantity=int(raw_tx.get("quantity", 0)),
            price=float(raw_tx.get("price") or 0),
            executed_at=datetime.fromisoformat(
                raw_tx.get("executed_at", "").replace("Z", "+00:00")
            ),
            transaction_type=raw_tx.get("transaction_type", ""),
            transaction_sub_type=raw_tx.get("transaction_sub_type", ""),
            description=raw_tx.get("description", ""),
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            commission=float(raw_tx.get("commission", 0)),
            regulatory_fees=float(raw_tx.get("regulatory_fees", 0)),
            clearing_fees=float(raw_tx.get("clearing_fees", 0)),
            value=float(raw_tx.get("value", 0)),
            net_value=float(raw_tx.get("net_value", 0)),
        )

        transactions.append(tx)

    return transactions, assignment_stock_transactions


def group_transactions(
    transactions: List[Transaction],
) -> Dict[Tuple, List[Transaction]]:
    """Group transactions by (account_number, underlying, order_id)."""
    grouped: Dict[Tuple, List[Transaction]] = defaultdict(list)

    for tx in transactions:
        underlying = tx.underlying_symbol
        if " " in underlying:
            underlying = underlying.split()[0]
        key = (tx.account_number, underlying, tx.order_id)
        grouped[key].append(tx)

    return grouped


def normalize_transactions(transactions: List[Transaction]) -> List[Transaction]:
    """Aggregate fills with same (action, symbol, option_type, strike, expiration, price).

    Different prices are NOT aggregated per the processing rules.
    """
    groups: Dict[Tuple, List[Transaction]] = defaultdict(list)

    for tx in transactions:
        key = (tx.action, tx.symbol, tx.option_type, tx.strike, tx.expiration, tx.price)
        groups[key].append(tx)

    normalized: List[Transaction] = []
    for key, group in groups.items():
        if len(group) == 1:
            normalized.append(group[0])
        else:
            total_quantity = sum(tx.quantity for tx in group)
            first_tx = group[0]

            aggregated = Transaction(
                id=",".join(tx.id for tx in group),
                account_number=first_tx.account_number,
                order_id=first_tx.order_id,
                symbol=first_tx.symbol,
                underlying_symbol=first_tx.underlying_symbol,
                action=first_tx.action,
                quantity=total_quantity,
                price=first_tx.price,
                executed_at=min(tx.executed_at for tx in group),
                transaction_type=first_tx.transaction_type,
                transaction_sub_type=first_tx.transaction_sub_type,
                description=f"Aggregated {len(group)} fills",
                option_type=first_tx.option_type,
                strike=first_tx.strike,
                expiration=first_tx.expiration,
                commission=sum(tx.commission for tx in group),
                regulatory_fees=sum(tx.regulatory_fees for tx in group),
                clearing_fees=sum(tx.clearing_fees for tx in group),
                value=sum(tx.value for tx in group),
                net_value=sum(tx.net_value for tx in group),
            )
            normalized.append(aggregated)

    return normalized


def classify_order(transactions: List[Transaction]) -> OrderType:
    """Classify order as OPENING, ROLLING, or CLOSING."""
    has_opening = any(tx.is_opening for tx in transactions)
    has_closing = any(tx.is_closing for tx in transactions)

    if has_opening and not has_closing:
        return OrderType.OPENING
    elif has_closing and not has_opening:
        return OrderType.CLOSING
    elif has_opening and has_closing:
        return OrderType.ROLLING
    else:
        logger.warning(
            f"Could not classify order with transactions: "
            f"{[tx.action for tx in transactions]}"
        )
        return OrderType.CLOSING


def create_orders(
    grouped_transactions: Dict[Tuple, List[Transaction]],
) -> List[Order]:
    """Create normalized, classified Order objects from grouped transactions."""
    orders: List[Order] = []

    for (account, underlying, order_id), transactions in grouped_transactions.items():
        normalized = normalize_transactions(transactions)
        order_type = classify_order(normalized)
        executed_at = min(tx.executed_at for tx in normalized)

        order = Order(
            order_id=order_id,
            account_number=account,
            underlying=underlying,
            executed_at=executed_at,
            order_type=order_type,
            transactions=normalized,
        )
        orders.append(order)

    return orders


def assemble_orders(raw_transactions: List[Dict]) -> AssemblyResult:
    """Top-level entry point: raw transaction dicts -> classified Order objects.

    Composes preprocess -> group -> create -> sort.
    Pure function — no DB access, no position tracking, no side effects.
    """
    transactions, assignment_stock_txs = preprocess_transactions(raw_transactions)
    grouped = group_transactions(transactions)
    orders = create_orders(grouped)
    orders.sort(key=lambda o: o.executed_at)

    return AssemblyResult(
        orders=orders,
        assignment_stock_transactions=assignment_stock_txs,
    )
