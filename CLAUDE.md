# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## High-Level Application Overview

### What is OptionLedger?

OptionLedger is a comprehensive local web application designed for options traders who use Tastytrade. It automatically imports, organizes, and analyzes your trading data to provide insights into your trading performance and current positions.

### Core Purpose

The application solves several key problems for options traders:
- **Trade Organization**: Automatically groups related transactions into coherent trades and chains
- **Strategy Recognition**: Identifies complex multi-leg strategies (Iron Condors, Spreads, etc.)
- **Roll Tracking**: Links rolled positions to show complete trade progression over time
- **Live Monitoring**: Provides real-time P&L tracking for open positions
- **Performance Analysis**: Calculates accurate profit/loss across complex trade chains

### How It Works (User Perspective)

1. **Setup**: User configures OAuth2 credentials (provider_secret + refresh_token) in `.env` or via Settings page
2. **Auto-Connect**: App authenticates with Tastytrade on startup using OAuth2
3. **Data Sync**: One-click sync imports all transactions from Tastytrade accounts
4. **Automatic Processing**: System intelligently groups transactions into trades and identifies strategies
5. **Live Tracking**: Open positions update with real-time market data via WebSocket
6. **Analysis**: View trade chains, P&L progression, and performance metrics through web interface

### Key Features

**Position Management**:
- Real-time portfolio overview with live P&L calculations
- Days-to-expiration warnings for time-sensitive positions
- Visual indicators showing current price relative to strike prices
- Persistent user comments and notes on positions

**Trade Chain Analysis**:
- Links opening trades → rolls → closings into complete progressions
- Accurate P&L calculation across entire chain lifecycle
- Strategy detection for complex multi-leg positions
- Visual chain progression with status indicators

**Data Security & Privacy**:
- 100% local application - no cloud storage or external data sharing
- OAuth2 credentials stored in local `.env` file (never committed to git)
- No login page or session cookies - app auto-connects on startup
- SQLite database stored locally on user's machine

### Technical Architecture

The application follows a modern web architecture:
- **Backend**: Python FastAPI server providing REST API and WebSocket endpoints
- **Frontend**: Multi-page app with per-page Alpine.js components for reactivity
- **Database**: SQLite for local data persistence
- **Real-time Data**: WebSocket integration for live market quotes
- **Authentication**: OAuth2 via tastytrade SDK v12 (provider_secret + refresh_token in `.env`)

### Data Flow Summary

```
Tastytrade API → Transaction Import → Strategy Detection → Database Storage → Web Interface
                                                                ↓
Live Market Data → WebSocket → Real-time Position Updates → User Dashboard
```

The system maintains two main views:
1. **Open Positions**: Current portfolio with live P&L and risk metrics
2. **Order Chains**: Historical view of complete trade progressions and strategy analysis

## Project Overview

OptionLedger is a local web application for tracking and analyzing options trades from Tastytrade. It uses FastAPI for the backend, Alpine.js/Tailwind CSS for the frontend, and SQLite for local data storage.

## Common Development Commands

### Running the Application
```bash
# Start the application (Linux/Mac)
./start.sh

# Start the application (Windows)
start.bat

# Or directly with Python
python app.py
```

The application runs on http://localhost:8000 with auto-reload enabled during development. The default page is the Open Positions page, with Order Chains accessible at /chains.

### Authentication (OAuth2)
- Uses Tastytrade SDK v12 with OAuth2 authentication (async-only)
- Credentials (`TASTYTRADE_PROVIDER_SECRET` and `TASTYTRADE_REFRESH_TOKEN`) stored in `.env` file
- App auto-connects on startup via `ConnectionManager` singleton — no login page needed
- OAuth credentials can also be configured via the Settings page (`/settings`)
- Get credentials from: my.tastytrade.com → Manage → My Profile → API → OAuth Applications
- Token refresh is handled automatically by the SDK

### Database Operations
```bash
# Query specific trades
python query_db.py

# Migrate database schema
python migrate_database.py
```

### Managing Trades
```bash
# Interactive trade management CLI
python manage_trades.py
```

### Testing
```bash
# Run individual test files directly with Python
python test_pnl_calculation.py
python test_chain_creation.py
python test_expiration.py
# etc.
```

