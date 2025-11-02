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
import logging

logger = logging.getLogger(__name__)

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

# Legacy imports removed - V2 system only


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
                CREATE TABLE IF NOT EXISTS order_positions (
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
            
            # Order chain cache - stores complete order details for fast display
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_chain_cache (
                    chain_id TEXT,
                    order_id TEXT,
                    order_data TEXT,  -- JSON blob of complete order data
                    PRIMARY KEY (chain_id, order_id),
                    FOREIGN KEY (chain_id) REFERENCES order_chains (chain_id)
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
                
                # Check order_positions table for new enhanced fields
                cursor.execute("PRAGMA table_info(order_positions)")
                position_columns = [column[1] for column in cursor.fetchall()]

                if 'opening_order_id' not in position_columns:
                    cursor.execute("ALTER TABLE order_positions ADD COLUMN opening_order_id TEXT")
                    logger.info("Added opening_order_id column to order_positions")

                if 'closing_order_id' not in position_columns:
                    cursor.execute("ALTER TABLE order_positions ADD COLUMN closing_order_id TEXT")
                    logger.info("Added closing_order_id column to order_positions")

                if 'opening_amount' not in position_columns:
                    cursor.execute("ALTER TABLE order_positions ADD COLUMN opening_amount REAL")
                    logger.info("Added opening_amount column to order_positions")

                if 'closing_amount' not in position_columns:
                    cursor.execute("ALTER TABLE order_positions ADD COLUMN closing_amount REAL")
                    logger.info("Added closing_amount column to order_positions")
                    
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
    
    # Legacy trade methods removed - use V2 order system instead

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
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions ORDER BY market_value DESC")
            return [dict(row) for row in cursor.fetchall()]
    
    def save_positions(self, positions: List[Dict[str, Any]], account_number: str) -> bool:
        """Save current positions for an account - OPTIMIZED with batch insert"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Clear existing positions for this account
                cursor.execute("DELETE FROM positions WHERE account_number = ?", (account_number,))
                
                # Prepare batch insert data
                if positions:
                    # Use executemany for batch insert (much faster)
                    insert_data = [
                        (
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
                        )
                        for pos in positions
                    ]
                    
                    cursor.executemany("""
                        INSERT INTO positions (
                            account_number, symbol, underlying, instrument_type, quantity,
                            quantity_direction, average_open_price, close_price,
                            market_value, cost_basis, realized_day_gain,
                            unrealized_pnl, pnl_percent, opened_at, expires_at,
                            strike_price, option_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, insert_data)
                
                return True
                
        except Exception as e:
            logger.error(f"Error saving positions: {str(e)}")
            return False
    
    # Legacy statistics methods removed - use V2 order/chain system for analytics

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