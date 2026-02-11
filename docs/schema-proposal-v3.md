# Schema Proposal V3: Lot-Based Position Tracking

## Overview

This proposal addresses four critical gaps in the current data model:

1. **Overlapping positions** - Multiple independent trades on the same symbol get merged
2. **Vertical spreads** - Legs need explicit linkage for proper P&L and roll tracking
3. **Early assignment** - Stock received from assignment has no lineage to original option
4. **Partial closures** - No granular tracking of which lots were closed

## Core Concept: Lots vs Inventory

The current `positions_inventory` table uses `UNIQUE(account_number, symbol)`, which merges all positions on the same symbol. This is fundamentally incompatible with tracking independent trades.

**Solution**: Replace inventory-based tracking with **lot-based tracking**. Each opening transaction creates a distinct lot. Closings consume specific lots (FIFO by default).

---

## New Tables

### 1. `position_lots` - Core Position Tracking

Each opening transaction creates a lot. This is the source of truth for open positions.

```sql
CREATE TABLE position_lots (
    lot_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    account_number TEXT NOT NULL,
    symbol TEXT NOT NULL,
    underlying TEXT NOT NULL,

    -- Option details (NULL for stock)
    option_type TEXT,           -- 'Call', 'Put', NULL for stock
    strike REAL,
    expiration DATE,

    -- Chain linkage
    chain_id TEXT,              -- Which chain this lot belongs to
    leg_index INTEGER,          -- Position within multi-leg strategy (0, 1, 2, 3)

    -- Opening details
    opening_order_id TEXT NOT NULL,
    opening_transaction_id TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_date TIMESTAMP NOT NULL,

    -- Quantity tracking (signed: + for long, - for short)
    original_quantity INTEGER NOT NULL,
    remaining_quantity INTEGER NOT NULL,

    -- Assignment/exercise lineage
    derived_from_lot_id INTEGER,    -- If this lot came from assignment/exercise
    derivation_type TEXT,           -- 'ASSIGNMENT', 'EXERCISE', NULL

    -- Status
    status TEXT DEFAULT 'OPEN',     -- 'OPEN', 'PARTIAL', 'CLOSED'

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (chain_id) REFERENCES order_chains(chain_id),
    FOREIGN KEY (derived_from_lot_id) REFERENCES position_lots(lot_id)
);

-- Indexes for common queries
CREATE INDEX idx_lots_account_status ON position_lots(account_number, status);
CREATE INDEX idx_lots_chain ON position_lots(chain_id);
CREATE INDEX idx_lots_symbol ON position_lots(account_number, symbol);
CREATE INDEX idx_lots_underlying ON position_lots(account_number, underlying);
CREATE INDEX idx_lots_derived_from ON position_lots(derived_from_lot_id);
```

### 2. `lot_closings` - Closing Event Tracking

Records each closing event against a lot. Enables FIFO matching and partial closure tracking.

```sql
CREATE TABLE lot_closings (
    closing_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- What was closed
    lot_id INTEGER NOT NULL,

    -- Closing details
    closing_order_id TEXT NOT NULL,
    closing_transaction_id TEXT,
    quantity_closed INTEGER NOT NULL,   -- Absolute value
    closing_price REAL NOT NULL,
    closing_date TIMESTAMP NOT NULL,

    -- How it closed
    closing_type TEXT NOT NULL,         -- 'MANUAL', 'EXPIRATION', 'ASSIGNMENT', 'EXERCISE'

    -- P&L for this specific closing
    realized_pnl REAL NOT NULL,

    -- For assignment/exercise: the resulting stock lot
    resulting_lot_id INTEGER,           -- Links to the stock lot created

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (lot_id) REFERENCES position_lots(lot_id),
    FOREIGN KEY (resulting_lot_id) REFERENCES position_lots(lot_id)
);

CREATE INDEX idx_closings_lot ON lot_closings(lot_id);
CREATE INDEX idx_closings_order ON lot_closings(closing_order_id);
CREATE INDEX idx_closings_date ON lot_closings(closing_date);
```

---

## Modified Tables

### 3. `order_chains` - Enhanced Chain Tracking

Add fields for better quantity and status tracking.

