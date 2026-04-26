"""Direct unit tests for src/pipeline/roll_splitter.py.

Covers the four behaviors of split_rolling_orders:
1. Non-ROLLING orders pass through unchanged.
2. ROLLING with a single opening symbol is left intact (simple roll).
3. ROLLING whose closes mirror its opens by (option_type, direction)
   stays intact — that's a multi-leg roll, not a compound roll
   (OPT-262 invariant).
4. ROLLING with multiple opening symbols whose closes don't mirror the
   opens splits into a ROLLING (close + closest-strike open) plus an
   OPENING (the remaining new positions, given a derived order_id).
"""

from datetime import date, datetime

from src.models.order_processor import Order, OrderType, Transaction
from src.pipeline.roll_splitter import split_rolling_orders


def _tx(*, action, symbol, option_type, strike, qty=1, order_id="ORD-1"):
    """Shorthand option transaction. expiration & timestamps set so the
    splitter has the fields it reads (it doesn't care about most)."""
    return Transaction(
        id=f"tx-{action}-{strike}",
        account_number="ACCT",
        order_id=order_id,
        symbol=symbol,
        underlying_symbol="AAPL",
        action=action,
        quantity=qty,
        price=1.0,
        executed_at=datetime(2025, 3, 15, 10, 0, 0),
        transaction_type="Trade",
        transaction_sub_type="",
        description="",
        option_type=option_type,
        strike=strike,
        expiration=date(2025, 4, 18),
    )


def _order(*, order_type, transactions, order_id="ORD-1"):
    return Order(
        order_id=order_id,
        account_number="ACCT",
        underlying="AAPL",
        executed_at=datetime(2025, 3, 15, 10, 0, 0),
        order_type=order_type,
        transactions=transactions,
    )


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------

class TestPassThrough:
    def test_opening_order_unchanged(self):
        """An OPENING order should pass through the splitter unchanged."""
        order = _order(order_type=OrderType.OPENING, transactions=[
            _tx(action="SELL_TO_OPEN", symbol="AAPL  250418C00100000",
                option_type="C", strike=100.0),
        ])

        result = split_rolling_orders([order])

        assert len(result) == 1
        assert result[0] is order

    def test_closing_order_unchanged(self):
        """A CLOSING order (no opens) should pass through unchanged."""
        order = _order(order_type=OrderType.CLOSING, transactions=[
            _tx(action="BUY_TO_CLOSE", symbol="AAPL  250418C00100000",
                option_type="C", strike=100.0),
        ])

        result = split_rolling_orders([order])

        assert len(result) == 1 and result[0] is order

    def test_simple_roll_unchanged(self):
        """A ROLLING order with one closing leg + one opening leg (the basic 1-to-1 roll) should not be split."""
        order = _order(order_type=OrderType.ROLLING, transactions=[
            _tx(action="BUY_TO_CLOSE", symbol="AAPL  250321C00100000",
                option_type="C", strike=100.0),
            _tx(action="SELL_TO_OPEN", symbol="AAPL  250418C00105000",
                option_type="C", strike=105.0),
        ])

        result = split_rolling_orders([order])

        assert len(result) == 1
        assert result[0] is order
        assert result[0].order_type == OrderType.ROLLING


# ---------------------------------------------------------------------------
# OPT-262 invariant: multi-leg rolls stay intact
# ---------------------------------------------------------------------------