## Architecture Overview

### Core Components

1. **FastAPI Backend** (`app.py`):
   - Serves the web interface and API endpoints
   - Handles trade sync, filtering, and updates
   - WebSocket endpoint for real-time quotes at `/ws/quotes`
   - System components initialized on startup

2. **Database Layer** (`src/database/db_manager.py`):
   - SQLite database with tables for trades, option_legs, stock_legs, accounts, transactions, positions, orders, order_legs, order_chains
   - Context manager pattern for safe database operations
   - All trades stored locally in `trade_journal.db`
   - Row factory returns sqlite3.Row objects for dict-like access

3. **Order Processing System**:
   - **OrderProcessor** (`src/models/order_processor.py`): Core processing engine for transaction grouping
   - **PositionInventoryManager** (`src/models/position_inventory.py`): Tracks open positions and matches closings
   - **StrategyDetector** (`src/models/strategy_detector.py`): Identifies complex option strategies
   - **PnLCalculator** (`src/models/pnl_calculator.py`): Calculates P&L with proper roll chain handling

4. **Legacy Trade Recognition** (`src/models/trade_strategy.py`):
   - Groups individual transactions into complete trades
   - Recognizes multi-leg option strategies (Iron Condors, Verticals, etc.)
   - Handles timezone conversion (UTC → US/Eastern)
   - Still used alongside the order system for backward compatibility

5. **Tastytrade Integration** (`src/api/tastytrade_client.py`):
   - OAuth2 authentication via `Session(provider_secret, refresh_token)`
   - All methods are async (tastytrade SDK v12 is async-only)
   - Supports multiple accounts
   - Quote caching with 30-second TTL

6. **Connection Manager** (`src/utils/auth_manager.py`):
   - `ConnectionManager` singleton holds a shared `TastytradeClient` instance
   - Auto-connects on startup, reused across all API requests
   - Provides `get_client()`, `is_configured()`, `get_status()` methods
   - Reconnect endpoint available for credential updates

### Frontend Structure

- **Open Positions Page** (default): `static/positions-dense.html` with live quotes and position management
- **Order Chains Dashboard**: `static/chains-dense.html` at `/chains` with `static/js/app.js` (advanced strategy detection)
- **Position Ledger**: `static/ledger-dense.html` at `/ledger` with position-group model, lot lifecycle view, action/order toggle, and group management using inline `ledgerApp()` Alpine component
- **Performance Reports**: `static/reports-dense.html` at `/reports` with strategy breakdown and historical performance
- **Portfolio Risk X-Ray**: `static/risk-dashboard.html` at `/risk` with real-time portfolio Greeks, Black-Scholes engine, and ApexCharts visualizations (delta exposure, theta projection, treemap, scenario analysis)
- **Settings**: `static/settings.html` at `/settings` for OAuth credential management, connection status, and app configuration
- **Alpine.js** for reactivity (loaded from CDN)
- **ApexCharts** for advanced visualizations on Risk page (loaded from CDN)
- **Chart.js** for visualizations (loaded from CDN)
- **Tailwind CSS** for styling (loaded from CDN)
- **WebSocket integration** for real-time price streaming
- **LocalStorage** for persistent user comments and settings

### Data Flow

1. User clicks "Sync Trades" → API call to `/api/sync-trades`
2. Backend fetches transactions from Tastytrade API
3. Transactions grouped into trades by `StrategyRecognizer`
4. Trades stored in SQLite database
5. Frontend updates via API calls to display trades

### Live Data Features

1. **Real-time Quotes**: WebSocket connection (`/ws/quotes`) streams live market data
2. **Position Tracking**: Current positions fetched from Tastytrade API with live P&L
3. **Cross-page State**: Account selection synced between Order Chains and Positions pages
4. **Persistent Comments**: User notes stored in localStorage, scoped by underlying + account

### Sync Behavior by Page

The Sync button behaves differently depending on which page you're on:

**Chains Page Sync** (`/api/sync`):
- Fetches transactions from Tastytrade → saves to database
- Fetches current positions → saves to database
- Fetches account balances → saves to database
- Reprocesses order chains with strategy detection
- Shows notification popup with transaction/position counts

