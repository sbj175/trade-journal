#!/usr/bin/env python3
"""Insert synthetic transactions for sbj175+001@gmail.com for UI design session."""
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timedelta
from src.database.engine import init_engine, get_session
init_engine(os.getenv('DATABASE_URL'))

from src.database.db_manager import DatabaseManager
from src.database.tenant import set_current_user_id
from src.database.models import RawTransaction, UserCredential, User, Account, AccountBalance
from src.database.engine import dialect_insert

USER_ID = "2a8092c4-69d0-4629-9a3c-5f1da48ba8c9"
USER_EMAIL = "sajohnson@gmail.com"
USER_NAME = "SA Johnson"

ACCT_MARGIN = "5WZ27378"
ACCT_ROTH = "5WZ28644"
ACCT_TRAD = "5WZ26959"

set_current_user_id(USER_ID)

db = DatabaseManager()
db.initialize_database()

# ── 0. Provision user, accounts, balances, and credentials ──────
# This makes the app think the user is fully connected to Tastytrade
# without needing real API credentials.

# Create or update user row (handles UUID changes from Supabase re-creation)
with get_session(unscoped=True) as session:
    existing_by_id = session.query(User).filter(User.id == USER_ID).first()
    existing_by_email = session.query(User).filter(User.email == USER_EMAIL).first()
    if existing_by_id:
        print(f"User already exists: {existing_by_id.email} ({USER_ID})")
    elif existing_by_email:
        # Email exists with a different UUID — delete the old user via admin first
        print(f"ERROR: {USER_EMAIL} exists with a different UUID ({existing_by_email.id}).")
        print(f"       Delete the old user via admin dashboard, then re-run this script.")
        sys.exit(1)
    else:
        session.add(User(
            id=USER_ID,
            email=USER_EMAIL,
            display_name=USER_NAME,
            auth_provider="supabase",
            is_active=True,
        ))
        print(f"Created user: {USER_EMAIL} ({USER_ID})")

# Create accounts
ACCOUNTS = [
    {"account_number": ACCT_MARGIN, "account_name": "Individual Margin", "account_type": "Margin", "opened_at": "2024-06-15"},
    {"account_number": ACCT_ROTH,   "account_name": "Roth IRA",          "account_type": "Roth IRA", "opened_at": "2024-08-01"},
    {"account_number": ACCT_TRAD,   "account_name": "Traditional IRA",   "account_type": "Traditional IRA", "opened_at": "2024-09-10"},
]

with get_session(user_id=USER_ID) as session:
    for acct in ACCOUNTS:
        stmt = dialect_insert(Account).values(
            user_id=USER_ID,
            **acct,
            is_active=True,
        ).on_conflict_do_nothing(constraint="uq_accounts_number_user")
        session.execute(stmt)
    print(f"Ensured {len(ACCOUNTS)} accounts exist")

# Create account balances (realistic mock values)
BALANCES = [
    {"account_number": ACCT_MARGIN, "cash_balance": 45_230.50, "net_liquidating_value": 128_750.00,
     "margin_equity": 128_750.00, "equity_buying_power": 185_400.00,
     "derivative_buying_power": 185_400.00, "day_trading_buying_power": 370_800.00,
     "maintenance_requirement": 42_300.00},
    {"account_number": ACCT_ROTH, "cash_balance": 22_150.75, "net_liquidating_value": 87_500.00,
     "margin_equity": 87_500.00, "equity_buying_power": 22_150.75,
     "derivative_buying_power": 22_150.75, "day_trading_buying_power": 0.0,
     "maintenance_requirement": 0.0},
    {"account_number": ACCT_TRAD, "cash_balance": 18_900.25, "net_liquidating_value": 65_200.00,
     "margin_equity": 65_200.00, "equity_buying_power": 18_900.25,
     "derivative_buying_power": 18_900.25, "day_trading_buying_power": 0.0,
     "maintenance_requirement": 0.0},
]

with get_session(user_id=USER_ID) as session:
    # Clear old balances for this user, then insert fresh
    session.query(AccountBalance).delete()
    for bal in BALANCES:
        session.add(AccountBalance(user_id=USER_ID, **bal))
    print(f"Inserted {len(BALANCES)} account balances")

# Ensure user_credentials row exists (makes /api/settings/credentials return configured=true)
with get_session(user_id=USER_ID) as session:
    stmt = dialect_insert(UserCredential).values(
        user_id=USER_ID,
        provider="tastytrade",
        encrypted_provider_secret=None,
        encrypted_refresh_token=None,
        is_active=True,
    ).on_conflict_do_nothing(index_elements=["user_id", "provider"])
    session.execute(stmt)
    print("Ensured user_credentials row exists (TT onboarding bypass)")

print("\n✓ User provisioning complete — app will see this user as connected\n")

# Delete existing raw_transactions for this user
with get_session(user_id=USER_ID) as session:
    deleted = session.query(RawTransaction).delete()
    print(f"Deleted {deleted} existing raw_transactions")

# ── Helpers ──────────────────────────────────────────────────────

_txn_counter = 0
_ord_counter = 0

def tid():
    global _txn_counter
    _txn_counter += 1
    return f"synth-{_txn_counter:04d}"

def oid():
    global _ord_counter
    _ord_counter += 1
    return f"synth-ord-{_ord_counter:04d}"

