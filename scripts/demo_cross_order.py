#!/usr/bin/env python3
"""Demo: cross-order strategy evolution visible on the Ledger page.

Usage:
    venv/bin/python scripts/demo_cross_order.py inject     # Bull Put Spread
    venv/bin/python scripts/demo_cross_order.py add-wing   # + Bear Call Spread → Iron Condor
    venv/bin/python scripts/demo_cross_order.py cleanup    # Remove all ZTEST data

Between steps, open http://localhost:8000/ledger, filter to ZTEST, and watch
the strategy label evolve from "Bull Put Spread" → "Iron Condor".
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dependencies import db, lot_manager
from src.pipeline.orchestrator import reprocess
from src.database.models import PositionGroup, PositionGroupLot, PositionLot, LotClosing

# Initialize engine + tables (no-op if already created)
db.initialize_database()


# ── Constants ──────────────────────────────────────────────────────────────

ACCOUNT = "TESTACCT"
UNDERLYING = "ZTEST"
EXPIRATION = "2026-09-18"


# ── Transaction builders ──────────────────────────────────────────────────

def _make_txn(*, id, order_id, symbol, action, quantity, price, executed_at,
              option_type, strike, transaction_sub_type, description):
    """Build a raw transaction dict for an option."""
    return {
        "id": id,
        "account_number": ACCOUNT,
        "order_id": order_id,
        "symbol": symbol,
        "underlying_symbol": UNDERLYING,
        "action": action,
        "quantity": quantity,
        "price": price,
        "executed_at": executed_at,
        "instrument_type": "EQUITY_OPTION",
        "transaction_type": "Trade",
        "transaction_sub_type": transaction_sub_type,
        "description": description,
        "option_type": option_type,
        "strike": strike,
        "expiration": EXPIRATION,
        "value": price * quantity * 100,
        "net_value": price * quantity * 100,
        "commission": 0.0,
        "regulatory_fees": 0.0,
        "clearing_fees": 0.0,
    }


def bull_put_spread_txns():
    """Short $50 put + long $45 put."""
    return [
        _make_txn(
            id="tx-bps-short", order_id="ORD-BPS-001",
            symbol="ZTEST  260918P00050000",
            action="SELL_TO_OPEN", quantity=1, price=2.00,
            executed_at="2026-06-01T10:00:00+00:00",
            option_type="Put", strike=50.0,
            transaction_sub_type="Sell to Open",
            description="Sold 1 ZTEST 09/18/26 Put 50.00",
        ),
        _make_txn(
            id="tx-bps-long", order_id="ORD-BPS-001",
            symbol="ZTEST  260918P00045000",
            action="BUY_TO_OPEN", quantity=1, price=1.00,
            executed_at="2026-06-01T10:00:00+00:00",
            option_type="Put", strike=45.0,
            transaction_sub_type="Buy to Open",
            description="Bought 1 ZTEST 09/18/26 Put 45.00",
        ),
    ]


def bear_call_spread_txns():
    """Short $55 call + long $60 call."""
    return [
        _make_txn(
            id="tx-bcs-short", order_id="ORD-BCS-001",
            symbol="ZTEST  260918C00055000",
            action="SELL_TO_OPEN", quantity=1, price=2.00,
            executed_at="2026-06-02T10:00:00+00:00",
            option_type="Call", strike=55.0,
            transaction_sub_type="Sell to Open",
            description="Sold 1 ZTEST 09/18/26 Call 55.00",
        ),
        _make_txn(
            id="tx-bcs-long", order_id="ORD-BCS-001",
            symbol="ZTEST  260918C00060000",
            action="BUY_TO_OPEN", quantity=1, price=1.00,
            executed_at="2026-06-02T10:00:00+00:00",
            option_type="Call", strike=60.0,
            transaction_sub_type="Buy to Open",
            description="Bought 1 ZTEST 09/18/26 Call 60.00",
        ),
    ]


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_inject():
    """Insert Bull Put Spread for ZTEST and run pipeline."""
    # Clean any prior ZTEST data first
    _cleanup_silent()

    txs = bull_put_spread_txns()
    result = reprocess(db, lot_manager, txs, {UNDERLYING})

    _print_state("inject")
    print(f"  Pipeline: {result.orders_assembled} orders, "
          f"{result.chains_derived} chains, {result.groups_processed} groups")
    print()
    print("  Open http://localhost:8000/ledger and filter to ZTEST.")
    print("  You should see: Bull Put Spread (OPEN)")
    print()
    print("  Next step: venv/bin/python scripts/demo_cross_order.py add-wing")


def cmd_add_wing():
    """Add Bear Call Spread to make it an Iron Condor."""
    # Check that inject was run first
    with db.get_session() as session:
        count = session.query(PositionLot).filter(
            PositionLot.underlying == UNDERLYING,
        ).count()
    if count == 0:
        print("ERROR: No ZTEST data found. Run 'inject' first.")
        sys.exit(1)

    # Reprocess with all transactions (BPS + BCS)
    txs = bull_put_spread_txns() + bear_call_spread_txns()
    result = reprocess(db, lot_manager, txs, {UNDERLYING})

    _print_state("add-wing")
    print(f"  Pipeline: {result.orders_assembled} orders, "
          f"{result.chains_derived} chains, {result.groups_processed} groups")
    print()
    print("  Refresh the Ledger page and filter to ZTEST.")
    print("  You should see: Iron Condor (OPEN)")
    print()
    print("  When done: venv/bin/python scripts/demo_cross_order.py cleanup")


def cmd_cleanup():
    """Remove all ZTEST data from the database."""
    _cleanup_silent()
    print("[cleanup] All ZTEST data removed.")


def _cleanup_silent():
    """Delete all lots, closings, and groups for ZTEST."""
    lot_manager.clear_all_lots(underlyings={UNDERLYING})


def _print_state(step):
    """Print current ZTEST state from the database."""
    with db.get_session() as session:
        groups = [
            (g.strategy_label, g.status)
            for g in session.query(PositionGroup).filter(
                PositionGroup.underlying == UNDERLYING,
            ).all()
        ]
        lots = [
            (lot.quantity, lot.option_type, lot.strike, lot.status, lot.remaining_quantity)
            for lot in session.query(PositionLot).filter(
                PositionLot.underlying == UNDERLYING,
            ).all()
        ]

    print(f"\n[{step}] ZTEST state:")
    print(f"  Lots: {len(lots)}")
    for qty, opt_type, strike, status, remaining in lots:
        side = "short" if qty < 0 else "long"
        print(f"    {side} {opt_type} ${strike} ({status}, remaining={remaining})")
    print(f"  Groups: {len(groups)}")
    for label, status in groups:
        print(f"    {label} ({status})")


# ── Main ──────────────────────────────────────────────────────────────────

COMMANDS = {
    "inject": cmd_inject,
    "add-wing": cmd_add_wing,
    "cleanup": cmd_cleanup,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS)}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