class TestMultiLegRollKeptIntact:
    def test_put_spread_roll_stays_intact(self):
        """Rolling a put spread (1 long put + 1 short put) in one order: closes mirror opens by (option_type, direction), so the splitter must keep the order whole — each new leg pairs with its direction-matched close during lot processing."""
        order = _order(order_type=OrderType.ROLLING, transactions=[
            _tx(action="SELL_TO_CLOSE", symbol="AAPL  250321P00045000",
                option_type="P", strike=45.0),
            _tx(action="BUY_TO_CLOSE", symbol="AAPL  250321P00050000",
                option_type="P", strike=50.0),
            _tx(action="BUY_TO_OPEN", symbol="AAPL  250418P00040000",
                option_type="P", strike=40.0),
            _tx(action="SELL_TO_OPEN", symbol="AAPL  250418P00045000",
                option_type="P", strike=45.0),
        ])

        result = split_rolling_orders([order])

        assert len(result) == 1
        assert result[0].order_type == OrderType.ROLLING
        assert len(result[0].opening_transactions) == 2
        assert len(result[0].closing_transactions) == 2

    def test_iron_condor_roll_stays_intact(self):
        """A 4-leg Iron Condor rolled in one order — 2 short calls/puts + 2 long calls/puts on each side — has closes mirroring opens by (option_type, direction). Must stay intact."""
        order = _order(order_type=OrderType.ROLLING, transactions=[
            # 4 closes
            _tx(action="BUY_TO_CLOSE", symbol="OLD-SP", option_type="P", strike=95.0),
            _tx(action="SELL_TO_CLOSE", symbol="OLD-LP", option_type="P", strike=90.0),
            _tx(action="BUY_TO_CLOSE", symbol="OLD-SC", option_type="C", strike=105.0),
            _tx(action="SELL_TO_CLOSE", symbol="OLD-LC", option_type="C", strike=110.0),
            # 4 opens at new strikes
            _tx(action="SELL_TO_OPEN", symbol="NEW-SP", option_type="P", strike=85.0),
            _tx(action="BUY_TO_OPEN", symbol="NEW-LP", option_type="P", strike=80.0),
            _tx(action="SELL_TO_OPEN", symbol="NEW-SC", option_type="C", strike=115.0),
            _tx(action="BUY_TO_OPEN", symbol="NEW-LC", option_type="C", strike=120.0),
        ])

        result = split_rolling_orders([order])

        assert len(result) == 1
        assert result[0].order_type == OrderType.ROLLING


# ---------------------------------------------------------------------------
# Compound roll splits
# ---------------------------------------------------------------------------

class TestCompoundRollSplits:
    def test_roll_plus_extra_open_splits(self):
        """Closing a covered call AND opening two distinct calls (e.g., the roll target + an extra income leg) is a 'compound' roll — the close pairs with the closest-strike open as ROLLING, the rest is split off as an OPENING with a derived order_id."""
        order = _order(
            order_type=OrderType.ROLLING,
            order_id="ORD-X",
            transactions=[
                # Close the existing 100C
                _tx(action="BUY_TO_CLOSE", symbol="AAPL  250321C00100000",
                    option_type="C", strike=100.0, order_id="ORD-X"),
                # Roll target: new 105C (closer to old 100 than the 115)
                _tx(action="SELL_TO_OPEN", symbol="AAPL  250418C00105000",
                    option_type="C", strike=105.0, order_id="ORD-X"),
                # Extra new income leg: 115C
                _tx(action="SELL_TO_OPEN", symbol="AAPL  250418C00115000",
                    option_type="C", strike=115.0, order_id="ORD-X"),
            ],
        )

        result = split_rolling_orders([order])

        assert len(result) == 2

        rolling = next(o for o in result if o.order_type == OrderType.ROLLING)
        opening = next(o for o in result if o.order_type == OrderType.OPENING)

        # Roll keeps the close + closest-strike open (100 → 105)
        roll_open_strikes = {t.strike for t in rolling.opening_transactions}
        assert roll_open_strikes == {105.0}
        assert {t.strike for t in rolling.closing_transactions} == {100.0}
        assert rolling.order_id == "ORD-X"

        # Split-off OPENING gets the orphan leg with a derived order_id
        assert {t.strike for t in opening.opening_transactions} == {115.0}
        assert opening.order_id == "ORD-X_split"
        # And the orphan leg's transaction has been re-stamped with the
        # split order_id so downstream lot creation doesn't re-merge them.
        assert opening.transactions[0].order_id == "ORD-X_split"