def occ(underlying, exp_date, call_put, strike):
    """Build OCC symbol: 'AAPL  250321C00170000'"""
    sym = underlying.ljust(6)
    exp = exp_date.strftime("%y%m%d")
    cp = "C" if call_put == "C" else "P"
    st = f"{int(strike * 1000):08d}"
    return f"{sym}{exp}{cp}{st}"

def dt(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, 0)

def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S+00:00")

def isodate(d):
    return d.strftime("%Y-%m-%d")

def txn(acct, order_id, symbol, underlying, action, sub_type, qty, price, executed, inst_type="EQUITY_OPTION", desc=None):
    multiplier = 100 if inst_type == "EQUITY_OPTION" else 1
    # For sells, value is positive; for buys, value is negative
    if action and "SELL" in action:
        value = round(abs(price) * qty * multiplier, 2)
    elif action and "BUY" in action:
        value = round(-abs(price) * qty * multiplier, 2)
    else:
        value = 0.0
    return {
        "id": tid(),
        "account_number": acct,
        "order_id": order_id,
        "symbol": symbol if inst_type == "EQUITY" else symbol,
        "underlying_symbol": underlying,
        "action": action,
        "quantity": float(qty),
        "price": float(price),
        "executed_at": iso(executed),
        "transaction_date": isodate(executed),
        "instrument_type": inst_type,
        "transaction_type": "Trade",
        "transaction_sub_type": sub_type,
        "description": desc or f"{sub_type} {qty} {symbol}",
        "value": value,
        "net_value": value,
        "commission": 0.0,
        "regulatory_fees": 0.0,
        "clearing_fees": 0.0,
        "is_estimated_fee": False,
    }

transactions = []

# ═══════════════════════════════════════════════════════════════════
# MARGIN ACCOUNT — Active trading
# ═══════════════════════════════════════════════════════════════════

# ── 1. NVDA Bull Put Spread (WINNER — closed) ──
# Opened Dec 5 2025, closed Dec 19
o = oid()
exp = dt(2026, 1, 17)
transactions += [
    txn(ACCT_MARGIN, o, occ("NVDA", exp, "P", 125), "NVDA", "SELL_TO_OPEN", "Sell to Open", 5, 3.45, dt(2025, 12, 5, 10, 15)),
    txn(ACCT_MARGIN, o, occ("NVDA", exp, "P", 120), "NVDA", "BUY_TO_OPEN", "Buy to Open", 5, 1.80, dt(2025, 12, 5, 10, 15)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("NVDA", exp, "P", 125), "NVDA", "BUY_TO_CLOSE", "Buy to Close", 5, 0.85, dt(2025, 12, 19, 14, 30)),
    txn(ACCT_MARGIN, o2, occ("NVDA", exp, "P", 120), "NVDA", "SELL_TO_CLOSE", "Sell to Close", 5, 0.20, dt(2025, 12, 19, 14, 30)),
]

# ── 2. AMZN Bear Call Spread (WINNER — expired worthless) ──
o = oid()
exp = dt(2026, 1, 17)
transactions += [
    txn(ACCT_MARGIN, o, occ("AMZN", exp, "C", 230), "AMZN", "SELL_TO_OPEN", "Sell to Open", 3, 4.20, dt(2025, 12, 10, 9, 45)),
    txn(ACCT_MARGIN, o, occ("AMZN", exp, "C", 240), "AMZN", "BUY_TO_OPEN", "Buy to Open", 3, 1.95, dt(2025, 12, 10, 9, 45)),
]
# Expired worthless
transactions += [
    txn(ACCT_MARGIN, None, occ("AMZN", exp, "C", 230), "AMZN", None, "Expiration", 3, 0, exp, desc="Expiration of AMZN 01/17/26 Call 230.00"),
    txn(ACCT_MARGIN, None, occ("AMZN", exp, "C", 240), "AMZN", None, "Expiration", 3, 0, exp, desc="Expiration of AMZN 01/17/26 Call 240.00"),
]