```sql
-- New columns to add
ALTER TABLE order_chains ADD COLUMN leg_count INTEGER DEFAULT 1;
ALTER TABLE order_chains ADD COLUMN original_quantity INTEGER;
ALTER TABLE order_chains ADD COLUMN remaining_quantity INTEGER;
ALTER TABLE order_chains ADD COLUMN has_assignment BOOLEAN DEFAULT 0;
ALTER TABLE order_chains ADD COLUMN assignment_date DATE;
ALTER TABLE order_chains ADD COLUMN realized_pnl REAL DEFAULT 0;
ALTER TABLE order_chains ADD COLUMN unrealized_pnl REAL DEFAULT 0;
```

---

## Data Flow Examples

### Example 1: Bull Put Spread (Vertical)

**Trade**: Sell 450P, Buy 445P on SPY (5-wide spread, 2 contracts)

```
Opening Order:
├── Lot 1: SPY 450P, qty=-2, leg_index=0 (short leg)
└── Lot 2: SPY 445P, qty=+2, leg_index=1 (long leg)

Chain:
├── chain_id: "SPY_SPREAD_20240115_abc123"
├── leg_count: 2
├── original_quantity: 2
└── remaining_quantity: 2
```

### Example 2: Partial Closure

**Action**: Close 1 of 2 spreads

```
Closing Order (1 contract):
├── lot_closings: lot_id=1, quantity_closed=1, closing_type='MANUAL'
└── lot_closings: lot_id=2, quantity_closed=1, closing_type='MANUAL'

Updated Lots:
├── Lot 1: remaining_quantity=-1, status='PARTIAL'
└── Lot 2: remaining_quantity=+1, status='PARTIAL'

Updated Chain:
├── remaining_quantity: 1
└── chain_status: 'PARTIAL'
```

### Example 3: Early Assignment on Short Leg

**Scenario**: Short 450P assigned, you receive 100 shares at $450

```
Before Assignment:
├── Lot 1: SPY 450P, qty=-2, status='PARTIAL' (1 remaining after partial close)
└── Lot 2: SPY 445P, qty=+2, status='PARTIAL' (1 remaining)

Assignment Event:
├── lot_closings: lot_id=1, quantity_closed=1, closing_type='ASSIGNMENT'
│   └── resulting_lot_id=3 (points to new stock lot)
└── New Lot 3: SPY stock, qty=+100, derived_from_lot_id=1, derivation_type='ASSIGNMENT'

After Assignment:
├── Lot 1: remaining_quantity=0, status='CLOSED'
├── Lot 2: remaining_quantity=+1, status='OPEN' (long put still open!)
└── Lot 3: SPY stock, qty=+100, status='OPEN'

Chain Update:
├── has_assignment: true
├── assignment_date: 2024-01-20
└── chain_status: 'ASSIGNED' (new status to indicate broken spread)
```

### Example 4: Overlapping Positions

**Scenario**: Two independent bull put spreads on SPY opened on different days

```
Trade A (Jan 10): Sell 450P/Buy 445P
├── Lot 1: SPY 450P, qty=-2, chain_id='CHAIN_A'
└── Lot 2: SPY 445P, qty=+2, chain_id='CHAIN_A'

Trade B (Jan 15): Sell 450P/Buy 445P (same strikes!)
├── Lot 3: SPY 450P, qty=-3, chain_id='CHAIN_B'
└── Lot 4: SPY 445P, qty=+3, chain_id='CHAIN_B'

Closing Trade A (Jan 20):
└── Matches to Lots 1 & 2 via chain_id, NOT by symbol
```

The key insight: **chain_id on the lot determines which trade it belongs to**, not the symbol.

### Example 5: Roll the Spread

**Action**: Roll the spread to new expiration

```
Roll Order (contains closing + opening):
├── Closing legs: BTC 450P, STC 445P → close Lots 1 & 2
└── Opening legs: STO 455P, BTO 450P → create Lots 5 & 6

New Lots:
├── Lot 5: SPY 455P Feb, qty=-2, chain_id='CHAIN_A', leg_index=0
└── Lot 6: SPY 450P Feb, qty=+2, chain_id='CHAIN_A', leg_index=1

Chain stays the same, just has more orders in it.
```

---

## Chain Status Values

Enhance `chain_status` to capture more states:

