# Complete Trading System Logic Verification Statements
## Core Transaction and Order Rules
### Basic Relationships
1. An Order belongs to an Account
2. A Transaction belongs to an Order
3. A Position is Opened from an opening transaction (BTO or STO)
4. A Position is Closed from a closing transaction (BTC or STC)
5. Long positions are opened with a BTO transaction
6. Long positions are closed  with a STC transaction
7. Short positions are opened with a STO transaction
8. Short positions are closed with a BTC transaction
9. BTC or STC transactions close positions from a previous order
10. Order can open positions (BTO/STO), close positions (BTC/STC) or both
11. Orders that close positions always close positions that were opened in a previous Order
12. A Trade is made up of 1 or more positions
13. A Trade is opened when 1 or more positions are opened
14. A Trade is closed when all position in the Trade are closed
### Rolling Orders
1. A rolling order contains both opening and closing transactions
2. Detection of a Rolling Order is based on the Order containing both opening and closing transactions and the closing transactions matching an earlier open order for the same account, underlying symbol, expiration date, strike price and option type
3. **Position-Based Roll Linking**: Rolling orders are linked to previous orders by matching exact position details:
   - Same account number
   - Same underlying symbol  
   - Same expiration date
   - Same strike price
   - Same option type (Call/Put)
   - Closing transactions in rolling order must match open positions from earlier orders
4. **Chain Detection Rules**:
   - Orders with system-generated closures (expiration, assignment, exercise) are excluded from rolling chains
   - Only orders with manual closing transactions can be part of rolling chains
   - Time proximity requirement: Rolling orders must occur within 30 days of previous order
5. **Order Chain Construction**: Chains are built iteratively by finding rolling orders that close positions from the current order in the chain
### Closing Orders
1. A closing order contains only closing transactions (BTC or STC)
### Expiration Processing
1. Expiration, Exercise and Assignment transactions are system generated and have a type of "Receive Deliver" with a sub-type of "Assignment", "Cash Settled Assignment", "Exercise", "Cash Settled Exercise" or "Expiration"

### Order Cards
1. The Order Chains page is made up of cards that represent individual Orders linked together by Rolling or Closing Orders
2. An Order Chain can be ended (Closed, Expired, Exercised, etc...) by a Closing Order, or system generated transactions such as Expiration, Exercise or Assignment
3. The Strategy label for each Order Chain should be determined by the characteristics of the opening order
4. Order Cards should show all BTO, STO, BTC, STC transactions on their own line
5. Order Cards should show system generated transactions such as Expiration, Exercise or Assignment as emblems on the appropriate transactions they've been applied to
6. Rolling Orders should be linked to the Order that they are acting on (rolling) through position-based matching
7. Orders can contain multiple "fill" transactions and these should be summed up into a single summed quantity for the appropriate transaction type (BTO, STO, BTC, STC)
8. P&L should be calculated and shown on each Order Card and a Total P&L also shown for each Order Chain

## Strategy Recognition Rules

### Position-Based Strategy Classification
1. Strategy classification is determined by analyzing all positions within an order
2. When positions exist in the same order (stock + option), standard multi-leg strategy rules apply
3. When only option positions exist in an order, enhanced historical analysis is required for accurate classification

### Covered Call Detection Rules
1. **Definition**: A Covered Call requires short call positions with sufficient long stock coverage
2. **Timing Requirement**: Stock positions must exist **at or before** the time of call sale
3. **Coverage Requirement**: Any amount of stock coverage qualifies (partial coverage accepted)
4. **Historical Analysis**: System checks for existing stock positions in the same underlying by:
   - Same account number
   - Same underlying symbol
   - Stock position exists on or before the call order date
   - Stock position status is OPEN at time of analysis
5. **Coverage Calculation**: Coverage ratio = (Available Shares / (Call Contracts × 100)) × 100%
6. **Classification Logic**:
   - If no stock exists at call sale time → "Naked Call"
   - If any stock exists at call sale time → "Covered Call" (with coverage percentage logged)
