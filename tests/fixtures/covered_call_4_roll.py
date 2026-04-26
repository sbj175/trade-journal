"""A 4-roll covered call ladder on a single underlying.

Pattern modeled on the user's real IBIT 9-roll chain — same essential
shape, scaled down so the test is readable. Exercises the full pipeline:
chain inheritance, rolled_from linkage across 4 generations, strategy
label stability, multi-day group transitions.

Timeline:
  2025-02-11  STO 32× ZTEST 250213C00038000  — open initial covered call
  2025-02-13  ROLL → 250220C00039500
  2025-02-20  ROLL → 250227C00040000
  2025-02-27  ROLL → 250306C00039000  (rolled down)
  2025-03-06  ROLL → 250313C00039000  (kept strike, out in time)
  (current open: 250313C00039000, expiring 2025-03-13)
"""

from datetime import datetime, date

from tests.conftest import make_option_transaction


_ACCT = "ACCT-COV-CALL"
_UNDERLYING = "ZTEST"
_QTY = 32


def _open(*, exp, strike, executed_at, order_id, tx_id, price=2.50):
    return make_option_transaction(
        id=tx_id, account_number=_ACCT, order_id=order_id,
        symbol=f"{_UNDERLYING:6}{exp.replace('-', '')[2:]}C0{int(strike*1000):07d}",
        underlying_symbol=_UNDERLYING,
        action="SELL_TO_OPEN", quantity=_QTY, price=price,
        executed_at=executed_at,
        option_type="Call", strike=strike, expiration=exp,
    )


def _close(*, exp, strike, executed_at, order_id, tx_id, price=1.00):
    return make_option_transaction(
        id=tx_id, account_number=_ACCT, order_id=order_id,
        symbol=f"{_UNDERLYING:6}{exp.replace('-', '')[2:]}C0{int(strike*1000):07d}",
        underlying_symbol=_UNDERLYING,
        action="BUY_TO_CLOSE", quantity=_QTY, price=price,
        executed_at=executed_at,
        option_type="Call", strike=strike, expiration=exp,
    )


def transactions():
    """Return the full list of raw_transactions for this scenario."""
    txs = []

    # Day 0: initial open
    txs.append(_open(
        exp="2025-02-13", strike=38.0,
        executed_at="2025-02-11T16:00:00+00:00",
        order_id="OPEN-INIT", tx_id="t-open-init", price=0.85,
    ))

    # Each subsequent day: roll = BTC the previous strike + STO the new one
    rolls = [
        # (close_exp, close_strike, close_price, open_exp, open_strike, open_price, executed_at, order_id_suffix)
        ("2025-02-13", 38.0, 0.05, "2025-02-20", 39.5, 0.92, "2025-02-13T20:30:00+00:00", "ROLL-1"),
        ("2025-02-20", 39.5, 0.10, "2025-02-27", 40.0, 1.05, "2025-02-20T19:33:00+00:00", "ROLL-2"),
        ("2025-02-27", 40.0, 0.15, "2025-03-06", 39.0, 1.20, "2025-02-27T20:07:00+00:00", "ROLL-3"),
        ("2025-03-06", 39.0, 0.20, "2025-03-13", 39.0, 1.10, "2025-03-06T20:48:00+00:00", "ROLL-4"),
    ]
    for i, (c_exp, c_strike, c_price, o_exp, o_strike, o_price, exec_at, oid) in enumerate(rolls, 1):
        txs.append(_close(
            exp=c_exp, strike=c_strike,
            executed_at=exec_at, order_id=oid,
            tx_id=f"t-btc-{i}", price=c_price,
        ))
        txs.append(_open(
            exp=o_exp, strike=o_strike,
            executed_at=exec_at, order_id=oid,
            tx_id=f"t-sto-{i}", price=o_price,
        ))

    return txs
