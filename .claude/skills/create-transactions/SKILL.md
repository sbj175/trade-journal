---
name: create-transactions
description: Create synthetic Tastytrade raw transactions (equity and option trades) for loading into the raw_transactions table. Use when the user asks to create test data, sample transactions, or seed trade data.
disable-model-invocation: true
allowed-tools: Read, Bash, Edit, Write
argument-hint: [description of trades to create]
---

# Create Raw Transactions for OptionLedger

You are creating synthetic Tastytrade transactions to insert into the `raw_transactions` table. The user will describe the trades they want and you will generate the correct transaction records.

## User Request

$ARGUMENTS

## Instructions

1. Ask clarifying questions if needed (account number, dates, quantities, prices)
2. Generate transaction dicts following the exact schema below
3. Write a Python script that **first deletes all existing raw_transactions** for the user, then inserts the new ones via `DatabaseManager.save_raw_transactions()`
4. Run the script — it should delete, insert, and reprocess all in one go

## Raw Transaction Schema

Every transaction is a dict with these keys:

```python
{
    "id": str,                    # Unique ID (use "synth-{N}" pattern)
    "account_number": str,        # e.g., "5WZ28644"
    "order_id": str | None,       # Links legs of same order (e.g., "synth-ord-001")
    "symbol": str,                # Equity: "AAPL", Option: "AAPL  250321C00170000"
    "underlying_symbol": str,     # Always the base ticker: "AAPL"
    "action": str | None,         # "BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE", or None
    "quantity": float,            # Shares or contracts (always positive)
    "price": float,               # Per-share or per-contract price
    "executed_at": str,           # ISO 8601 UTC: "2025-03-01T10:00:00+00:00"
    "transaction_date": str,      # Same date as executed_at (date portion)
    "instrument_type": str,       # "EQUITY" or "EQUITY_OPTION"
    "transaction_type": str,      # Usually "Trade"
    "transaction_sub_type": str,  # "Buy to Open", "Sell to Open", "Buy to Close", "Sell to Close", "Expiration", "Assignment", "Exercise"
    "description": str,           # Human-readable: "Sold 1 AAPL 03/21/25 Call 170.00"
    "value": float,               # price * quantity (equity) or price * quantity * 100 (options)
    "net_value": float,           # Usually same as value (no fees for synthetic)
    "commission": 0.0,
    "regulatory_fees": 0.0,
    "clearing_fees": 0.0,
    "is_estimated_fee": False,
}
```

## Option Symbol Format

Options use OCC symbology, space-padded to 6 chars for the underlying:

```
"AAPL  250321C00170000"
 ^^^^  ^^^^^^ ^^^^^^^^
 |     |    | |
 |     |    | Strike in thousandths (170.000 = 170 * 1000 = 00170000)
 |     |    Option type: C=Call, P=Put
 |     Expiration: YYMMDD
 Underlying (left-padded with spaces to 6 chars total)
```

Examples:
- `"AAPL  250321C00170000"` = AAPL Mar 21 2025 Call $170
- `"IBIT  260417P00050000"` = IBIT Apr 17 2026 Put $50
- `"ORCL  260320P00145000"` = ORCL Mar 20 2026 Put $145
- `"SPY   250221C00600000"` = SPY Feb 21 2025 Call $600

## Action & Sub-Type Mapping

| Action | transaction_sub_type | Description Pattern |
|--------|---------------------|-------------------|
| BUY_TO_OPEN | Buy to Open | "Bought {qty} {symbol_desc}" |
| SELL_TO_OPEN | Sell to Open | "Sold {qty} {symbol_desc}" |
| BUY_TO_CLOSE | Buy to Close | "Bought {qty} {symbol_desc}" |
| SELL_TO_CLOSE | Sell to Close | "Sold {qty} {symbol_desc}" |
| None | Expiration | "Expiration of {symbol}" |
| None | Assignment | "Assignment of {symbol}" |
| None | Exercise | "Exercise of {symbol}" |

## Special Transaction Types

**Expiration** (option expires worthless):
- `action`: None, `price`: 0.0, `value`: 0.0, `order_id`: None