7. **Retroactive Coverage Exclusion**: Stock purchased after call sale does NOT qualify as covered call coverage

### Single Position Strategy Rules
1. **Option Positions**:
   - Long Call: Positive quantity, Call option
   - Long Put: Positive quantity, Put option  
   - Naked Call: Negative quantity, Call option, no stock coverage
   - Cash Secured Put: Negative quantity, Put option
   - Covered Call: Negative quantity, Call option, with historical stock coverage
2. **Stock Positions**:
   - Long Stock: Positive quantity, equity instrument
   - Short Stock: Negative quantity, equity instrument

### Multi-Position Strategy Rules
1. **Two Position Strategies**:
   - **Stock + Option Combinations**:
     - Covered Call: Stock position + short call position (same order)
     - Complex Strategy: Other stock + option combinations
   - **Two Option Combinations** (same expiration):
     - Vertical Spreads: Same option type, different strikes
     - Straddle: Different option types, same strike
     - Strangle: Different option types, different strikes
   - **Two Option Combinations** (different expiration):
     - Calendar Spread: Same strike, different expirations
     - Diagonal Spread: Different strikes, different expirations

2. **Four Position Strategies**:
   - Iron Condor: 2 calls + 2 puts, 4 different strikes
   - Iron Butterfly: 2 calls + 2 puts, 3 different strikes

3. **Three Position Strategies**:
   - Butterfly: 3 options of same type with different strikes

### Strategy Recognition Implementation
1. **Primary Analysis**: Standard position analysis within the order
2. **Enhanced Analysis**: Historical stock position lookup for potential covered calls
3. **Logging**: System logs coverage calculations and classification reasoning
4. **Chain Strategy Sync**: Order chain strategy updated to match opening order strategy
5. **Database Consistency**: Strategy changes trigger chain strategy updates

### Order Chain Display Rules
1. **Stock Position Filtering**: Order Chains page displays only orders containing option positions
2. **Pure Stock Orders**: Orders containing only stock positions are filtered from Order Chains display
3. **Mixed Orders**: Orders containing both stock and option positions are displayed
4. **Strategy Labels**: Chain strategy reflects the opening order's strategy classification

### Position Quantity Tracking
1. **Quantity Signs**:
   - Positive quantities = Long positions
   - Negative quantities = Short positions
2. **Option Quantities**: Represent number of contracts
3. **Stock Quantities**: Represent number of shares
4. **Coverage Calculations**: Options require 100 shares per contract for full coverage

## User Interface Requirements

### Order Chain Display Enhancements
1. **Emblem System**: Orders display emblems to indicate special characteristics:
   - **A**: Assignment occurred
   - **E**: Expiration occurred  
   - **X**: Exercise occurred
   - **R emblem removed**: Rolling orders identified by ROLLING order type, not emblem
2. **Status Column Removal**: Status columns removed from position details as status can be inferred from chain progression
3. **Order Type Display**: Prominent display of order types (OPENING, ROLLING, CLOSING) replaces redundant status information
4. **Inline Order Expansion**: Order details expand inline rather than using modal dialogs
5. **Chain Progression Clarity**: Users can follow order progression through chain sequence (OPENING→ROLLING→ROLLING→EXPIRED)

### Data Filtering and Focus
1. **Options-Only Display**: Order Chains page shows only orders containing option positions
2. **Stock Order Exclusion**: Pure stock trading orders filtered from Order Chains view
3. **Position Page Preparation**: All position data with quantities ready for dedicated Positions page
4. **Account Separation**: Position and chain data properly separated by account

### Strategy Recognition Feedback
1. **Enhanced Logging**: Detailed logs show coverage calculations and strategy classification reasoning
2. **Coverage Percentage**: System calculates and logs actual coverage ratios for covered calls
3. **Classification Transparency**: Clear indication of why strategies were classified as covered vs naked
4. **Historical Context**: Strategy recognition considers historical position context for accurate classification