# ── 3. TSLA Iron Condor (LOSER — closed for loss) ──
o = oid()
exp = dt(2026, 2, 21)
transactions += [
    txn(ACCT_MARGIN, o, occ("TSLA", exp, "P", 320), "TSLA", "SELL_TO_OPEN", "Sell to Open", 2, 5.60, dt(2026, 1, 6, 10, 0)),
    txn(ACCT_MARGIN, o, occ("TSLA", exp, "P", 300), "TSLA", "BUY_TO_OPEN", "Buy to Open", 2, 2.80, dt(2026, 1, 6, 10, 0)),
    txn(ACCT_MARGIN, o, occ("TSLA", exp, "C", 420), "TSLA", "SELL_TO_OPEN", "Sell to Open", 2, 6.10, dt(2026, 1, 6, 10, 0)),
    txn(ACCT_MARGIN, o, occ("TSLA", exp, "C", 440), "TSLA", "BUY_TO_OPEN", "Buy to Open", 2, 3.25, dt(2026, 1, 6, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("TSLA", exp, "P", 320), "TSLA", "BUY_TO_CLOSE", "Buy to Close", 2, 12.40, dt(2026, 1, 27, 11, 0)),
    txn(ACCT_MARGIN, o2, occ("TSLA", exp, "P", 300), "TSLA", "SELL_TO_CLOSE", "Sell to Close", 2, 5.10, dt(2026, 1, 27, 11, 0)),
    txn(ACCT_MARGIN, o2, occ("TSLA", exp, "C", 420), "TSLA", "BUY_TO_CLOSE", "Buy to Close", 2, 0.45, dt(2026, 1, 27, 11, 0)),
    txn(ACCT_MARGIN, o2, occ("TSLA", exp, "C", 440), "TSLA", "SELL_TO_CLOSE", "Sell to Close", 2, 0.10, dt(2026, 1, 27, 11, 0)),
]

# ── 4. SPY Put Debit Spread (WINNER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_MARGIN, o, occ("SPY", exp, "P", 560), "SPY", "BUY_TO_OPEN", "Buy to Open", 10, 8.75, dt(2026, 1, 15, 10, 30)),
    txn(ACCT_MARGIN, o, occ("SPY", exp, "P", 545), "SPY", "SELL_TO_OPEN", "Sell to Open", 10, 4.20, dt(2026, 1, 15, 10, 30)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("SPY", exp, "P", 560), "SPY", "SELL_TO_CLOSE", "Sell to Close", 10, 14.60, dt(2026, 2, 20, 15, 0)),
    txn(ACCT_MARGIN, o2, occ("SPY", exp, "P", 545), "SPY", "BUY_TO_CLOSE", "Buy to Close", 10, 6.30, dt(2026, 2, 20, 15, 0)),
]

# ── 5. COIN Call Debit Spread (LOSER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_MARGIN, o, occ("COIN", exp, "C", 280), "COIN", "BUY_TO_OPEN", "Buy to Open", 4, 12.50, dt(2026, 1, 22, 11, 15)),
    txn(ACCT_MARGIN, o, occ("COIN", exp, "C", 300), "COIN", "SELL_TO_OPEN", "Sell to Open", 4, 6.80, dt(2026, 1, 22, 11, 15)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("COIN", exp, "C", 280), "COIN", "SELL_TO_CLOSE", "Sell to Close", 4, 3.10, dt(2026, 2, 28, 10, 45)),
    txn(ACCT_MARGIN, o2, occ("COIN", exp, "C", 300), "COIN", "BUY_TO_CLOSE", "Buy to Close", 4, 1.05, dt(2026, 2, 28, 10, 45)),
]

# ── 6. PLTR Cash-Secured Put (WINNER — expired) ──
o = oid()
exp = dt(2026, 2, 21)
transactions += [
    txn(ACCT_MARGIN, o, occ("PLTR", exp, "P", 85), "PLTR", "SELL_TO_OPEN", "Sell to Open", 3, 4.15, dt(2026, 1, 10, 13, 0)),
]
transactions += [
    txn(ACCT_MARGIN, None, occ("PLTR", exp, "P", 85), "PLTR", None, "Expiration", 3, 0, exp, desc="Expiration of PLTR 02/21/26 Put 85.00"),
]

# ── 7. META Naked Put ROLLED (opened → rolled → still open) ──
# Original: Feb exp
o = oid()
exp1 = dt(2026, 2, 21)
transactions += [
    txn(ACCT_MARGIN, o, occ("META", exp1, "P", 580), "META", "SELL_TO_OPEN", "Sell to Open", 2, 8.90, dt(2026, 1, 8, 10, 0)),
]
# Roll to March (close Feb, open Mar in same order)
o_roll = oid()
exp2 = dt(2026, 3, 20)
transactions += [
    txn(ACCT_MARGIN, o_roll, occ("META", exp1, "P", 580), "META", "BUY_TO_CLOSE", "Buy to Close", 2, 3.20, dt(2026, 2, 14, 10, 30)),
    txn(ACCT_MARGIN, o_roll, occ("META", exp2, "P", 575), "META", "SELL_TO_OPEN", "Sell to Open", 2, 9.50, dt(2026, 2, 14, 10, 30)),
]
# Roll again to April (close Mar, open Apr)
o_roll2 = oid()
exp3 = dt(2026, 4, 17)
transactions += [
    txn(ACCT_MARGIN, o_roll2, occ("META", exp2, "P", 575), "META", "BUY_TO_CLOSE", "Buy to Close", 2, 4.10, dt(2026, 3, 12, 11, 0)),
    txn(ACCT_MARGIN, o_roll2, occ("META", exp3, "P", 570), "META", "SELL_TO_OPEN", "Sell to Open", 2, 10.80, dt(2026, 3, 12, 11, 0)),
]

# ── 8. GOOGL Strangle (WINNER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_MARGIN, o, occ("GOOGL", exp, "P", 165), "GOOGL", "SELL_TO_OPEN", "Sell to Open", 3, 3.80, dt(2026, 1, 28, 9, 35)),
    txn(ACCT_MARGIN, o, occ("GOOGL", exp, "C", 195), "GOOGL", "SELL_TO_OPEN", "Sell to Open", 3, 2.95, dt(2026, 1, 28, 9, 35)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("GOOGL", exp, "P", 165), "GOOGL", "BUY_TO_CLOSE", "Buy to Close", 3, 0.60, dt(2026, 3, 5, 14, 0)),
    txn(ACCT_MARGIN, o2, occ("GOOGL", exp, "C", 195), "GOOGL", "BUY_TO_CLOSE", "Buy to Close", 3, 0.35, dt(2026, 3, 5, 14, 0)),
]

