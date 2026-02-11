#!/usr/bin/env python3
"""
Database Migration Script
Adds account support to existing trade journal database
"""

import sqlite3
import os
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def migrate_database():
    """Migrate existing database to add account support"""
    
    db_path = "trade_journal.db"
    
    if not os.path.exists(db_path):
        logger.info("No existing database found, will create new one with account support")
        return True
    
    logger.info("Migrating existing database to add account support...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if accounts table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        if not cursor.fetchone():
            logger.info("Creating accounts table...")
            cursor.execute("""
                CREATE TABLE accounts (
                    account_number TEXT PRIMARY KEY,
                    account_name TEXT,
                    account_type TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Check if trades table has account_number column
        cursor.execute("PRAGMA table_info(trades)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'account_number' not in columns:
            logger.info("Adding account_number column to trades table...")
            cursor.execute("ALTER TABLE trades ADD COLUMN account_number TEXT DEFAULT 'UNKNOWN'")
            
            # Update existing trades to have a default account
            logger.info("Setting default account for existing trades...")
            cursor.execute("UPDATE trades SET account_number = 'LEGACY' WHERE account_number = 'UNKNOWN'")
            
            # Create a legacy account entry
            cursor.execute("""
                INSERT OR IGNORE INTO accounts (account_number, account_name, account_type)
                VALUES ('LEGACY', 'Legacy Account (Pre-Migration)', 'Individual')
            """)
        
        # Check if positions table has account_number column
        cursor.execute("PRAGMA table_info(positions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'account_number' not in columns:
            logger.info("Adding account_number column to positions table...")
            cursor.execute("ALTER TABLE positions ADD COLUMN account_number TEXT DEFAULT 'LEGACY'")
        
        # Add margin_equity column to account_balances if it doesn't exist
        cursor.execute("PRAGMA table_info(account_balances)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'margin_equity' not in columns:
            logger.info("Adding margin_equity column to account_balances table...")
            cursor.execute("ALTER TABLE account_balances ADD COLUMN margin_equity REAL")

        # Create indexes
        logger.info("Creating account indexes...")
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_number)")
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Index creation warning: {e}")
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Database migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database migration failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = migrate_database()
    if not success:
        exit(1)