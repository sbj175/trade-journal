# Tastytrade API Documentation

This document describes the Tastytrade APIs used by OptionLedger and the data available from each.

**SDK:** `tastytrade` (unofficial Python SDK)
**Client:** `src/api/tastytrade_client.py`

---

## API Methods

### 1. `authenticate()` → Session + Accounts

Creates an authenticated session with Tastytrade.

```python
Session(username, password)
Account.get(session)
```

**Returns:** Session object and list of accounts

| Field | Type | Description |
|-------|------|-------------|
| `account_number` | str | Account ID |
| `nickname` | str | Account display name |
| `account_type` | str | Type (Individual, IRA, etc.) |
| `is_closed` | bool | Whether account is closed |
| `day_trader_status` | bool | Day trader flag |

**Used by:** Login flow, sync operations

---

### 2. `get_transactions(days_back, account_number)` → Trade History

Fetches transaction history for a specified date range.

```python
account.get_history(session, start_date, end_date, per_page=250)
```

**Parameters:**
- `days_back`: int (default 30) - Number of days to look back
- `account_number`: Optional[str] - Specific account (all if None)

**Returns per transaction:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique transaction ID |
| `account_number` | str | Associated account |
| `transaction_type` | str | Type (Trade, Receive Deliver, Money Movement, etc.) |
| `transaction_sub_type` | str | Sub-type for additional classification |
| `description` | str | Human-readable description |
| `executed_at` | str (ISO) | Execution timestamp (UTC) |
| `transaction_date` | str (ISO) | Transaction date |
| `action` | str | BUY_TO_OPEN, SELL_TO_CLOSE, etc. |
| `symbol` | str | Security symbol (OCC format for options) |
| `instrument_type` | str | EQUITY, EQUITY_OPTION, FUTURE, etc. |
| `underlying_symbol` | str | For options, the underlying stock |
| `quantity` | float | Number of shares/contracts |
| `price` | float | Price per share/contract |
| `value` | float | Total transaction value |
| `commission` | float | Commission charged |
| `regulatory_fees` | float | SEC/regulatory fees |
| `clearing_fees` | float | Clearing fees |
| `net_value` | float | Net value after all fees |
| `order_id` | str | Associated order ID |
| `is_estimated_fee` | bool | Whether fees are estimated |

**Used by:** Trade sync (`/api/sync-trades`)

**Note:** This is the primary data source for building orders and chains. The application groups transactions by `order_id` to reconstruct orders rather than fetching orders directly.

---

### 3. `get_positions(account_number)` → Current Holdings

Fetches current open positions with real-time market data.

```python
account.get_positions(session, include_marks=True)
```

**Parameters:**
- `account_number`: Optional[str] - Specific account (all if None)

**Returns per position:**

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | str | Security symbol |
| `instrument_type` | str | EQUITY, EQUITY_OPTION, etc. |
| `underlying_symbol` | str | For options, the underlying |
| `quantity` | float | Number of contracts/shares |
| `quantity_direction` | str | 'Long' or 'Short' |
| `close_price` | float | Previous close price |
| `mark_price` | float | Current mark price |
| `mark_value_total` | float | Total position mark value |
| `average_open_price` | float | Cost basis per unit |
| `market_value` | float | Current position value |
| `cost_basis` | float | Total cost basis |
| `realized_day_gain` | float | Realized gain today |
| `realized_today` | float | Total realized P&L today |
| `unrealized_pnl` | float | Unrealized profit/loss |
| `pnl_percent` | float | P&L as percentage |
| `multiplier` | float | Contract multiplier (100 for options, 1 for stock) |
| `expires_at` | str (ISO) | For options, expiration date |
| `strike_price` | float | For options, strike price |
| `option_type` | str | 'C' for call, 'P' for put |

**Used by:** Positions page, sync operations

---

### 4. `get_quotes(symbols)` → Real-Time Market Data

Fetches current market quotes for stocks and options.

```python
from tastytrade.market_data import get_market_data_by_type

# For equities
get_market_data_by_type(session, equities=['AAPL', 'SPY'])

# For options (OCC format)
get_market_data_by_type(session, options=['AAPL  250131C00200000'])
```

**Parameters:**
- `symbols`: List[str] - Symbols to fetch quotes for

**Returns per symbol:**

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | str | Symbol |
| `price` | float | Current mark price |
| `mark` | float | Mark price |
| `bid` | float | Bid price |
| `ask` | float | Ask price |
| `last` | float | Last trade price |
| `change` | float | Change since previous close |
| `changePercent` | float | Change as percentage |
| `volume` | int | Trading volume |
| `prev_close` | float | Previous close price |
| `day_high` | float | Day's high |
| `day_low` | float | Day's low |
| `ivr` | float | Implied Volatility Rank (0-100) |
| `iv` | float | Implied Volatility (%) |
| `iv_percentile` | float | IV percentile |

