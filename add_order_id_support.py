#!/usr/bin/env python3
"""
Database migration to add order_id support
Adds order_id columns to store transaction grouping information
"""

import sqlite3
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.database.db_manager import DatabaseManager
from loguru import logger

def migrate_database():
    """Add order_id columns to support transaction grouping"""
    
    db = DatabaseManager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        logger.info("Starting database migration to add order_id support...")
        
        try:
            # Add order_id column to option_legs table
            logger.info("Adding order_id column to option_legs table...")
            cursor.execute("""
                ALTER TABLE option_legs 
                ADD COLUMN order_id TEXT
            """)
            
            # Add order_id column to stock_legs table  
            logger.info("Adding order_id column to stock_legs table...")
            cursor.execute("""
                ALTER TABLE stock_legs
                ADD COLUMN order_id TEXT
            """)
            
            # Create index on order_id for faster grouping queries
            logger.info("Creating indexes on order_id columns...")
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_option_legs_order_id 
                ON option_legs(order_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stock_legs_order_id
                ON stock_legs(order_id)
            """)
            
            # Add a table to track raw transactions with order IDs
            logger.info("Creating transactions table for raw transaction data...")
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_number) REFERENCES accounts(account_number)
                )
            """)
            
            # Create indexes for raw_transactions
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_transactions_order_id
                ON raw_transactions(order_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_transactions_symbol
                ON raw_transactions(underlying_symbol, executed_at)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_transactions_account
                ON raw_transactions(account_number, executed_at)
            """)
            
            conn.commit()
            logger.info("✅ Database migration completed successfully!")
            
            # Verify the changes
            cursor.execute("PRAGMA table_info(option_legs)")
            option_columns = cursor.fetchall()
            has_order_id = any(col['name'] == 'order_id' for col in option_columns)
            
            if has_order_id:
                logger.info("✅ order_id column successfully added to option_legs")
            else:
                logger.error("❌ Failed to add order_id column to option_legs")
                
            cursor.execute("PRAGMA table_info(stock_legs)")
            stock_columns = cursor.fetchall()
            has_order_id = any(col['name'] == 'order_id' for col in stock_columns)
            
            if has_order_id:
                logger.info("✅ order_id column successfully added to stock_legs")
            else:
                logger.error("❌ Failed to add order_id column to stock_legs")
                
            # Check if raw_transactions table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='raw_transactions'
            """)
            if cursor.fetchone():
                logger.info("✅ raw_transactions table created successfully")
            else:
                logger.error("❌ Failed to create raw_transactions table")
                
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                logger.info("⚠️  order_id columns already exist, skipping migration")
            else:
                logger.error(f"❌ Database migration failed: {e}")
                raise
        except Exception as e:
            logger.error(f"❌ Unexpected error during migration: {e}")
            raise

def verify_migration():
    """Verify the migration was successful"""
    
    db = DatabaseManager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        logger.info("Verifying migration...")
        
        # Check option_legs structure
        cursor.execute("PRAGMA table_info(option_legs)")
        option_columns = [col['name'] for col in cursor.fetchall()]
        logger.info(f"option_legs columns: {option_columns}")
        
        # Check stock_legs structure
        cursor.execute("PRAGMA table_info(stock_legs)")
        stock_columns = [col['name'] for col in cursor.fetchall()]
        logger.info(f"stock_legs columns: {stock_columns}")
        
        # Check raw_transactions structure
        cursor.execute("PRAGMA table_info(raw_transactions)")
        raw_columns = [col['name'] for col in cursor.fetchall()]
        logger.info(f"raw_transactions columns: {raw_columns}")
        
        # Check indexes
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name LIKE '%order_id%'
        """)
        indexes = cursor.fetchall()
        logger.info(f"order_id indexes: {[idx['name'] for idx in indexes]}")

if __name__ == "__main__":
    print("🚀 Starting database migration for order_id support...")
    migrate_database()
    verify_migration()
    print("✅ Migration complete!")