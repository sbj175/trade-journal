# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trade Journal is a local web application for tracking and analyzing options trades from Tastytrade. It uses FastAPI for the backend, Alpine.js/Tailwind CSS for the frontend, and SQLite for local data storage.

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

The application runs on http://localhost:8000 with auto-reload enabled during development.

### Setting Up Credentials
```bash
# Set up encrypted Tastytrade credentials
python setup_credentials.py

# Check credentials are working
python check_creds.py
```

### Database Operations
```bash
# Check database structure and content
python check_db.py

# Query specific trades
python query_db.py

# Migrate database schema
python migrate_database.py
```

### Managing Trades
```bash
# Sync trades from Tastytrade
python manage_trades.py

# Clean up RIVN-specific trades (legacy script)
python clean_rivn_trades.py
```

## Architecture Overview

### Core Components

1. **FastAPI Backend** (`app.py`):
   - Serves the web interface and API endpoints
   - Handles trade sync, filtering, and updates
   - Manages strategy configuration
   - WebSocket endpoint for real-time quotes

2. **Database Layer** (`src/database/db_manager.py`):
   - SQLite database with tables for trades, option_legs, stock_legs, accounts, transactions, and positions
   - Context manager pattern for safe database operations
   - All trades stored locally in `trade_journal.db`

3. **Trade Recognition System** (`src/models/trade_strategy.py`):
   - Groups individual transactions into complete trades
   - Recognizes multi-leg option strategies (Iron Condors, Verticals, etc.)
   - Handles timezone conversion (UTC → US/Eastern)
   - Position-based roll linking and chain detection

4. **Strategy Configuration** (`config/strategies.json`):
   - JSON-based strategy definitions with 15+ pre-configured strategies
   - Editable via web UI at `/strategy-config`
   - Defines recognition rules, categories, and display properties

5. **Tastytrade Integration** (`src/api/tastytrade_client.py`):
   - Authenticates and fetches transaction data
   - Supports multiple accounts
   - Uses unofficial tastytrade SDK
   - Quote caching with 30-second TTL

### Frontend Structure

- **Order Chains Dashboard**: `static/index-fixed.html` with `static/js/app-fixed.js`
- **Open Positions Page**: `static/positions.html` with live quotes and position management
- **Strategy Config UI**: `static/strategy-config.html`
- **Alpine.js** for reactivity, **Chart.js** for visualizations
- **WebSocket integration** for real-time price streaming

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

## Security Considerations

- Credentials encrypted using `cryptography` library with Fernet encryption
- Never commit: `.env`, `crypto.key`, `encrypted_credentials.py`, `*.db`
- All data stored locally - no external API calls except to Tastytrade

## Common Issues and Solutions

1. **Trades showing wrong dates**: Fixed by timezone conversion in `trade_strategy.py`
2. **Multi-leg trades split up**: Fixed by improved transaction grouping algorithm
3. **Database locked errors**: Use context managers, avoid long-running transactions
4. **Authentication failures**: Run `python setup_credentials.py` to reset credentials
5. **Missing quotes**: Check market hours and ensure symbols are valid