**Caching:** 30-second TTL per symbol to reduce API calls

**Used by:** WebSocket quotes endpoint (`/ws/quotes`), positions page

---

### 5. `get_account_balances()` → Account Value & Buying Power

Fetches account balance and buying power information.

```python
account.get_balances(session)
```

**Returns per account:**

| Field | Type | Description |
|-------|------|-------------|
| `account_number` | str | Account ID |
| `cash_balance` | float | Available cash |
| `net_liquidating_value` | float | Total account value |
| `equity_buying_power` | float | Buying power for stocks |
| `derivative_buying_power` | float | Buying power for options |
| `day_trading_buying_power` | float | Day trading BP |
| `cash_available_to_withdraw` | float | Withdrawable cash |
| `maintenance_requirement` | float | Margin requirement |
| `pending_cash` | float | Cash pending settlement |
| `long_equity_value` | float | Long positions value |
| `short_equity_value` | float | Short positions value |
| `margin_equity` | float | Margin equity |
| `updated_at` | str (ISO) | When balance was fetched |

**Used by:** Positions page header, sync operations

---

### 6. `get_market_metrics(symbols)` → Volatility Data

Fetches implied volatility and IV rank data.

```python
from tastytrade.metrics import get_market_metrics
get_market_metrics(session, symbols)
```

**Returns per symbol:**

| Field | Type | Description |
|-------|------|-------------|
| `iv` | float | Implied Volatility (%) |
| `ivr` | float | IV Rank (0-100) |
| `iv_percentile` | float | IV percentile |
| `historical_volatility` | float | Historical volatility |

**Note:** Called internally by `get_quotes()` to supplement quote data with volatility metrics.

---

### 7. `get_orders(status)` → Order History

Fetches open orders or order history.

```python
# Live orders
account.get_live_orders(session)

# Order history
account.get_order_history(session, start_date, end_date, per_page=250)
```

**Returns per order:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Order ID |
| `account_number` | str | Account |
| `time_in_force` | str | GTC, Day, etc. |
| `order_type` | str | Limit, Market, etc. |
| `size` | float | Order size |
| `underlying_symbol` | str | Underlying |
| `status` | str | Filled, Open, Cancelled, etc. |
| `price` | float | Limit price |
| `legs` | list | Order legs for multi-leg orders |

**Note:** This method is available but **not actively used**. The application builds orders from transaction data instead, which provides:
- More accurate execution details
- Better handling of assignments/exercises
- Complete historical coverage
- Ability to derive strategy types from actual fills

---

## Streaming API (Fallback)

When the primary market data API fails, the client falls back to streaming quotes:

```python
from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Quote, Trade, Greeks

async with DXLinkStreamer(session) as streamer:
    await streamer.subscribe(Quote, symbols)   # Bid/ask prices
    await streamer.subscribe(Trade, symbols)   # Volume/change data
    await streamer.subscribe(Greeks, symbols)  # IV and Greeks
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        LOGIN                                 │
│  authenticate() → Session + Accounts                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      SYNC TRADES                             │
│  get_transactions(days_back) → Raw transactions             │
│           │                                                  │
│           ▼                                                  │
│  OrderProcessorV2 groups by order_id → Orders → Chains      │
│           │                                                  │
│           ▼                                                  │
│  get_positions() → Current open positions                   │
│  get_account_balances() → Account values & BP               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    REAL-TIME DATA                            │
│  WebSocket /ws/quotes                                        │
│           │                                                  │
│           ▼                                                  │
│  get_quotes(symbols) every 5 seconds                        │
│  (with 30-second cache per symbol)                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Why Transactions Instead of Orders?

The application builds orders from transaction data rather than fetching from the orders API:

1. **Transactions are the source of truth** - They show what actually executed, not just what was ordered
2. **Better historical coverage** - Transaction history is more complete and goes back further
3. **Handles edge cases** - Assignments, exercises, and expirations appear as transactions without traditional "orders"
4. **Strategy detection** - Strategies are derived from the actual legs that executed together
5. **Chain tracking** - Roll relationships are built by matching closing and opening transactions

---

## External Fallbacks

### Yahoo Finance API
Used as a fallback for previous close data when Tastytrade doesn't provide it:

```
GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
```

---

## Configuration

### Quote Caching
- **Duration:** 30 seconds per symbol
- **Purpose:** Reduce API calls during WebSocket streaming
- **Clear Method:** `client.clear_quote_cache()`

### Timezone Handling
- All Tastytrade timestamps are in **UTC**
- Converted to **US/Eastern** for display

### Pagination
- Transaction history: 250 per page (auto-paginated)
- Order history: 250 per page