| Status | Meaning |
|--------|---------|
| `OPEN` | All positions open, no closures |
| `PARTIAL` | Some quantity closed, some still open |
| `CLOSED` | All positions closed normally |
| `ASSIGNED` | One or more legs were assigned (spread broken) |
| `EXERCISED` | One or more legs were exercised |
| `EXPIRED` | All legs expired worthless |
| `MIXED` | Combination of closing types (e.g., one leg expired, one assigned) |

---

## Migration Strategy

### Phase 1: Add New Tables
1. Create `position_lots` table
2. Create `lot_closings` table
3. Add new columns to `order_chains`

### Phase 2: Backfill Data
1. For each existing chain, create lots from `order_positions`
2. Create closing records from closing transactions
3. Calculate and set `remaining_quantity` on lots and chains

### Phase 3: Update Processing Logic
1. Modify `OrderProcessorV2` to create lots instead of updating inventory
2. Modify chain derivation to use lot matching
3. Update P&L calculator to use lot-based calculations

### Phase 4: Deprecate Old Tables
1. Stop writing to `positions_inventory`
2. Update API endpoints to read from `position_lots`
3. Eventually drop `positions_inventory`

---

## Key Benefits

| Gap | Solution |
|-----|----------|
| **Overlapping positions** | Each opening creates a unique lot; `chain_id` on lot determines trade ownership |
| **Vertical spreads** | `leg_index` links legs within a chain; legs share `chain_id` |
| **Early assignment** | `derived_from_lot_id` + `derivation_type` tracks stock lineage; `lot_closings.resulting_lot_id` links to new stock lot |
| **Partial closures** | `remaining_quantity` on lots; `lot_closings` records each closure event |

---

## Assignment Detection Logic

Based on actual TT transaction data, assignment creates TWO linked transactions:

```
2026-01-09T17:00:00  Receive Deliver  Assignment              OKLO..CALL  "Removal of option due to assignment"  Order#=EMPTY
2026-01-09T17:00:00  Receive Deliver  Sell to Open  SELL_TO_OPEN  OKLO      "Sell to Open 400 OKLO @ 104.00"       Order#=EMPTY
```

**Detection rules:**