**Assignment** (option assigned):
- `action`: None, `price`: 0.0, `value`: 0.0, `order_id`: None
- Generates a corresponding equity transaction (shares bought/sold at strike)

**Multi-leg orders** (spreads, iron condors):
- All legs share the same `order_id`
- Each leg is a separate transaction

## Value Calculation

- **Equity**: `value = price * quantity`
- **Options**: `value = price * quantity * 100` (100 shares per contract)
- For sells/credits, value should be positive
- For buys/debits, value should be negative (or positive depending on Tastytrade convention — match existing data)

## Insertion Script Pattern

The script respects `DATABASE_URL` from `.env` so it inserts into PostgreSQL when configured.
Ask the user which account number and user_id to use.

```python
#!/usr/bin/env python3
"""Insert synthetic transactions into raw_transactions."""
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()  # picks up DATABASE_URL from .env → uses PostgreSQL when configured

from src.database.db_manager import DatabaseManager
from src.database.tenant import set_current_user_id, DEFAULT_USER_ID

# Set user context — ask the user for their user_id, or use DEFAULT_USER_ID for local dev
set_current_user_id(DEFAULT_USER_ID)

db = DatabaseManager()
db.initialize_database()

# Step 1: Delete all existing raw_transactions for this user
from src.database.models import RawTransaction
with db.get_session() as session:
    deleted = session.query(RawTransaction).delete()
    session.commit()
    print(f"Deleted {deleted} existing raw_transactions")

# Step 2: Insert new synthetic transactions
transactions = [
    # ... generated transactions ...
]

saved, symbols = db.save_raw_transactions(transactions)
print(f"Saved {saved} transactions, symbols: {symbols}")

# Ensure user can bypass TT onboarding gate (insert dummy credential if missing)
from src.database.models import UserCredential
from src.database.engine import dialect_insert
with db.get_session() as session:
    stmt = dialect_insert(UserCredential).values(
        user_id=USER_ID,
        provider="tastytrade",
        encrypted_provider_secret=None,
        encrypted_refresh_token=None,
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["user_id", "provider"])
    session.execute(stmt)
    session.commit()
    print("Ensured user_credentials row exists (TT onboarding bypass)")
```

After insertion, run the reprocess pipeline + cache update directly in the same script:

```python
from src.pipeline.orchestrator import reprocess
from src.models.lot_manager import LotManager

lot_manager = LotManager(db)
raw_transactions = db.get_raw_transactions()
print(f"Reprocessing {len(raw_transactions)} raw transactions...")

result = reprocess(db, lot_manager, raw_transactions)
print(f"Orders assembled: {result.orders_assembled}")
print(f"Groups processed: {result.groups_processed}")
print(f"Equity lots netted: {result.equity_lots_netted}")
print(f"P&L events populated: {result.pnl_events_populated}")
```

## Randomization Requirements

Each invocation MUST produce a fresh, distinct set of transactions. Do NOT reuse the same tickers, strategies, dates, prices, or quantities from previous runs. To ensure variety:

1. **Tickers**: Pick from a broad universe. Rotate through different sectors each time:
   - Tech: AAPL, MSFT, NVDA, AMD, GOOGL, META, AMZN, NFLX, CRM, ADBE, ORCL, INTC, AVGO, SHOP, SNOW
   - Finance: JPM, GS, BAC, MS, V, MA, AXP, SCHW, BLK, C
   - Healthcare: UNH, JNJ, LLY, PFE, ABBV, MRK, TMO, ABT, AMGN, GILD
   - Consumer: COST, WMT, TGT, NKE, SBUX, MCD, HD, LOW, TJX, PG
   - Energy/Industrial: XOM, CVX, COP, CAT, DE, BA, GE, LMT, RTX, HON
   - ETFs: SPY, QQQ, IWM, DIA, XLF, XLE, XLK, GLD, SLV, TLT, IBIT, EEM, EWZ
   - Meme/volatile: TSLA, COIN, PLTR, SOFI, RIVN, GME, MARA, RBLX, DKNG, ROKU
   - Don't use more than 2-3 from any single group. Aim for 8-12 distinct underlyings total.

