"""Roll continuation where the new leg's expiration matches a
pre-existing sibling group's expiration but at a different strike.

This is the OPT-287 IBIT regression in fixture form. Two open positions
exist before today; a roll forward of one of them produces a new leg
that happens to share its expiration with the *other* still-open
position. Routing must mint a NEW group for the rolled-in leg rather
than absorbing it into the unrelated sibling.

Timeline:
  2026-04-01 14:00  STO 80x ZTEST 2026-04-22 C 41.50  (the sibling — never rolls)
  2026-04-01 14:05  STO 80x ZTEST 2026-04-15 C 43.50  (the source — gets rolled)
  2026-04-15 13:30  BTC 80x ZTEST 2026-04-15 C 43.50  (close source, one ROLLING order)
  2026-04-15 13:30  STO 80x ZTEST 2026-04-22 C 44.00  (open new leg, same order)

Expected post-pipeline:
  - G1: original 4/22 $41.50 — still OPEN, no rolled_from (unrelated to the roll)
  - G2: 4/15 $43.50 — CLOSED (the source)
  - G3: 4/22 $44.00 — OPEN, rolled_from = G2 (the rolled leg, its own group)
"""

from tests.conftest import make_option_transaction


SPEC_SECTION = "§1.1 (lot-level pairing) + §4 (group model)"

DESCRIPTION = (
    "OPT-287 regression. A pre-existing sibling group at the roll's "
    "target expiration must NOT absorb the rolled-in leg via Rule 1 of "
    "the routing function. The new leg gets its own group with "
    "rolled_from pointing at the closed source."
)


_ACCT = "ACCT-OPT287"
_UNDERLYING = "ZTEST"
_QTY = 80


def _sym(exp_iso, option_type, strike):
    """Build an OCC-style symbol: 'ZTEST 260422C00041500'."""
    yymmdd = exp_iso.replace("-", "")[2:]
    cp = "C" if option_type == "Call" else "P"
    strike_part = f"{int(strike * 1000):08d}"
    return f"{_UNDERLYING:6}{yymmdd}{cp}{strike_part}"


def transactions():
    txs = []

    # Day 0, 14:00 — the SIBLING position. Opens at the future target
    # expiration but at a different strike. Never gets rolled in this
    # fixture's window.
    txs.append(make_option_transaction(
        id="t-sib-open", account_number=_ACCT, order_id="O-SIB",
        symbol=_sym("2026-04-22", "Call", 41.50),
        underlying_symbol=_UNDERLYING,
        action="SELL_TO_OPEN", quantity=_QTY, price=1.50,
        executed_at="2026-04-01T14:00:00+00:00",
        option_type="Call", strike=41.50, expiration="2026-04-22",
    ))

    # Day 0, 14:05 — the SOURCE position. Opens at a nearer expiration;
    # will be rolled forward to the same expiration as the sibling.
    txs.append(make_option_transaction(
        id="t-src-open", account_number=_ACCT, order_id="O-SRC",
        symbol=_sym("2026-04-15", "Call", 43.50),
        underlying_symbol=_UNDERLYING,
        action="SELL_TO_OPEN", quantity=_QTY, price=1.20,
        executed_at="2026-04-01T14:05:00+00:00",
        option_type="Call", strike=43.50, expiration="2026-04-15",
    ))

    # Day 14 — close the source + open new leg at the sibling's
    # expiration. One broker ROLLING order, two legs.
    txs.append(make_option_transaction(
        id="t-btc-roll", account_number=_ACCT, order_id="O-ROLL",
        symbol=_sym("2026-04-15", "Call", 43.50),
        underlying_symbol=_UNDERLYING,
        action="BUY_TO_CLOSE", quantity=_QTY, price=0.05,
        executed_at="2026-04-15T13:30:00+00:00",
        option_type="Call", strike=43.50, expiration="2026-04-15",
    ))
    txs.append(make_option_transaction(
        id="t-sto-roll", account_number=_ACCT, order_id="O-ROLL",
        symbol=_sym("2026-04-22", "Call", 44.00),
        underlying_symbol=_UNDERLYING,
        action="SELL_TO_OPEN", quantity=_QTY, price=0.80,
        executed_at="2026-04-15T13:30:00+00:00",
        option_type="Call", strike=44.00, expiration="2026-04-22",
    ))

    return txs


def expected():
    """Canonical post-pipeline state.

    Groups are ordered by (opening_date, first-lot signature):
      G1: sibling (4/22 $41.50, opened 4/1 14:00)
      G2: source  (4/15 $43.50, opened 4/1 14:05) — CLOSED by the roll
      G3: rolled-in leg (4/22 $44.00, opened 4/15 13:30) — rolled_from = G2

    Roll chain summaries are emitted per actual chain (length ≥ 2);
    standalone groups with no lineage produce no row. Here that means
    one row for G2 → G3 and nothing for G1.
    """
    return {
        "underlying": _UNDERLYING,
        "groups": [
            {
                "strategy_label": "Short Call",
                "status": "OPEN",
                "rolled_from": None,
                "lots": [{"option_type": "Call", "strike": 41.50, "expiration": "2026-04-22", "quantity": -_QTY}],
            },
            {
                "strategy_label": "Short Call",
                "status": "CLOSED",
                "rolled_from": None,
                "lots": [{"option_type": "Call", "strike": 43.50, "expiration": "2026-04-15", "quantity": -_QTY}],
            },
            {
                "strategy_label": "Short Call",
                "status": "OPEN",
                "rolled_from": "G2",
                "lots": [{"option_type": "Call", "strike": 44.00, "expiration": "2026-04-22", "quantity": -_QTY}],
            },
        ],
        "roll_chains": [
            {"chain_length": 2, "roll_count": 1},
        ],
    }