1. Both have `Type = "Receive Deliver"`
2. Both have **no order_id** (empty Order # field)
3. Same timestamp (or within seconds)
4. Same underlying symbol
5. One has `Sub Type = "Assignment"` (option removal)
6. One has `Sub Type = "Sell to Open"` or `"Buy to Open"` (stock position)

**Processing algorithm:**

```python
def process_assignment_pair(option_tx, stock_tx, chain):
    # 1. Close the option lot
    option_lot = find_lot_by_symbol(option_tx.symbol, chain)
    close_lot(
        lot=option_lot,
        closing_type='ASSIGNMENT',
        closing_price=0,  # Assignment has no price on option side
    )

    # 2. Create the stock lot with lineage
    stock_lot = create_lot(
        symbol=stock_tx.symbol,  # e.g., "OKLO"
        quantity=stock_tx.quantity,  # -400 (negative = short)
        entry_price=stock_tx.price,  # 104.00
        chain_id=chain.chain_id,  # SAME chain as the option
        derived_from_lot_id=option_lot.lot_id,
        derivation_type='ASSIGNMENT',
    )

    # 3. Update chain status
    chain.has_assignment = True
    chain.status = 'ASSIGNED'
```

**Call vs Put Assignment:**

| Spread Type | Assigned Leg | Stock Result | Stock Action |
|-------------|--------------|--------------|--------------|
| Call spread (short call assigned) | Short call | Short stock (-shares) | SELL_TO_OPEN |
| Put spread (short put assigned) | Short put | Long stock (+shares) | BUY_TO_OPEN |

---

## UI: Nested View for Assignment-Derived Positions

Stock positions created from assignment are shown as **children** of the assigned option, not as separate legs. This reflects that they're "cleanup" positions that must be closed quickly.

**Visual representation:**

```
Chain: OKLO Diagonal (Dec 8 - Jan 12)  Status: CLOSED  P&L: +$3,973.15
├── Leg 0: Short 4x Jan 104C @ $12.47
│   ├── Opened: Dec 8, 2025
│   ├── Closed: Jan 9, 2026 (ASSIGNED)
│   ├── P&L: +$4,983.53
│   │
│   └── [Derived] Short 400 OKLO @ $104.00
│       ├── Created: Jan 9, 2026 (from assignment)
│       ├── Closed: Jan 12, 2026 @ $104.91 (covered)
│       └── P&L: -$369.40
│
└── Leg 1: Long 4x May 70C @ $44.15
    ├── Opened: Dec 8, 2025
    ├── Closed: Jan 12, 2026 @ $42.56
    └── P&L: -$640.98
```

**Data model support:**

The `derived_from_lot_id` field enables this nested display:

```sql
-- Get chain with nested derived positions
SELECT
    pl.*,
    derived.lot_id AS derived_lot_id,
    derived.symbol AS derived_symbol,
    derived.status AS derived_status
FROM position_lots pl
LEFT JOIN position_lots derived ON derived.derived_from_lot_id = pl.lot_id
WHERE pl.chain_id = ?
ORDER BY pl.leg_index, derived.lot_id;
```

**UI behavior:**

- Derived positions are **indented** under their parent
- Derived positions show a **"from assignment"** or **"from exercise"** badge
- Chain `leg_count` does NOT include derived positions (still shows 2 for a spread)
- Chain status shows `ASSIGNED` while derived position is open, `CLOSED` when all closed

---

## Real Example: OKLO Diagonal Assignment

From actual TT data - validates the schema handles this correctly.

**Opening (Dec 8, Order #425434695):**
```
Lot 1: SELL_TO_OPEN 4x OKLO Jan 104C @ 12.47  → +$4,983.53
Lot 2: BUY_TO_OPEN  4x OKLO May 70C  @ 44.15  → -$17,664.46
                                        Net debit: -$12,680.93
```

**Assignment (Jan 9, No Order #):**
```
Lot 1: CLOSED via assignment (option removed, price=$0)
Lot 3: SELL_TO_OPEN 400 OKLO @ 104.00 → +$41,594.92 (short stock)
       derived_from_lot_id = Lot 1
       derivation_type = 'ASSIGNMENT'
```

**Close (Jan 12, Order #431740438):**
```
Lot 2: SELL_TO_CLOSE 4x May 70C @ 42.56 → +$17,023.48
Lot 3: BUY_TO_CLOSE 400 OKLO @ 104.91  → -$41,964.32 (cover short)
                                   Net: -$24,940.84
```

**P&L Calculation by Lot:**

| Lot | Type | Open | Close | P&L |
|-----|------|------|-------|-----|
| Lot 1 | Short Jan 104C | +$4,983.53 | $0 (assigned) | +$4,983.53 |
| Lot 2 | Long May 70C | -$17,664.46 | +$17,023.48 | -$640.98 |
| Lot 3 | Short 400 OKLO | +$41,594.92 | -$41,964.32 | -$369.40 |
| **Total** | | | | **+$3,973.15** |

This matches the TT "Total" column sum: $3,973.16 (penny difference from rounding).

**Chain state after each event:**

```
After Opening:
├── chain_status: OPEN
├── leg_count: 2
├── realized_pnl: $0
└── unrealized_pnl: (market dependent)

After Assignment:
├── chain_status: ASSIGNED
├── leg_count: 2 (Lot 3 is derived, not a new "leg")
├── has_assignment: true
├── realized_pnl: +$4,983.53 (Lot 1 closed)
└── Lot 2 still open, Lot 3 (stock) open

After Close:
├── chain_status: CLOSED
├── realized_pnl: +$3,973.15
└── All lots closed
```

---

## Open Questions

1. **FIFO vs LIFO vs User-specified**: Should closing transactions always match FIFO, or allow user override?
   - Recommendation: Default FIFO, but allow manual lot selection in UI

2. **Chain merging**: If user closes a spread that spans two chains (accidentally), should we merge or error?
   - Recommendation: Error in processing, require explicit chain selection

3. **Wash sale tracking**: Do we need to track wash sales for tax purposes?
   - Could add `is_wash_sale` and `disallowed_loss` to `lot_closings`

4. **Historical data**: Should we backfill existing data or start fresh?
   - Recommendation: Backfill to maintain continuity

---

## Next Steps

1. Review and approve schema design
2. Write migration script
3. Update `OrderProcessorV2` to use lot-based tracking
4. Update `PnLCalculatorV2` for lot-based P&L
5. Update API endpoints
6. Update frontend to display lot information
