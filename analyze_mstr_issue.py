#!/usr/bin/env python3
from src.database.db_manager import DatabaseManager

def analyze_mstr_issue():
    db = DatabaseManager()
    
    print("=== MSTR Strategy Classification Analysis ===\n")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check trades classified as Covered Call but without stock legs
        print("1. MSTR trades classified as 'Covered Call' but missing stock legs:\n")
        
        query = """
        SELECT t.trade_id, t.strategy_type, t.status, t.entry_date,
               COUNT(ol.id) as option_count, COUNT(sl.id) as stock_count
        FROM trades t
        LEFT JOIN option_legs ol ON t.trade_id = ol.trade_id
        LEFT JOIN stock_legs sl ON t.trade_id = sl.trade_id
        WHERE t.underlying = 'MSTR' AND t.strategy_type = 'Covered Call'
        GROUP BY t.trade_id
        HAVING stock_count = 0
        ORDER BY t.entry_date DESC
        """
        
        cursor.execute(query)
        covered_calls_no_stock = cursor.fetchall()
        
        print(f"Found {len(covered_calls_no_stock)} MSTR 'Covered Call' trades without stock legs:")
        for trade in covered_calls_no_stock:
            print(f"  {trade[0]} | {trade[1]} | {trade[2]} | {trade[3]} | Options: {trade[4]} | Stock: {trade[5]}")
        
        print(f"\n2. MSTR trades classified as 'Naked Call' with missing legs:\n")
        
        query = """
        SELECT t.trade_id, t.strategy_type, t.status, t.entry_date,
               COUNT(ol.id) as option_count, COUNT(sl.id) as stock_count
        FROM trades t
        LEFT JOIN option_legs ol ON t.trade_id = ol.trade_id
        LEFT JOIN stock_legs sl ON t.trade_id = sl.trade_id
        WHERE t.underlying = 'MSTR' AND t.strategy_type = 'Naked Call'
        GROUP BY t.trade_id
        ORDER BY t.entry_date DESC
        """
        
        cursor.execute(query)
        naked_calls = cursor.fetchall()
        
        print(f"Found {len(naked_calls)} MSTR 'Naked Call' trades:")
        for trade in naked_calls:
            print(f"  {trade[0]} | {trade[1]} | {trade[2]} | {trade[3]} | Options: {trade[4]} | Stock: {trade[5]}")
        
        print(f"\n3. Analysis Summary:")
        print(f"   - {len(covered_calls_no_stock)} trades classified as 'Covered Call' should likely be 'Naked Call'")
        print(f"   - {len([t for t in naked_calls if t[4] == 0])} trades classified as 'Naked Call' have no option legs (data issue)")
        
        # Let's check if there are any MSTR stock positions in raw_transactions that might not be grouped
        print(f"\n4. Check for MSTR stock transactions in raw_transactions:\n")
        
        query = """
        SELECT id, symbol, underlying_symbol, transaction_type, action, 
               quantity, price, executed_at, order_id
        FROM raw_transactions 
        WHERE symbol = 'MSTR' AND transaction_type = 'Trade'
        ORDER BY executed_at DESC
        LIMIT 10
        """
        
        cursor.execute(query)
        stock_transactions = cursor.fetchall()
        
        print(f"Found {len(stock_transactions)} recent MSTR stock transactions:")
        for tx in stock_transactions:
            print(f"  TX {tx[0]} | {tx[1]} | {tx[3]} {tx[4]} | Qty: {tx[5]} | ${tx[6]} | {tx[7]} | Order: {tx[8]}")
        
        if stock_transactions:
            print(f"\n   --> Found MSTR stock transactions! These should be creating stock legs.")
            
            # Check if these stock transactions are linked to any trades
            stock_tx_ids = [str(tx[0]) for tx in stock_transactions]
            
            query = f"""
            SELECT trade_id, symbol, transaction_ids, transaction_actions
            FROM stock_legs 
            WHERE symbol = 'MSTR'
            """
            
            cursor.execute(query)
            stock_legs = cursor.fetchall()
            
            print(f"\n5. Existing MSTR stock legs:")
            for leg in stock_legs:
                print(f"  Trade: {leg[0]} | Symbol: {leg[1]} | TX IDs: {leg[2]} | Actions: {leg[3]}")
            
            if not stock_legs:
                print("   --> No MSTR stock legs found! This confirms the issue - stock transactions aren't being grouped into trades properly.")

if __name__ == "__main__":
    analyze_mstr_issue()