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

2. **Database Layer** (`src/database/db_manager.py`):
   - SQLite database with tables for trades, option_legs, stock_legs, accounts, and transactions
   - Context manager pattern for safe database operations
   - All trades stored locally in `trade_journal.db`

3. **Trade Recognition System** (`src/models/trade_strategy.py`):
   - Groups individual transactions into complete trades
   - Recognizes multi-leg option strategies (Iron Condors, Verticals, etc.)
   - Handles timezone conversion (UTC → US/Eastern)
   - Key fix: Properly groups closing transactions with their openings

4. **Strategy Configuration** (`config/strategies.json`):
   - JSON-based strategy definitions
   - Editable via web UI at `/strategy-config`
   - Defines recognition rules, categories, and display properties

5. **Tastytrade Integration** (`src/api/tastytrade_client.py`):
   - Authenticates and fetches transaction data
   - Supports multiple accounts
   - Uses unofficial tastytrade SDK

### Frontend Structure

- **Main Dashboard**: `static/index-fixed.html` with `static/js/app-fixed.js`
- **Strategy Config UI**: `static/strategy-config.html`
- **Alpine.js** for reactivity, **Chart.js** for visualizations

### Data Flow

1. User clicks "Sync Trades" → API call to `/api/sync-trades`
2. Backend fetches transactions from Tastytrade API
3. Transactions grouped into trades by `StrategyRecognizer`
4. Trades stored in SQLite database
5. Frontend updates via API calls to display trades

## Key Implementation Details

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

## Security Considerations

- Credentials encrypted using `cryptography` library
- Never commit: `.env`, `crypto.key`, `encrypted_credentials.py`, `*.db`
- All data stored locally - no external API calls except to Tastytrade

## Common Issues and Solutions

1. **Trades showing wrong dates**: Fixed by timezone conversion in `trade_strategy.py`
2. **Multi-leg trades split up**: Fixed by improved transaction grouping algorithm
3. **Database locked errors**: Use context managers, avoid long-running transactions
4. **Authentication failures**: Run `python setup_credentials.py` to reset credentials