**Positions Page Sync** (`/api/sync-positions-only`):
- Fetches current positions → saves to database
- Fetches account balances → saves to database
- Does NOT fetch transactions or reprocess chains (fast mode)

**Implications**:
- Syncing on Chains page updates both chains AND positions data
- Syncing on Positions page only updates positions (faster, but new trades won't appear on Chains until you sync there)
- The Positions page uses fast mode by default for better responsiveness

## Key Implementation Details

### Order Chain System
The system links related trades into "chains" (opening → rolls → closing) by:
- Matching positions based on underlying, quantity, and timing
- Tracking roll relationships through position changes
- Aggregating P&L across entire chains
- Visual progression display with chain indicators

### Transaction Grouping Algorithm
The system matches closing transactions to their opening counterparts by:
- Indexing all opening transactions by option details
- Finding corresponding closings and grouping them together
- Handling multi-leg strategies that may have time gaps between legs

### Timezone Handling
All timestamps from Tastytrade (UTC) are converted to US/Eastern time to ensure correct date display.

### Trade Status Management
- OPEN: Trade has unclosed positions
- CLOSED: All positions closed
- PARTIAL: Some legs closed (for multi-leg strategies)
- ASSIGNED/EXPIRED: Special close types

### Position Page Features
- **DTE Column**: Shows minimum days to expiration for option positions (yellow/bold ≤21 days)
- **Price Position Indicators**: Visual representation of current price vs strike prices for spreads
- **Strategy Recognition**: Automatic identification of Iron Condors, Verticals, Covered Calls, etc.
- **Live P&L**: Real-time unrealized P&L calculations using current market prices
- **Comments System**: Persistent user notes stored locally with localStorage

## Order System Notes

The system uses position-based order chain tracking with:
- Position-based tracking instead of trade-based
- Better handling of rolls and chain relationships
- More accurate P&L calculations for complex strategies
- Separation of orders from trades for cleaner data model

Key tables:
- `orders`: Individual orders with strategy detection
- `order_legs`: Option/stock legs for each order
- `order_chains`: Links related orders (opening → rolls → closing)
- `positions`: Current position inventory

## Security Considerations

- OAuth2 credentials stored in local `.env` file (gitignored)
- No login page, session cookies, or per-request authentication
- A shared `ConnectionManager` singleton holds the authenticated client
- Never commit: `.env`, `*.db`
- All data stored locally - no external API calls except to Tastytrade

## Common Issues and Solutions

1. **Trades showing wrong dates**: Fixed by timezone conversion in `trade_strategy.py`
2. **Multi-leg trades split up**: Fixed by improved transaction grouping in OrderProcessor
3. **Database locked errors**: Use context managers, avoid long-running transactions
4. **Authentication failures**: Check `.env` has valid `TASTYTRADE_PROVIDER_SECRET` and `TASTYTRADE_REFRESH_TOKEN`, or update via Settings page
5. **Missing quotes**: Check market hours and ensure symbols are valid
6. **Incorrect P&L for rolls**: The system properly tracks roll chains and calculates cumulative P&L
7. **Expired positions showing as open**: The system handles expirations, assignments, and exercises as closing events

## Development Workflow

Every code change must follow this process:

### 1. Linear Issue Required
- Every change must be associated with a Linear issue — use an existing one or create a new one before starting work
- When I refer to "Issues" I am referring to the issues, bugs, enhancements, etc. that are kept in Linear
- Don't ask for permission to read or write to Linear - just do it
- When creating a new issue, always assign it to me (Steve Johnson)
- Sometimes there will be issues labeled "Research"
  - Update Research issues with your findings in the comments

### 2. Git Workflow
- **Branch per task**: Create a feature branch from `main` for each issue (e.g., `opt-70-feature-name`)
- **Commit frequently**: Make meaningful commits as you work, not one giant commit at the end
- **Merge to main when done**: After changes are tested, merge the branch back to `main`

### 3. Linear Issue Lifecycle
- **Starting work**: Update the issue status to "In Progress"
- **During work**: Update the issue comments in Linear with progress notes or decisions made
- **Code complete**: Change status to "In Review" if you believe the issue is fixed or completed
- **After merge to main**: Mark the issue as "Done"