# ── 9. MARA Long Call (LOSER — closed) ──
o = oid()
exp = dt(2026, 4, 17)
transactions += [
    txn(ACCT_MARGIN, o, occ("MARA", exp, "C", 25), "MARA", "BUY_TO_OPEN", "Buy to Open", 8, 3.60, dt(2026, 2, 3, 10, 20)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("MARA", exp, "C", 25), "MARA", "SELL_TO_CLOSE", "Sell to Close", 8, 1.15, dt(2026, 3, 10, 11, 45)),
]

# ── 10. QQQ Bear Put Spread (STILL OPEN) ──
o = oid()
exp = dt(2026, 5, 15)
transactions += [
    txn(ACCT_MARGIN, o, occ("QQQ", exp, "P", 480), "QQQ", "BUY_TO_OPEN", "Buy to Open", 5, 11.20, dt(2026, 3, 18, 10, 0)),
    txn(ACCT_MARGIN, o, occ("QQQ", exp, "P", 460), "QQQ", "SELL_TO_OPEN", "Sell to Open", 5, 5.85, dt(2026, 3, 18, 10, 0)),
]

# ── 11. EQUITIES — AAPL buy and partial sell ──
o = oid()
transactions += [
    txn(ACCT_MARGIN, o, "AAPL", "AAPL", "BUY_TO_OPEN", "Buy to Open", 200, 228.50, dt(2025, 12, 2, 10, 0), inst_type="EQUITY"),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, "AAPL", "AAPL", "SELL_TO_CLOSE", "Sell to Close", 100, 241.75, dt(2026, 1, 14, 14, 30), inst_type="EQUITY"),
]

# ── 12. EQUITIES — MSFT round trip ──
o = oid()
transactions += [
    txn(ACCT_MARGIN, o, "MSFT", "MSFT", "BUY_TO_OPEN", "Buy to Open", 50, 415.20, dt(2026, 1, 7, 10, 0), inst_type="EQUITY"),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, "MSFT", "MSFT", "SELL_TO_CLOSE", "Sell to Close", 50, 428.90, dt(2026, 2, 11, 15, 0), inst_type="EQUITY"),
]

# ── 13. EQUITIES — AMD buy (STILL OPEN) ──
o = oid()
transactions += [
    txn(ACCT_MARGIN, o, "AMD", "AMD", "BUY_TO_OPEN", "Buy to Open", 150, 118.30, dt(2026, 2, 24, 10, 15), inst_type="EQUITY"),
]

# ═══════════════════════════════════════════════════════════════════
# ROTH IRA — More conservative / premium selling
# ═══════════════════════════════════════════════════════════════════

# ── 14. JPM Bull Put Spread (WINNER — expired) ──
o = oid()
exp = dt(2026, 1, 17)
transactions += [
    txn(ACCT_ROTH, o, occ("JPM", exp, "P", 240), "JPM", "SELL_TO_OPEN", "Sell to Open", 4, 5.10, dt(2025, 12, 12, 10, 0)),
    txn(ACCT_ROTH, o, occ("JPM", exp, "P", 230), "JPM", "BUY_TO_OPEN", "Buy to Open", 4, 2.65, dt(2025, 12, 12, 10, 0)),
]
transactions += [
    txn(ACCT_ROTH, None, occ("JPM", exp, "P", 240), "JPM", None, "Expiration", 4, 0, exp, desc="Expiration of JPM 01/17/26 Put 240.00"),
    txn(ACCT_ROTH, None, occ("JPM", exp, "P", 230), "JPM", None, "Expiration", 4, 0, exp, desc="Expiration of JPM 01/17/26 Put 230.00"),
]

# ── 15. COST Covered Call — bought shares + sold call ──
o = oid()
transactions += [
    txn(ACCT_ROTH, o, "COST", "COST", "BUY_TO_OPEN", "Buy to Open", 100, 935.40, dt(2026, 1, 13, 10, 0), inst_type="EQUITY"),
]
o2 = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_ROTH, o2, occ("COST", exp, "C", 980), "COST", "SELL_TO_OPEN", "Sell to Open", 1, 18.50, dt(2026, 1, 13, 10, 5)),
]
# Call expired worthless
transactions += [
    txn(ACCT_ROTH, None, occ("COST", exp, "C", 980), "COST", None, "Expiration", 1, 0, exp, desc="Expiration of COST 03/20/26 Call 980.00"),
]