2. **Strategies**: Mix it up. Don't repeat the same pattern each time. Choose from:
   - Naked/cash-secured puts, covered calls, naked calls
   - Bull put spreads, bear call spreads, bull call spreads, bear put spreads
   - Iron condors, iron butterflies, strangles, straddles
   - Calendar spreads, diagonal spreads
   - Long puts, long calls (directional)
   - Equity buy/sell
   - Jade lizards, ratio spreads
   - Rolls (close one expiration, open the next in the same order)

3. **Dates**: Spread trades across a ~4 month window ending near today's date. Vary:
   - Open dates (don't cluster everything in the same week)
   - Hold durations (some held days, some weeks, some months)
   - Expiration cycles (use monthlies AND weeklies, different months)

4. **Quantities**: Vary contract counts (1-10) and share quantities (25, 50, 100, 200, etc.)

5. **Prices**: Use realistic prices for the underlying. A $500 stock should have higher option premiums than a $50 stock. Strike selection should be realistic (OTM puts ~5-15% below spot, OTM calls ~5-15% above spot).

6. **Outcomes**: Unless the user specifies, aim for roughly:
   - 50-60% winners, 30-40% losers, 10-20% still open
   - Mix of closing methods: bought/sold to close, expired worthless, assigned

## Verification Query

After reprocessing, always verify the results by querying the pipeline output. Use this exact pattern:

```python
# Verify groups and lots
from sqlalchemy import text

with get_session(user_id=USER_ID) as session:
    print("=== GROUPS ===")
    groups = session.execute(text(
        "SELECT group_id, underlying, strategy_label, status, opening_date "
        "FROM position_groups WHERE user_id = :uid ORDER BY opening_date"
    ), {"uid": USER_ID}).fetchall()
    for g in groups:
        print(f"  {g.underlying}  strategy={g.strategy_label}  status={g.status}  opened={g.opening_date}")

    print("\n=== LOTS ===")
    lots = session.execute(text(
        "SELECT l.symbol, l.quantity, l.option_type, l.strike, l.expiration, "
        "l.status, l.entry_price, l.chain_id "
        "FROM position_lots l WHERE l.user_id = :uid ORDER BY l.chain_id, l.symbol"
    ), {"uid": USER_ID}).fetchall()
    for l in lots:
        print(f"  {l.symbol:30s}  qty={l.quantity}  type={l.option_type}  status={l.status}  entry={l.entry_price}  chain={l.chain_id[:8] if l.chain_id else 'none'}")
```

### Key Schema Reference (avoid wrong column names)

**position_groups**: `id`, `group_id`, `user_id`, `account_number`, `underlying`, `strategy_label`, `strategy_label_user_override`, `status`, `opening_date`, `closing_date`, `last_activity_date`, `rolled_from_group_id`

**position_lots**: `id`, `user_id`, `transaction_id`, `account_number`, `symbol`, `underlying`, `instrument_type`, `option_type`, `strike`, `expiration`, `quantity`, `entry_price`, `entry_date`, `remaining_quantity`, `original_quantity`, `chain_id`, `leg_index`, `opening_order_id`, `derived_from_lot_id`, `derivation_type`, `status`

**position_group_lots**: `id`, `group_id`, `transaction_id`, `user_id`, `assigned_at`

Common mistakes to avoid:
- There is NO `quantity_direction` column — direction is inferred from context (Sell to Open = Short)
- There is NO `lot_id` — use `id` on position_lots
- There is NO `has_roll_chain` on position_groups
- `position_group_lots.transaction_id` links to `position_lots.transaction_id`, NOT to `position_lots.id`

### User Lookup

```python
from src.database.models import User
with get_session(unscoped=True) as session:
    for u in session.query(User).all():
        print(f"{u.id} | {u.email}")
```

Note: Use `get_session` from `src.database.engine`, NOT from `DatabaseManager`. The `DatabaseManager.get_session()` does not accept `unscoped` or `user_id` kwargs.

## Notes

- The dummy `user_credentials` row lets the user access Ledger/Reports/Positions pages
  without completing Tastytrade OAuth. Live quotes won't work but stored data is accessible.
- If the user already has real TT credentials, the `on_conflict_do_nothing` preserves them.
