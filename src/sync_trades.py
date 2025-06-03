#!/usr/bin/env python3
"""
Main script to sync trades from Tastytrade to Google Sheets
"""

import os
import sys
from datetime import datetime
import argparse
from loguru import logger
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.tastytrade_client import TastytradeClient
from src.api.google_sheets_client import GoogleSheetsClient
from src.models.trade_manager import TradeManager

# Configure logging
logger.add(
    "logs/trade_sync_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)


def sync_trades_to_sheets(days_back: int = 30) -> bool:
    """
    Sync trades from Tastytrade to Google Sheets
    
    Args:
        days_back: Number of days of history to sync
        
    Returns:
        bool: Success status
    """
    logger.info(f"Starting trade sync for the last {days_back} days")
    
    # Initialize clients
    tastytrade = TastytradeClient()
    sheets = GoogleSheetsClient()
    trade_manager = TradeManager()
    
    # Authenticate Tastytrade
    if not tastytrade.authenticate():
        logger.error("Failed to authenticate with Tastytrade")
        return False
    
    # Authenticate Google Sheets
    if not sheets.authenticate():
        logger.error("Failed to authenticate with Google Sheets")
        return False
    
    # Create sheets if they don't exist
    if not sheets.create_sheets_if_not_exist():
        logger.error("Failed to create necessary sheets")
        return False
    
    # Sync data
    success = True
    
    # Get and sync transactions
    logger.info("Fetching transactions...")
    transactions = tastytrade.get_transactions(days_back=days_back)
    if not sheets.write_transactions(transactions):
        logger.error("Failed to write transactions")
        success = False
    
    # Get and sync positions
    logger.info("Fetching positions...")
    positions = tastytrade.get_positions()
    if not sheets.write_positions(positions):
        logger.error("Failed to write positions")
        success = False
    
    # Get and sync account balances
    logger.info("Fetching account balances...")
    balances = tastytrade.get_account_balances()
    if balances and not sheets.write_account_summary(balances):
        logger.error("Failed to write account summary")
        success = False
    
    # Process transactions into trades and sync
    logger.info("Processing transactions into trades...")
    trades = trade_manager.process_transactions(transactions)
    trade_data = trade_manager.export_for_sheets()
    if not sheets.write_trades(trade_data):
        logger.error("Failed to write trade data")
        success = False
    else:
        logger.info(f"Processed {len(trades)} trades from transactions")
    
    # Create dashboard
    logger.info("Creating dashboard...")
    if not sheets.create_dashboard_sheet():
        logger.error("Failed to create dashboard")
        success = False
    
    if success:
        logger.info("Trade sync completed successfully")
    else:
        logger.warning("Trade sync completed with errors")
    
    return success


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Sync trades from Tastytrade to Google Sheets"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of history to sync (default: 30)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
        logger.add(
            "logs/trade_sync_{time}.log",
            rotation="1 day",
            retention="7 days",
            level="DEBUG"
        )
    
    # Load environment variables
    load_dotenv()
    
    # Check required environment variables
    required_vars = ['GOOGLE_SHEETS_SPREADSHEET_ID']
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please copy .env.example to .env and fill in your Google Sheets ID")
        sys.exit(1)
    
    # Check if Tastytrade credentials are available (either encrypted or in env)
    from src.utils.credential_manager import CredentialManager
    cm = CredentialManager()
    username, password = cm.get_tastytrade_credentials()
    
    if not username or not password:
        logger.error("No Tastytrade credentials found!")
        logger.error("Please run 'python setup_credentials.py' to set up encrypted credentials")
        logger.error("Or add TASTYTRADE_USERNAME and TASTYTRADE_PASSWORD to your .env file")
        sys.exit(1)
    
    # Run sync
    try:
        success = sync_trades_to_sheets(days_back=args.days)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()