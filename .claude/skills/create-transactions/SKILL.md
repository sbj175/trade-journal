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
3. Write a Python script that inserts them via `DatabaseManager.save_raw_transactions()`
4. Run the script, then run a reprocess to update the pipeline

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

After insertion, remind the user to run reprocess via the admin app or:
```
POST /api/reprocess
```

## Notes

- The dummy `user_credentials` row lets the user access Ledger/Reports/Positions pages
  without completing Tastytrade OAuth. Live quotes won't work but stored data is accessible.
- If the user already has real TT credentials, the `on_conflict_do_nothing` preserves them.