# ── 16. UNH Bull Put Spread with ROLL ──
o = oid()
exp1 = dt(2026, 2, 21)
transactions += [
    txn(ACCT_ROTH, o, occ("UNH", exp1, "P", 500), "UNH", "SELL_TO_OPEN", "Sell to Open", 2, 7.20, dt(2026, 1, 15, 10, 0)),
    txn(ACCT_ROTH, o, occ("UNH", exp1, "P", 480), "UNH", "BUY_TO_OPEN", "Buy to Open", 2, 3.40, dt(2026, 1, 15, 10, 0)),
]
# Roll down and out
o_roll = oid()
exp2 = dt(2026, 3, 20)
transactions += [
    txn(ACCT_ROTH, o_roll, occ("UNH", exp1, "P", 500), "UNH", "BUY_TO_CLOSE", "Buy to Close", 2, 9.80, dt(2026, 2, 10, 11, 30)),
    txn(ACCT_ROTH, o_roll, occ("UNH", exp1, "P", 480), "UNH", "SELL_TO_CLOSE", "Sell to Close", 2, 4.60, dt(2026, 2, 10, 11, 30)),
    txn(ACCT_ROTH, o_roll, occ("UNH", exp2, "P", 490), "UNH", "SELL_TO_OPEN", "Sell to Open", 2, 10.50, dt(2026, 2, 10, 11, 30)),
    txn(ACCT_ROTH, o_roll, occ("UNH", exp2, "P", 470), "UNH", "BUY_TO_OPEN", "Buy to Open", 2, 4.90, dt(2026, 2, 10, 11, 30)),
]
# Roll again to May (Mar 20 is past today)
o_roll2 = oid()
exp3 = dt(2026, 5, 15)
transactions += [
    txn(ACCT_ROTH, o_roll2, occ("UNH", exp2, "P", 490), "UNH", "BUY_TO_CLOSE", "Buy to Close", 2, 6.30, dt(2026, 3, 14, 10, 30)),
    txn(ACCT_ROTH, o_roll2, occ("UNH", exp2, "P", 470), "UNH", "SELL_TO_CLOSE", "Sell to Close", 2, 2.10, dt(2026, 3, 14, 10, 30)),
    txn(ACCT_ROTH, o_roll2, occ("UNH", exp3, "P", 485), "UNH", "SELL_TO_OPEN", "Sell to Open", 2, 9.80, dt(2026, 3, 14, 10, 30)),
    txn(ACCT_ROTH, o_roll2, occ("UNH", exp3, "P", 465), "UNH", "BUY_TO_OPEN", "Buy to Open", 2, 4.20, dt(2026, 3, 14, 10, 30)),
]
# Now open with May expiry

# ── 17. LLY Naked Put (ASSIGNED) ──
o = oid()
exp = dt(2026, 2, 21)
transactions += [
    txn(ACCT_ROTH, o, occ("LLY", exp, "P", 800), "LLY", "SELL_TO_OPEN", "Sell to Open", 1, 15.30, dt(2026, 1, 21, 10, 0)),
]
# Assigned
transactions += [
    txn(ACCT_ROTH, None, occ("LLY", exp, "P", 800), "LLY", None, "Assignment", 1, 0, exp, desc="Assignment of LLY 02/21/26 Put 800.00"),
    txn(ACCT_ROTH, None, "LLY", "LLY", "BUY_TO_OPEN", "Buy to Open", 100, 800.00, exp, inst_type="EQUITY", desc="Assignment: Bought 100 LLY @ 800.00"),
]

