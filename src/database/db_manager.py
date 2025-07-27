"""
Database Manager for Trade Journal
Handles all database operations using SQLite
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json
import time
from loguru import logger

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.trade_strategy import Trade, OptionLeg, StockLeg, TradeStatus, StrategyType


class DatabaseManager:
    def __init__(self, db_path: str = "trade_journal.db"):
        self.db_path = db_path
        self._initialized = False
        # Note: initialize_database() is called explicitly by FastAPI startup event
    
    def ensure_initialized(self):
        """Ensure database is initialized (for standalone scripts)"""
        if not self._initialized:
            self.initialize_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def initialize_database(self):
        """Create all necessary tables"""
        start_time = time.time()
        logger.info("Starting database initialization...")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Accounts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_number TEXT PRIMARY KEY,
                    account_name TEXT,
                    account_type TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    account_number TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    entry_date DATE NOT NULL,
                    exit_date DATE,
                    status TEXT NOT NULL,
                    original_notes TEXT,
                    current_notes TEXT,
                    tags TEXT,
                    net_premium REAL,
                    current_pnl REAL,
                    days_in_trade INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_number) REFERENCES accounts(account_number)
                )
            """)
            
            # Option legs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_legs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiration DATE NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    transaction_ids TEXT,
                    transaction_actions TEXT,
                    transaction_timestamps TEXT,
                    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
                )
            """)
            
            # Stock legs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_legs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    transaction_ids TEXT,
                    transaction_actions TEXT,
                    transaction_timestamps TEXT,
                    FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
                )
            """)
            
            # Positions table (current positions)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_number TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    underlying TEXT,
                    instrument_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    quantity_direction TEXT,
                    average_open_price REAL,
                    close_price REAL,
                    market_value REAL,
                    cost_basis REAL,
                    realized_day_gain REAL,
                    unrealized_pnl REAL,
                    pnl_percent REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_number) REFERENCES accounts(account_number)
                )
            """)
            
            # Account balances table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_number TEXT,
                    cash_balance REAL,
                    net_liquidating_value REAL,
                    equity_buying_power REAL,
                    derivative_buying_power REAL,
                    day_trading_buying_power REAL,
                    maintenance_requirement REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Order-based system tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    account_number TEXT,
                    underlying TEXT,
                    order_type TEXT,
                    strategy_type TEXT,
                    order_date DATE,
                    status TEXT,
                    total_quantity INTEGER,
                    total_pnl REAL,
                    has_assignment BOOLEAN DEFAULT 0,
                    has_expiration BOOLEAN DEFAULT 0,
                    has_exercise BOOLEAN DEFAULT 0,
                    linked_order_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions_new (
                    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    account_number TEXT,
                    symbol TEXT,
                    underlying TEXT,
                    instrument_type TEXT,
                    option_type TEXT,
                    strike REAL,
                    expiration DATE,
                    quantity INTEGER,
                    opening_price REAL,
                    closing_price REAL,
                    opening_transaction_id TEXT,
                    closing_transaction_id TEXT,
                    opening_action TEXT,
                    closing_action TEXT,
                    status TEXT,
                    pnl REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES orders (order_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_chains (
                    chain_id TEXT PRIMARY KEY,
                    underlying TEXT,
                    account_number TEXT,
                    opening_order_id TEXT,
                    strategy_type TEXT,
                    opening_date DATE,
                    closing_date DATE,
                    chain_status TEXT,
                    order_count INTEGER,
                    total_pnl REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_chain_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT,
                    order_id TEXT,
                    sequence_number INTEGER,
                    FOREIGN KEY (chain_id) REFERENCES order_chains (chain_id),
                    FOREIGN KEY (order_id) REFERENCES orders (order_id),
                    UNIQUE(chain_id, order_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_transactions (
                    id TEXT PRIMARY KEY,
                    account_number TEXT NOT NULL,
                    order_id TEXT,
                    transaction_type TEXT,
                    transaction_sub_type TEXT,
                    description TEXT,
                    executed_at TEXT,
                    transaction_date TEXT,
                    action TEXT,
                    symbol TEXT,
                    instrument_type TEXT,
                    underlying_symbol TEXT,
                    quantity REAL,
                    price REAL,
                    value REAL,
                    regulatory_fees REAL,
                    clearing_fees REAL,
                    commission REAL,
                    net_value REAL,
                    is_estimated_fee BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sync metadata table for tracking sync state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Quote cache table for persisting WebSocket quotes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quote_cache (
                    symbol TEXT PRIMARY KEY,
                    mark REAL,
                    bid REAL,
                    ask REAL,
                    last REAL,
                    change REAL,
                    change_percent REAL,
                    volume INTEGER,
                    prev_close REAL,
                    day_high REAL,
                    day_low REAL,
                    iv REAL,
                    ivr REAL,
                    iv_percentile REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create strategic indexes for performance
            # Core position and account queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_underlying ON positions(underlying)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_instrument_type ON positions(instrument_type)")
            
            # Order system indexes - most frequently queried
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_underlying ON orders(underlying)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_account_underlying ON orders(account_number, underlying)")
            
            # Order chains - for chain linking and efficiency calculations
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_account ON order_chains(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_underlying ON order_chains(underlying)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_status ON order_chains(chain_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_opening_date ON order_chains(opening_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_account_underlying ON order_chains(account_number, underlying)")
            
            # Chain membership - critical for chain queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chain_members_chain ON order_chain_members(chain_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chain_members_order ON order_chain_members(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chain_members_sequence ON order_chain_members(chain_id, sequence_number)")
            
            # Raw transactions - for opening date calculations
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_transactions_order ON raw_transactions(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_transactions_account ON raw_transactions(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_transactions_symbol ON raw_transactions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_transactions_executed_at ON raw_transactions(executed_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_transactions_action ON raw_transactions(action)")
            
            # Quote cache - for live data performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_quote_cache_symbol ON quote_cache(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_quote_cache_updated ON quote_cache(updated_at)")
            
            # Account and balance lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_account_balances_account ON account_balances(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_account_balances_timestamp ON account_balances(timestamp)")
            
            # Add transaction action and timestamp columns if they don't exist
            self._add_transaction_columns()
            
            # Enable foreign key constraints
            cursor.execute("PRAGMA foreign_keys = ON")
            
            self._initialized = True
            elapsed_time = time.time() - start_time
            logger.info(f"Database initialized successfully in {elapsed_time:.2f} seconds")
    
    def _add_transaction_columns(self):
        """Add transaction action and timestamp columns to existing tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if columns exist and add them if they don't
            try:
                # Check option_legs table
                cursor.execute("PRAGMA table_info(option_legs)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'transaction_actions' not in columns:
                    cursor.execute("ALTER TABLE option_legs ADD COLUMN transaction_actions TEXT")
                    logger.info("Added transaction_actions column to option_legs")
                    
                if 'transaction_timestamps' not in columns:
                    cursor.execute("ALTER TABLE option_legs ADD COLUMN transaction_timestamps TEXT")
                    logger.info("Added transaction_timestamps column to option_legs")
                
                # Check stock_legs table
                cursor.execute("PRAGMA table_info(stock_legs)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'transaction_actions' not in columns:
                    cursor.execute("ALTER TABLE stock_legs ADD COLUMN transaction_actions TEXT")
                    logger.info("Added transaction_actions column to stock_legs")
                    
                if 'transaction_timestamps' not in columns:
                    cursor.execute("ALTER TABLE stock_legs ADD COLUMN transaction_timestamps TEXT")
                    logger.info("Added transaction_timestamps column to stock_legs")
                
                # Check trades table for includes_roll column
                cursor.execute("PRAGMA table_info(trades)")
                trade_columns = [column[1] for column in cursor.fetchall()]
                
                if 'includes_roll' not in trade_columns:
                    cursor.execute("ALTER TABLE trades ADD COLUMN includes_roll BOOLEAN DEFAULT 0")
                    logger.info("Added includes_roll column to trades")
                
                # Check order_chains table for realized_pnl column
                cursor.execute("PRAGMA table_info(order_chains)")
                chain_columns = [column[1] for column in cursor.fetchall()]
                
                if 'realized_pnl' not in chain_columns:
                    cursor.execute("ALTER TABLE order_chains ADD COLUMN realized_pnl REAL DEFAULT 0.0")
                    logger.info("Added realized_pnl column to order_chains")
                
                if 'unrealized_pnl' not in chain_columns:
                    cursor.execute("ALTER TABLE order_chains ADD COLUMN unrealized_pnl REAL DEFAULT 0.0")
                    logger.info("Added unrealized_pnl column to order_chains")
                
                # Check positions table for opened_at column
                cursor.execute("PRAGMA table_info(positions)")
                position_columns = [column[1] for column in cursor.fetchall()]
                
                if 'opened_at' not in position_columns:
                    cursor.execute("ALTER TABLE positions ADD COLUMN opened_at TIMESTAMP")
                    logger.info("Added opened_at column to positions")
                
                if 'expires_at' not in position_columns:
                    cursor.execute("ALTER TABLE positions ADD COLUMN expires_at TIMESTAMP")
                    logger.info("Added expires_at column to positions")
                
                if 'strike_price' not in position_columns:
                    cursor.execute("ALTER TABLE positions ADD COLUMN strike_price REAL")
                    logger.info("Added strike_price column to positions")
                
                if 'option_type' not in position_columns:
                    cursor.execute("ALTER TABLE positions ADD COLUMN option_type TEXT")
                    logger.info("Added option_type column to positions")
                
                # Check positions_new table for new enhanced fields
                cursor.execute("PRAGMA table_info(positions_new)")
                position_columns = [column[1] for column in cursor.fetchall()]
                
                if 'opening_order_id' not in position_columns:
                    cursor.execute("ALTER TABLE positions_new ADD COLUMN opening_order_id TEXT")
                    logger.info("Added opening_order_id column to positions_new")
                
                if 'closing_order_id' not in position_columns:
                    cursor.execute("ALTER TABLE positions_new ADD COLUMN closing_order_id TEXT")
                    logger.info("Added closing_order_id column to positions_new")
                
                if 'opening_amount' not in position_columns:
                    cursor.execute("ALTER TABLE positions_new ADD COLUMN opening_amount REAL")
                    logger.info("Added opening_amount column to positions_new")
                
                if 'closing_amount' not in position_columns:
                    cursor.execute("ALTER TABLE positions_new ADD COLUMN closing_amount REAL")
                    logger.info("Added closing_amount column to positions_new")
                    
            except Exception as e:
                logger.error(f"Error adding transaction columns: {e}")
    
    def save_account(self, account_number: str, account_name: str = None, account_type: str = None) -> bool:
        """Save account information"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO accounts (account_number, account_name, account_type, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (account_number, account_name, account_type))
                
                return True
        except Exception as e:
            logger.error(f"Error saving account {account_number}: {str(e)}")
            return False
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """Get all accounts"""
        self.ensure_initialized()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE is_active = 1 ORDER BY account_number")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_account(self, account_number: str) -> Optional[Dict[str, Any]]:
        """Get specific account"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts WHERE account_number = ?", (account_number,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def save_trade(self, trade: Trade, account_number: str = None) -> bool:
        """Save a trade to the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if trade already exists
                cursor.execute("SELECT trade_id FROM trades WHERE trade_id = ?", (trade.trade_id,))
                exists = cursor.fetchone() is not None
                
                # Prepare trade data
                tags_json = json.dumps(trade.tags) if trade.tags else None
                
                # Use account_number from parameter, trade object, or existing database record
                if not account_number:
                    # Try to get from trade object first
                    account_number = getattr(trade, 'account_number', None)
                    
                    if not account_number:
                        # Try to get account from existing trade or use a default
                        if exists:
                            cursor.execute("SELECT account_number FROM trades WHERE trade_id = ?", (trade.trade_id,))
                            row = cursor.fetchone()
                            account_number = row[0] if row else "UNKNOWN"
                        else:
                            account_number = "UNKNOWN"
                
                if exists:
                    # Update existing trade (preserve user notes and account)
                    cursor.execute("""
                        UPDATE trades 
                        SET strategy_type = ?, status = ?, exit_date = ?,
                            net_premium = ?, current_pnl = ?, days_in_trade = ?,
                            includes_roll = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE trade_id = ?
                    """, (
                        trade.strategy_type.value,
                        trade.status.value,
                        trade.exit_date,
                        trade.net_premium,
                        trade.current_pnl,
                        trade.days_in_trade,
                        trade.includes_roll,
                        trade.trade_id
                    ))
                else:
                    # Insert new trade
                    cursor.execute("""
                        INSERT INTO trades (
                            trade_id, account_number, underlying, strategy_type, entry_date,
                            exit_date, status, original_notes, current_notes,
                            tags, net_premium, current_pnl, days_in_trade, includes_roll
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade.trade_id,
                        account_number,
                        trade.underlying,
                        trade.strategy_type.value,
                        trade.entry_date,
                        trade.exit_date,
                        trade.status.value,
                        trade.original_notes,
                        trade.current_notes,
                        tags_json,
                        trade.net_premium,
                        trade.current_pnl,
                        trade.days_in_trade,
                        trade.includes_roll
                    ))
                
                # Save option legs
                cursor.execute("DELETE FROM option_legs WHERE trade_id = ?", (trade.trade_id,))
                for leg in trade.option_legs:
                    cursor.execute("""
                        INSERT INTO option_legs (
                            trade_id, symbol, underlying, option_type, strike,
                            expiration, quantity, entry_price, exit_price, transaction_ids,
                            transaction_actions, transaction_timestamps
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade.trade_id,
                        leg.symbol,
                        leg.underlying,
                        leg.option_type,
                        leg.strike,
                        leg.expiration,
                        leg.quantity,
                        leg.entry_price,
                        leg.exit_price,
                        json.dumps(leg.transaction_ids),
                        json.dumps(leg.transaction_actions),
                        json.dumps(leg.transaction_timestamps)
                    ))
                
                # Save stock legs
                cursor.execute("DELETE FROM stock_legs WHERE trade_id = ?", (trade.trade_id,))
                for leg in trade.stock_legs:
                    cursor.execute("""
                        INSERT INTO stock_legs (
                            trade_id, symbol, quantity, entry_price,
                            exit_price, transaction_ids, transaction_actions, transaction_timestamps
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade.trade_id,
                        leg.symbol,
                        leg.quantity,
                        leg.entry_price,
                        leg.exit_price,
                        json.dumps(leg.transaction_ids),
                        json.dumps(leg.transaction_actions),
                        json.dumps(leg.transaction_timestamps)
                    ))
                
                return True
                
        except Exception as e:
            logger.error(f"Error saving trade {trade.trade_id}: {str(e)}")
            return False
    
    def get_trades(
        self,
        account_number: Optional[str] = None,
        status: Optional[str] = None,
        strategy: Optional[str] = None,
        underlying: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get trades with optional filters"""
        self.ensure_initialized()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM trades WHERE 1=1"
            params = []
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if strategy:
                query += " AND strategy_type = ?"
                params.append(strategy)
            
            if underlying:
                query += " AND underlying = ?"
                params.append(underlying)
            
            query += " ORDER BY entry_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            
            trades = []
            for row in cursor.fetchall():
                trade_dict = dict(row)
                # Parse tags JSON
                if trade_dict['tags']:
                    trade_dict['tags'] = json.loads(trade_dict['tags'])
                trades.append(trade_dict)
            
            return trades
    
    def get_trade_details(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Get full trade details including all legs"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get trade
            cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
            trade_row = cursor.fetchone()
            
            if not trade_row:
                return None
            
            trade = dict(trade_row)
            if trade['tags']:
                trade['tags'] = json.loads(trade['tags'])
            
            # Get option legs
            cursor.execute("SELECT * FROM option_legs WHERE trade_id = ?", (trade_id,))
            option_legs = []
            for row in cursor.fetchall():
                leg = dict(row)
                # Parse JSON fields
                if leg.get('transaction_actions'):
                    leg['transaction_actions'] = json.loads(leg['transaction_actions'])
                if leg.get('transaction_timestamps'):
                    leg['transaction_timestamps'] = json.loads(leg['transaction_timestamps'])
                option_legs.append(leg)
            trade['option_legs'] = option_legs
            
            # Get stock legs
            cursor.execute("SELECT * FROM stock_legs WHERE trade_id = ?", (trade_id,))
            stock_legs = []
            for row in cursor.fetchall():
                leg = dict(row)
                # Parse JSON fields
                if leg.get('transaction_actions'):
                    leg['transaction_actions'] = json.loads(leg['transaction_actions'])
                if leg.get('transaction_timestamps'):
                    leg['transaction_timestamps'] = json.loads(leg['transaction_timestamps'])
                stock_legs.append(leg)
            trade['stock_legs'] = stock_legs
            
            return trade
    
    def save_raw_transactions(self, transactions: List[Dict]) -> int:
        """Save raw transactions to database for order-based grouping"""
        self.ensure_initialized()
        saved_count = 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for txn in transactions:
                try:
                    # Check if transaction already exists
                    cursor.execute(
                        "SELECT id FROM raw_transactions WHERE id = ?",
                        (txn.get('id'),)
                    )
                    
                    if cursor.fetchone():
                        continue  # Skip duplicates
                    
                    # Insert raw transaction (match schema from migration)
                    cursor.execute("""
                        INSERT INTO raw_transactions (
                            id, account_number, order_id, transaction_type,
                            transaction_sub_type, description, executed_at,
                            transaction_date, action, symbol, instrument_type,
                            underlying_symbol, quantity, price, value,
                            regulatory_fees, clearing_fees, commission,
                            net_value, is_estimated_fee
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        txn.get('id'),
                        txn.get('account_number'),
                        txn.get('order_id'),
                        txn.get('transaction_type'),
                        txn.get('transaction_sub_type'),
                        txn.get('description'),
                        txn.get('executed_at'),
                        txn.get('transaction_date'),
                        txn.get('action'),
                        txn.get('symbol'),
                        txn.get('instrument_type'),
                        txn.get('underlying_symbol'),
                        txn.get('quantity'),
                        txn.get('price'),
                        txn.get('value'),
                        txn.get('regulatory_fees'),
                        txn.get('clearing_fees'),
                        txn.get('commission'),
                        txn.get('net_value'),
                        txn.get('is_estimated_fee')
                    ))
                    
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to save transaction {txn.get('id')}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"Saved {saved_count} raw transactions to database")
            
        return saved_count
    
    def get_raw_transactions(
        self,
        account_number: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        underlying: Optional[str] = None
    ) -> List[Dict]:
        """Get raw transactions with optional filters"""
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM raw_transactions WHERE 1=1"
            params = []
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
                
            if start_date:
                query += " AND executed_at >= ?"
                params.append(start_date)
                
            if end_date:
                query += " AND executed_at <= ?"
                params.append(end_date)
                
            if underlying:
                query += " AND underlying_symbol = ?"
                params.append(underlying)
            
            query += " ORDER BY executed_at DESC"
            
            cursor.execute(query, params)
            transactions = []
            
            for row in cursor.fetchall():
                transactions.append(dict(row))
                
            return transactions
    
    def update_trade(
        self,
        trade_id: str,
        status: Optional[str] = None,
        current_notes: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> bool:
        """Update trade user data"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                updates = []
                params = []
                
                if status is not None:
                    updates.append("status = ?")
                    params.append(status)
                
                if current_notes is not None:
                    updates.append("current_notes = ?")
                    params.append(current_notes)
                
                if tags is not None:
                    updates.append("tags = ?")
                    params.append(json.dumps(tags))
                
                if not updates:
                    return True
                
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(trade_id)
                
                query = f"UPDATE trades SET {', '.join(updates)} WHERE trade_id = ?"
                cursor.execute(query, params)
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating trade {trade_id}: {str(e)}")
            return False
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions ORDER BY market_value DESC")
            return [dict(row) for row in cursor.fetchall()]
    
    def save_positions(self, positions: List[Dict[str, Any]], account_number: str) -> bool:
        """Save current positions for an account"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Clear existing positions for this account
                cursor.execute("DELETE FROM positions WHERE account_number = ?", (account_number,))
                
                # Insert new positions
                for pos in positions:
                    cursor.execute("""
                        INSERT INTO positions (
                            account_number, symbol, underlying, instrument_type, quantity,
                            quantity_direction, average_open_price, close_price,
                            market_value, cost_basis, realized_day_gain,
                            unrealized_pnl, pnl_percent, opened_at, expires_at,
                            strike_price, option_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        account_number,
                        pos.get('symbol'),
                        pos.get('underlying_symbol'),
                        pos.get('instrument_type'),
                        pos.get('quantity'),
                        pos.get('quantity_direction'),
                        pos.get('average_open_price'),
                        pos.get('close_price'),
                        pos.get('market_value'),
                        pos.get('cost_basis'),
                        pos.get('realized_day_gain'),
                        pos.get('unrealized_pnl'),
                        pos.get('pnl_percent'),
                        pos.get('opened_at'),
                        pos.get('expires_at'),
                        pos.get('strike_price'),
                        pos.get('option_type')
                    ))
                
                return True
                
        except Exception as e:
            logger.error(f"Error saving positions: {str(e)}")
            return False
    
    def get_trade_count(self, account_number: Optional[str] = None, status: Optional[str] = None) -> int:
        """Get count of trades"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT COUNT(*) FROM trades WHERE 1=1"
            params = []
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def get_total_pnl(self, account_number: Optional[str] = None) -> float:
        """Get total P&L across all closed trades"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT COALESCE(SUM(current_pnl), 0) FROM trades WHERE status = 'Closed'"
            params = []
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
            
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def get_pnl_by_date(self, target_date: date, account_number: Optional[str] = None) -> float:
        """Get P&L for a specific date"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT COALESCE(SUM(current_pnl), 0) 
                FROM trades 
                WHERE status = 'Closed' AND DATE(exit_date) = ?
            """
            params = [target_date]
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
            
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def get_pnl_by_date_range(self, start_date: date, end_date: date, account_number: Optional[str] = None) -> float:
        """Get P&L for a date range"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT COALESCE(SUM(current_pnl), 0) 
                FROM trades 
                WHERE status = 'Closed' 
                AND DATE(exit_date) >= ? 
                AND DATE(exit_date) <= ?
            """
            params = [start_date, end_date]
            
            if account_number:
                query += " AND account_number = ?"
                params.append(account_number)
            
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def get_win_rate(self, account_number: str = None) -> float:
        """Get win rate percentage"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build query with optional account filter
            base_where = "WHERE status = 'Closed'"
            params = []
            
            if account_number:
                base_where += " AND account_number = ?"
                params.append(account_number)
            
            # Get total closed trades
            cursor.execute(f"SELECT COUNT(*) FROM trades {base_where}", params)
            total = cursor.fetchone()[0]
            
            if total == 0:
                return 0.0
            
            # Get winning trades
            win_where = base_where + " AND current_pnl > 0"
            cursor.execute(f"SELECT COUNT(*) FROM trades {win_where}", params)
            wins = cursor.fetchone()[0]
            
            return (wins / total) * 100
    
    def get_strategy_statistics(self) -> List[Dict[str, Any]]:
        """Get statistics broken down by strategy"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    strategy_type,
                    COUNT(*) as count,
                    SUM(CASE WHEN status = 'Closed' THEN current_pnl ELSE 0 END) as total_pnl,
                    AVG(CASE WHEN status = 'Closed' THEN current_pnl ELSE NULL END) as avg_pnl,
                    COUNT(CASE WHEN status = 'Closed' AND current_pnl > 0 THEN 1 ELSE NULL END) as wins,
                    COUNT(CASE WHEN status = 'Closed' THEN 1 ELSE NULL END) as closed_count
                FROM trades
                GROUP BY strategy_type
                ORDER BY count DESC
            """)
            
            results = []
            for row in cursor.fetchall():
                stat = dict(row)
                if stat['closed_count'] > 0:
                    stat['win_rate'] = (stat['wins'] / stat['closed_count']) * 100
                else:
                    stat['win_rate'] = 0
                results.append(stat)
            
            return results
    
    def search_trades(self, search_term: str, account_number: str = None) -> List[Dict[str, Any]]:
        """Search trades by various fields"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build query with optional account filter
            base_query = """
                SELECT * FROM trades 
                WHERE (trade_id LIKE ? 
                OR underlying LIKE ? 
                OR strategy_type LIKE ?
                OR original_notes LIKE ?
                OR current_notes LIKE ?)
            """
            
            search_pattern = f"%{search_term}%"
            params = [search_pattern] * 5
            
            # Add account filter if specified
            if account_number:
                base_query += " AND account_number = ?"
                params.append(account_number)
            
            query = base_query + " ORDER BY entry_date DESC"
            
            cursor.execute(query, params)
            
            trades = []
            for row in cursor.fetchall():
                trade_dict = dict(row)
                if trade_dict['tags']:
                    trade_dict['tags'] = json.loads(trade_dict['tags'])
                trades.append(trade_dict)
            
            return trades
    
    def get_monthly_performance(self, year: int) -> List[Dict[str, Any]]:
        """Get performance broken down by month"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    strftime('%m', exit_date) as month,
                    COUNT(*) as trades_closed,
                    SUM(current_pnl) as total_pnl,
                    AVG(current_pnl) as avg_pnl,
                    COUNT(CASE WHEN current_pnl > 0 THEN 1 ELSE NULL END) as wins
                FROM trades
                WHERE status = 'Closed' 
                AND strftime('%Y', exit_date) = ?
                GROUP BY month
                ORDER BY month
            """, (str(year),))
            
            results = []
            for row in cursor.fetchall():
                month_data = dict(row)
                if month_data['trades_closed'] > 0:
                    month_data['win_rate'] = (month_data['wins'] / month_data['trades_closed']) * 100
                else:
                    month_data['win_rate'] = 0
                results.append(month_data)
            
            return results
    
    def save_account_balance(self, balance: Dict[str, Any]) -> bool:
        """Save account balance snapshot"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO account_balances (
                        account_number, cash_balance, net_liquidating_value,
                        equity_buying_power, derivative_buying_power,
                        day_trading_buying_power, maintenance_requirement
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    balance.get('account_number'),
                    balance.get('cash_balance'),
                    balance.get('net_liquidating_value'),
                    balance.get('equity_buying_power'),
                    balance.get('derivative_buying_power'),
                    balance.get('day_trading_buying_power'),
                    balance.get('maintenance_requirement')
                ))
                return True
        except Exception as e:
            logger.error(f"Error saving account balance: {str(e)}")
            return False
    
    def get_sync_metadata(self, key: str) -> Optional[str]:
        """Get a sync metadata value by key"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT value FROM sync_metadata WHERE key = ?
            """, (key,))
            result = cursor.fetchone()
            return result['value'] if result else None
    
    def set_sync_metadata(self, key: str, value: str) -> bool:
        """Set a sync metadata value"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO sync_metadata (key, value, updated_at) 
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, value))
                return True
        except Exception as e:
            logger.error(f"Error setting sync metadata: {str(e)}")
            return False
    
    def get_last_sync_timestamp(self) -> Optional[datetime]:
        """Get the last sync timestamp"""
        timestamp_str = self.get_sync_metadata('last_sync_timestamp')
        if timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str)
            except ValueError:
                logger.warning(f"Invalid timestamp format: {timestamp_str}")
        return None
    
    def update_last_sync_timestamp(self, timestamp: datetime = None) -> bool:
        """Update the last sync timestamp"""
        if timestamp is None:
            timestamp = datetime.now()
        return self.set_sync_metadata('last_sync_timestamp', timestamp.isoformat())
    
    def is_initial_sync_completed(self) -> bool:
        """Check if initial sync has been completed"""
        return self.get_sync_metadata('initial_sync_completed') == 'true'
    
    def mark_initial_sync_completed(self) -> bool:
        """Mark initial sync as completed"""
        return self.set_sync_metadata('initial_sync_completed', 'true')
    
    def reset_sync_metadata(self) -> bool:
        """Reset sync metadata (for initial sync)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sync_metadata")
                return True
        except Exception as e:
            logger.error(f"Error resetting sync metadata: {str(e)}")
            return False
    
    def cache_quote(self, symbol: str, quote_data: Dict[str, Any]) -> bool:
        """Cache a quote in the database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO quote_cache (
                        symbol, mark, bid, ask, last, change, change_percent,
                        volume, prev_close, day_high, day_low, iv, ivr, iv_percentile,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    symbol,
                    quote_data.get('mark'),
                    quote_data.get('bid'),
                    quote_data.get('ask'),
                    quote_data.get('last'),
                    quote_data.get('change'),
                    quote_data.get('change_percent'),
                    quote_data.get('volume'),
                    quote_data.get('prev_close'),
                    quote_data.get('day_high'),
                    quote_data.get('day_low'),
                    quote_data.get('iv'),
                    quote_data.get('ivr'),
                    quote_data.get('iv_percentile')
                ))
                
                return True
        except Exception as e:
            logger.error(f"Error caching quote for {symbol}: {str(e)}")
            return False
    
    def get_cached_quotes(self, symbols: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get cached quotes from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if symbols:
                    placeholders = ','.join(['?' for _ in symbols])
                    cursor.execute(f"SELECT * FROM quote_cache WHERE symbol IN ({placeholders})", symbols)
                else:
                    cursor.execute("SELECT * FROM quote_cache")
                
                quotes = {}
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    symbol = row_dict.pop('symbol')
                    quotes[symbol] = row_dict
                
                return quotes
        except Exception as e:
            logger.error(f"Error getting cached quotes: {str(e)}")
            return {}
    
    def clear_old_quotes(self, hours_old: int = 24) -> bool:
        """Clear quotes older than specified hours"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM quote_cache 
                    WHERE updated_at < datetime('now', '-{} hours')
                """.format(hours_old))
                return True
        except Exception as e:
            logger.error(f"Error clearing old quotes: {str(e)}")
            return False