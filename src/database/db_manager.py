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
from loguru import logger

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.models.trade_strategy import Trade, OptionLeg, StockLeg, TradeStatus, StrategyType


class DatabaseManager:
    def __init__(self, db_path: str = "trade_journal.db"):
        self.db_path = db_path
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
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_underlying ON trades(underlying)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_number)")
            
            # Add transaction action and timestamp columns if they don't exist
            self._add_transaction_columns()
            
            logger.info("Database initialized successfully")
    
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
                            updated_at = CURRENT_TIMESTAMP
                        WHERE trade_id = ?
                    """, (
                        trade.strategy_type.value,
                        trade.status.value,
                        trade.exit_date,
                        trade.net_premium,
                        trade.current_pnl,
                        trade.days_in_trade,
                        trade.trade_id
                    ))
                else:
                    # Insert new trade
                    cursor.execute("""
                        INSERT INTO trades (
                            trade_id, account_number, underlying, strategy_type, entry_date,
                            exit_date, status, original_notes, current_notes,
                            tags, net_premium, current_pnl, days_in_trade
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        trade.days_in_trade
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
                            unrealized_pnl, pnl_percent
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        pos.get('pnl_percent')
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
    
    def get_win_rate(self) -> float:
        """Get win rate percentage"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total closed trades
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'Closed'")
            total = cursor.fetchone()[0]
            
            if total == 0:
                return 0.0
            
            # Get winning trades
            cursor.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'Closed' AND current_pnl > 0"
            )
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
    
    def search_trades(self, search_term: str) -> List[Dict[str, Any]]:
        """Search trades by various fields"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Search in multiple fields
            query = """
                SELECT * FROM trades 
                WHERE trade_id LIKE ? 
                OR underlying LIKE ? 
                OR strategy_type LIKE ?
                OR original_notes LIKE ?
                OR current_notes LIKE ?
                ORDER BY entry_date DESC
            """
            
            search_pattern = f"%{search_term}%"
            params = [search_pattern] * 5
            
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