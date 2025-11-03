#!/usr/bin/env python3
import time
import asyncio
from contextlib import contextmanager
from src.database.db_manager import DatabaseManager
from src.api.tastytrade_client import TastytradeClient
from src.models.position_manager import PositionManager
from src.utils.crypto_utils import load_encrypted_credentials

@contextmanager
def timer(name):
    start = time.time()
    print(f"[{name}] Starting...")
    yield
    elapsed = time.time() - start
    print(f"[{name}] Completed in {elapsed:.2f}s")

async def profile_sync_positions():
    db_manager = DatabaseManager()
    
    with timer("Load credentials"):
        creds = load_encrypted_credentials()
        username = creds['username']
        password = creds['password']
    
    with timer("Initialize Tastytrade client"):
        tt_client = TastytradeClient()
    
    with timer("Authenticate"):
        await tt_client.authenticate(username, password)
    
    with timer("Get accounts"):
        accounts = await tt_client.get_accounts()
        print(f"  Found {len(accounts)} accounts")
    
    total_positions = 0
    for account in accounts:
        account_number = account['account-number']
        print(f"\nProcessing account {account_number}:")
        
        with timer(f"  Fetch positions from API for {account_number}"):
            positions = await tt_client.get_positions(account_number)
            print(f"    Found {len(positions)} positions")
            total_positions += len(positions)
        
        with timer(f"  Get balances for {account_number}"):
            balances = await tt_client.get_account_balances(account_number)
        
        with timer(f"  Store account info for {account_number}"):
            db_manager.update_account(account_number, balances)
        
        # Break down position processing
        for i, position in enumerate(positions):
            if i == 0:  # Only profile first position in detail
                print(f"\n  Detailed profiling for first position:")
                
                with timer(f"    Process position {position.get('symbol', 'Unknown')}"):
                    position_manager = PositionManager(db_manager)
                    
                    with timer("      Get current quote"):
                        # This might be making individual API calls
                        pass
                    
                    with timer("      Calculate Greeks"):
                        pass
                    
                    with timer("      Store position in DB"):
                        position_manager.store_position(position, account_number)
            else:
                # Process remaining positions without detailed timing
                position_manager = PositionManager(db_manager)
                position_manager.store_position(position, account_number)
    
    print(f"\nTotal positions processed: {total_positions}")
    
    # Check if quotes are being fetched individually
    with timer("Check quote fetching pattern"):
        # Let's see if we're making individual quote requests
        pass

if __name__ == "__main__":
    asyncio.run(profile_sync_positions())