# ── 18. GLD Long Put (hedge — WINNER) ──
o = oid()
exp = dt(2026, 4, 17)
transactions += [
    txn(ACCT_ROTH, o, occ("GLD", exp, "P", 280), "GLD", "BUY_TO_OPEN", "Buy to Open", 5, 6.40, dt(2026, 2, 5, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_ROTH, o2, occ("GLD", exp, "P", 280), "GLD", "SELL_TO_CLOSE", "Sell to Close", 5, 11.90, dt(2026, 3, 15, 14, 20)),
]

# ── 19. V Bear Call Spread (WINNER — closed early) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_ROTH, o, occ("V", exp, "C", 340), "V", "SELL_TO_OPEN", "Sell to Open", 3, 5.70, dt(2026, 2, 18, 10, 0)),
    txn(ACCT_ROTH, o, occ("V", exp, "C", 355), "V", "BUY_TO_OPEN", "Buy to Open", 3, 2.30, dt(2026, 2, 18, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_ROTH, o2, occ("V", exp, "C", 340), "V", "BUY_TO_CLOSE", "Buy to Close", 3, 1.10, dt(2026, 3, 8, 15, 30)),
    txn(ACCT_ROTH, o2, occ("V", exp, "C", 355), "V", "SELL_TO_CLOSE", "Sell to Close", 3, 0.25, dt(2026, 3, 8, 15, 30)),
]

# ═══════════════════════════════════════════════════════════════════
# TRADITIONAL IRA — Mix
# ═══════════════════════════════════════════════════════════════════

# ── 20. XLE Iron Condor (WINNER — expired) ──
o = oid()
exp = dt(2026, 2, 21)
transactions += [
    txn(ACCT_TRAD, o, occ("XLE", exp, "P", 82), "XLE", "SELL_TO_OPEN", "Sell to Open", 6, 1.85, dt(2026, 1, 5, 10, 0)),
    txn(ACCT_TRAD, o, occ("XLE", exp, "P", 78), "XLE", "BUY_TO_OPEN", "Buy to Open", 6, 0.90, dt(2026, 1, 5, 10, 0)),
    txn(ACCT_TRAD, o, occ("XLE", exp, "C", 96), "XLE", "SELL_TO_OPEN", "Sell to Open", 6, 1.60, dt(2026, 1, 5, 10, 0)),
    txn(ACCT_TRAD, o, occ("XLE", exp, "C", 100), "XLE", "BUY_TO_OPEN", "Buy to Open", 6, 0.75, dt(2026, 1, 5, 10, 0)),
]
transactions += [
    txn(ACCT_TRAD, None, occ("XLE", exp, "P", 82), "XLE", None, "Expiration", 6, 0, exp, desc="Expiration of XLE 02/21/26 Put 82.00"),
    txn(ACCT_TRAD, None, occ("XLE", exp, "P", 78), "XLE", None, "Expiration", 6, 0, exp, desc="Expiration of XLE 02/21/26 Put 78.00"),
    txn(ACCT_TRAD, None, occ("XLE", exp, "C", 96), "XLE", None, "Expiration", 6, 0, exp, desc="Expiration of XLE 02/21/26 Call 96.00"),
    txn(ACCT_TRAD, None, occ("XLE", exp, "C", 100), "XLE", None, "Expiration", 6, 0, exp, desc="Expiration of XLE 02/21/26 Call 100.00"),
]

# ── 21. CAT Bull Call Spread (LOSER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_TRAD, o, occ("CAT", exp, "C", 370), "CAT", "BUY_TO_OPEN", "Buy to Open", 2, 15.80, dt(2026, 1, 20, 10, 0)),
    txn(ACCT_TRAD, o, occ("CAT", exp, "C", 395), "CAT", "SELL_TO_OPEN", "Sell to Open", 2, 6.40, dt(2026, 1, 20, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_TRAD, o2, occ("CAT", exp, "C", 370), "CAT", "SELL_TO_CLOSE", "Sell to Close", 2, 5.20, dt(2026, 3, 1, 11, 0)),
    txn(ACCT_TRAD, o2, occ("CAT", exp, "C", 395), "CAT", "BUY_TO_CLOSE", "Buy to Close", 2, 1.10, dt(2026, 3, 1, 11, 0)),
]

# ── 22. IWM Put Credit Spread with ROLL (still open) ──
o = oid()
exp1 = dt(2026, 2, 21)
transactions += [
    txn(ACCT_TRAD, o, occ("IWM", exp1, "P", 210), "IWM", "SELL_TO_OPEN", "Sell to Open", 7, 3.30, dt(2026, 1, 12, 10, 0)),
    txn(ACCT_TRAD, o, occ("IWM", exp1, "P", 200), "IWM", "BUY_TO_OPEN", "Buy to Open", 7, 1.45, dt(2026, 1, 12, 10, 0)),
]
# Roll to March
o_roll = oid()
exp2 = dt(2026, 3, 20)
transactions += [
    txn(ACCT_TRAD, o_roll, occ("IWM", exp1, "P", 210), "IWM", "BUY_TO_CLOSE", "Buy to Close", 7, 5.80, dt(2026, 2, 12, 10, 0)),
    txn(ACCT_TRAD, o_roll, occ("IWM", exp1, "P", 200), "IWM", "SELL_TO_CLOSE", "Sell to Close", 7, 2.60, dt(2026, 2, 12, 10, 0)),
    txn(ACCT_TRAD, o_roll, occ("IWM", exp2, "P", 205), "IWM", "SELL_TO_OPEN", "Sell to Open", 7, 5.10, dt(2026, 2, 12, 10, 0)),
    txn(ACCT_TRAD, o_roll, occ("IWM", exp2, "P", 195), "IWM", "BUY_TO_OPEN", "Buy to Open", 7, 2.20, dt(2026, 2, 12, 10, 0)),
]
# Roll again to April
o_roll2 = oid()
exp3 = dt(2026, 4, 17)
transactions += [
    txn(ACCT_TRAD, o_roll2, occ("IWM", exp2, "P", 205), "IWM", "BUY_TO_CLOSE", "Buy to Close", 7, 4.50, dt(2026, 3, 13, 10, 0)),
    txn(ACCT_TRAD, o_roll2, occ("IWM", exp2, "P", 195), "IWM", "SELL_TO_CLOSE", "Sell to Close", 7, 1.80, dt(2026, 3, 13, 10, 0)),
    txn(ACCT_TRAD, o_roll2, occ("IWM", exp3, "P", 200), "IWM", "SELL_TO_OPEN", "Sell to Open", 7, 4.80, dt(2026, 3, 13, 10, 0)),
    txn(ACCT_TRAD, o_roll2, occ("IWM", exp3, "P", 190), "IWM", "BUY_TO_OPEN", "Buy to Open", 7, 2.10, dt(2026, 3, 13, 10, 0)),
]

# ── 23. DKNG Long Call (WINNER — closed) ──
o = oid()
exp = dt(2026, 4, 17)
transactions += [
    txn(ACCT_TRAD, o, occ("DKNG", exp, "C", 45), "DKNG", "BUY_TO_OPEN", "Buy to Open", 10, 2.85, dt(2026, 2, 7, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_TRAD, o2, occ("DKNG", exp, "C", 45), "DKNG", "SELL_TO_CLOSE", "Sell to Close", 10, 5.40, dt(2026, 3, 20, 14, 0)),
]

# ── 24. XOM Covered Call (shares + call, still open) ──
o = oid()
transactions += [
    txn(ACCT_TRAD, o, "XOM", "XOM", "BUY_TO_OPEN", "Buy to Open", 200, 108.60, dt(2026, 1, 2, 10, 0), inst_type="EQUITY"),
]
o2 = oid()
exp = dt(2026, 5, 15)
transactions += [
    txn(ACCT_TRAD, o2, occ("XOM", exp, "C", 120), "XOM", "SELL_TO_OPEN", "Sell to Open", 2, 3.40, dt(2026, 3, 25, 10, 0)),
]

# ── 25. SOFI Put Credit Spread (WINNER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_TRAD, o, occ("SOFI", exp, "P", 14), "SOFI", "SELL_TO_OPEN", "Sell to Open", 15, 0.85, dt(2026, 2, 14, 10, 0)),
    txn(ACCT_TRAD, o, occ("SOFI", exp, "P", 12), "SOFI", "BUY_TO_OPEN", "Buy to Open", 15, 0.35, dt(2026, 2, 14, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_TRAD, o2, occ("SOFI", exp, "P", 14), "SOFI", "BUY_TO_CLOSE", "Buy to Close", 15, 0.15, dt(2026, 3, 14, 15, 0)),
    txn(ACCT_TRAD, o2, occ("SOFI", exp, "P", 12), "SOFI", "SELL_TO_CLOSE", "Sell to Close", 15, 0.05, dt(2026, 3, 14, 15, 0)),
]

# ── 26. BA Long Put (hedge — LOSER) ──
o = oid()
exp = dt(2026, 4, 17)
transactions += [
    txn(ACCT_TRAD, o, occ("BA", exp, "P", 170), "BA", "BUY_TO_OPEN", "Buy to Open", 3, 7.80, dt(2026, 2, 20, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_TRAD, o2, occ("BA", exp, "P", 170), "BA", "SELL_TO_CLOSE", "Sell to Close", 3, 2.90, dt(2026, 3, 28, 11, 30)),
]

# ── 27. AVGO Put Credit Spread (STILL OPEN) ──
o = oid()
exp = dt(2026, 5, 15)
transactions += [
    txn(ACCT_MARGIN, o, occ("AVGO", exp, "P", 195), "AVGO", "SELL_TO_OPEN", "Sell to Open", 3, 8.40, dt(2026, 3, 24, 10, 0)),
    txn(ACCT_MARGIN, o, occ("AVGO", exp, "P", 180), "AVGO", "BUY_TO_OPEN", "Buy to Open", 3, 4.15, dt(2026, 3, 24, 10, 0)),
]

# ── 28. NFLX Jade Lizard (short put + bear call spread, WINNER — closed) ──
o = oid()
exp = dt(2026, 3, 20)
transactions += [
    txn(ACCT_MARGIN, o, occ("NFLX", exp, "P", 950), "NFLX", "SELL_TO_OPEN", "Sell to Open", 1, 18.50, dt(2026, 2, 6, 10, 0)),
    txn(ACCT_MARGIN, o, occ("NFLX", exp, "C", 1050), "NFLX", "SELL_TO_OPEN", "Sell to Open", 1, 12.30, dt(2026, 2, 6, 10, 0)),
    txn(ACCT_MARGIN, o, occ("NFLX", exp, "C", 1080), "NFLX", "BUY_TO_OPEN", "Buy to Open", 1, 6.90, dt(2026, 2, 6, 10, 0)),
]
o2 = oid()
transactions += [
    txn(ACCT_MARGIN, o2, occ("NFLX", exp, "P", 950), "NFLX", "BUY_TO_CLOSE", "Buy to Close", 1, 3.40, dt(2026, 3, 12, 14, 0)),
    txn(ACCT_MARGIN, o2, occ("NFLX", exp, "C", 1050), "NFLX", "BUY_TO_CLOSE", "Buy to Close", 1, 1.20, dt(2026, 3, 12, 14, 0)),
    txn(ACCT_MARGIN, o2, occ("NFLX", exp, "C", 1080), "NFLX", "SELL_TO_CLOSE", "Sell to Close", 1, 0.30, dt(2026, 3, 12, 14, 0)),
]

# ── 29. IBIT Bull Call Spread (STILL OPEN) ──
o = oid()
exp = dt(2026, 6, 19)
transactions += [
    txn(ACCT_MARGIN, o, occ("IBIT", exp, "C", 55), "IBIT", "BUY_TO_OPEN", "Buy to Open", 10, 4.80, dt(2026, 3, 28, 10, 0)),
    txn(ACCT_MARGIN, o, occ("IBIT", exp, "C", 65), "IBIT", "SELL_TO_OPEN", "Sell to Open", 10, 2.15, dt(2026, 3, 28, 10, 0)),
]

# ── 30. HD Equity (round trip — WINNER) ──
o = oid()
transactions += [
    txn(ACCT_ROTH, o, "HD", "HD", "BUY_TO_OPEN", "Buy to Open", 50, 378.90, dt(2026, 1, 27, 10, 0), inst_type="EQUITY"),
]
o2 = oid()
transactions += [
    txn(ACCT_ROTH, o2, "HD", "HD", "SELL_TO_CLOSE", "Sell to Close", 50, 402.15, dt(2026, 3, 3, 14, 30), inst_type="EQUITY"),
]

print(f"\nGenerated {len(transactions)} transactions across {len(set(t['underlying_symbol'] for t in transactions))} underlyings")
print(f"Accounts: {', '.join(sorted(set(t['account_number'] for t in transactions)))}")

# ── Insert ──
saved, symbols = db.save_raw_transactions(transactions)
print(f"Saved {saved} transactions, symbols: {sorted(symbols)}")

# ── Reprocess pipeline ──
from src.pipeline.orchestrator import reprocess
from src.models.lot_manager import LotManager

lot_manager = LotManager(db)
raw_transactions = db.get_raw_transactions()
print(f"\nReprocessing {len(raw_transactions)} raw transactions...")

result = reprocess(db, lot_manager, raw_transactions)
print(f"Orders assembled: {result.orders_assembled}")
print(f"Groups processed: {result.groups_processed}")
print(f"Equity lots netted: {result.equity_lots_netted}")
print(f"P&L events populated: {result.pnl_events_populated}")

# ── Seed quote cache (removes spinners — no live Tastytrade connection needed) ──
import random
from src.database.models import QuoteCache

# Realistic prices for underlying symbols (approximate as of early 2026)
UNDERLYING_PRICES = {
    "AAPL": 232.50, "AMD": 124.80, "AMZN": 218.40, "AVGO": 202.30,
    "BA": 178.60, "CAT": 365.20, "COIN": 265.40, "COST": 952.10,
    "DKNG": 48.75, "GLD": 285.30, "GOOGL": 182.90, "HD": 395.60,
    "IBIT": 58.20, "IWM": 203.50, "JPM": 252.80, "LLY": 785.40,
    "MARA": 22.30, "META": 585.70, "MSFT": 425.60, "NFLX": 1015.20,
    "NVDA": 138.90, "PLTR": 92.40, "QQQ": 475.80, "SOFI": 15.20,
    "SPY": 558.30, "TSLA": 355.40, "UNH": 488.50, "V": 332.70,
    "XLE": 89.40, "XOM": 112.80,
}

now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

with get_session(unscoped=True) as session:
    # Seed underlying quotes
    for sym, price in UNDERLYING_PRICES.items():
        change = round(random.uniform(-2.5, 2.5), 2)
        prev_close = round(price - change, 2)
        change_pct = round((change / prev_close) * 100, 2)
        stmt = dialect_insert(QuoteCache).values(
            symbol=sym,
            mark=price,
            bid=round(price - 0.05, 2),
            ask=round(price + 0.05, 2),
            last=price,
            change=change,
            change_percent=change_pct,
            volume=random.randint(500_000, 15_000_000),
            prev_close=prev_close,
            day_high=round(price + random.uniform(0.5, 3.0), 2),
            day_low=round(price - random.uniform(0.5, 3.0), 2),
            iv=round(random.uniform(0.18, 0.55), 4),
            ivr=round(random.uniform(15, 65), 1),
            iv_percentile=round(random.uniform(20, 70), 1),
            updated_at=now_str,
        ).on_conflict_do_update(
            index_elements=["symbol"],
            set_={"mark": price, "bid": round(price - 0.05, 2), "ask": round(price + 0.05, 2),
                   "last": price, "change": change, "change_percent": change_pct, "updated_at": now_str},
        )
        session.execute(stmt)

    # Seed option quotes for OPEN positions only
    # Collect open option symbols from transactions
    open_option_symbols = set()
    for t in transactions:
        if t["instrument_type"] == "EQUITY_OPTION":
            open_option_symbols.add(t["symbol"])

    for sym in open_option_symbols:
        # Generate a plausible option mark price
        mark = round(random.uniform(0.30, 12.00), 2)
        spread = round(random.uniform(0.03, 0.15), 2)
        stmt = dialect_insert(QuoteCache).values(
            symbol=sym,
            mark=mark,
            bid=round(mark - spread, 2),
            ask=round(mark + spread, 2),
            last=mark,
            change=round(random.uniform(-1.0, 1.0), 2),
            change_percent=round(random.uniform(-15, 15), 2),
            volume=random.randint(50, 5000),
            prev_close=round(mark + random.uniform(-0.5, 0.5), 2),
            day_high=round(mark + random.uniform(0.1, 1.0), 2),
            day_low=round(mark - random.uniform(0.1, 0.5), 2),
            iv=round(random.uniform(0.20, 0.80), 4),
            updated_at=now_str,
        ).on_conflict_do_update(
            index_elements=["symbol"],
            set_={"mark": mark, "bid": round(mark - spread, 2), "ask": round(mark + spread, 2),
                   "last": mark, "updated_at": now_str},
        )
        session.execute(stmt)

    print(f"Seeded quote cache: {len(UNDERLYING_PRICES)} underlyings + {len(open_option_symbols)} options")

# ── Verify ──
from sqlalchemy import text

with get_session(user_id=USER_ID) as session:
    print("\n=== GROUPS ===")
    groups = session.execute(text(
        "SELECT group_id, underlying, strategy_label, status, opening_date "
        "FROM position_groups WHERE user_id = :uid ORDER BY opening_date"
    ), {"uid": USER_ID}).fetchall()
    for g in groups:
        print(f"  {g.underlying:6s}  strategy={g.strategy_label:30s}  status={g.status:8s}  opened={g.opening_date}")

    print(f"\nTotal groups: {len(groups)}")
    open_groups = [g for g in groups if g.status == 'open']
    closed_groups = [g for g in groups if g.status == 'closed']
    print(f"Open: {len(open_groups)}, Closed: {len(closed_groups)}")
