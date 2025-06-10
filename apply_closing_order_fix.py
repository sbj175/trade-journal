#!/usr/bin/env python3
"""
Apply the closing order fix by re-running the Order/Position model implementation
"""
import sqlite3
from datetime import datetime, date
from pathlib import Path

def create_order_position_tables(conn):
    """Create the Orders and Positions tables"""
    cursor = conn.cursor()
    
    # Create Orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            account_number TEXT NOT NULL,
            underlying TEXT NOT NULL,
            order_type TEXT NOT NULL, -- 'OPENING', 'CLOSING', 'ROLLING'
            strategy_type TEXT,
            order_date DATE NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED', 'PARTIAL'
            total_quantity INTEGER,
            total_pnl REAL DEFAULT 0,
            has_assignment BOOLEAN DEFAULT 0,
            has_expiration BOOLEAN DEFAULT 0,
            has_exercise BOOLEAN DEFAULT 0,
            linked_order_id TEXT, -- For rolling orders, links to the order being rolled
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_number) REFERENCES accounts(account_number)
        )
    """)
    
    # Create Positions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions_new (
            position_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            account_number TEXT NOT NULL,
            symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            instrument_type TEXT NOT NULL, -- 'EQUITY', 'EQUITY_OPTION'
            option_type TEXT, -- 'Call' or 'Put' for options
            strike REAL, -- For options
            expiration DATE, -- For options
            quantity INTEGER NOT NULL, -- Positive for long, negative for short
            opening_price REAL,
            closing_price REAL,
            opening_transaction_id TEXT,
            closing_transaction_id TEXT,
            opening_action TEXT, -- 'BTO', 'STO', 'BUY', 'SELL'
            closing_action TEXT, -- 'BTC', 'STC', 'SELL', 'BUY', 'EXPIRED', 'ASSIGNED', etc.
            status TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED'
            pnl REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (account_number) REFERENCES accounts(account_number)
        )
    """)
    
    print("Created Orders and Positions tables successfully")

def create_positions_from_order_fixed(order_info, conn):
    """
    FIXED: Create Position records from an order's transactions with proper consolidation
    """
    order_id = order_info['order_id']
    transactions = order_info['transactions']
    
    cursor = conn.cursor()
    
    # Get order details
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        print(f"Order {order_id} not found")
        return
    
    # FIXED: Properly group transactions by unique position identifiers
    positions = {}
    
    for tx in transactions:
        instrument_type = tx.get('instrument_type', '')
        symbol = tx.get('symbol', '')
        
        if not symbol:
            continue
        
        # Create unique position key based on instrument details
        if 'EQUITY_OPTION' in str(instrument_type):
            # Parse option details from symbol (e.g., "MSTR  250328C00342500")
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                # Extract components with better parsing
                try:
                    expiration = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[8:] if len(option_code) > 8 else option_code[7:]
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    # FIXED: Use comprehensive position key
                    position_key = (symbol.strip(), expiration, strike, option_type)
                except (IndexError, ValueError) as e:
                    print(f"Could not parse option symbol {symbol}: {e}")
                    position_key = (symbol.strip(),)
            else:
                position_key = (symbol.strip(),)
        else:
            # For stocks, just use symbol
            position_key = (symbol.strip(),)
        
        # FIXED: Consolidate all transactions for the same position
        if position_key not in positions:
            positions[position_key] = {
                'symbol': symbol.strip(),
                'instrument_type': instrument_type,
                'transactions': [],
                'opening_transactions': [],
                'closing_transactions': []
            }
        
        # Categorize transactions
        action = str(tx.get('action', '')).upper()
        if any(open_action in action for open_action in ['BTO', 'STO', 'OPEN']):
            positions[position_key]['opening_transactions'].append(tx)
        elif any(close_action in action for close_action in ['BTC', 'STC', 'CLOSE', 'ASSIGNED', 'EXPIRED']):
            positions[position_key]['closing_transactions'].append(tx)
        
        positions[position_key]['transactions'].append(tx)
    
    # FIXED: Create consolidated position records
    for position_key, position_data in positions.items():
        symbol = position_data['symbol']
        instrument_type = position_data['instrument_type']
        opening_txs = position_data['opening_transactions']
        closing_txs = position_data['closing_transactions']
        
        # FIXED: Don't artificially create opening transactions for pure closing orders
        if not opening_txs:
            # For pure closing orders, we need to handle this differently
            # Don't artificially create opening transactions from closing transactions
            pass
        
        # FIXED: Consolidate quantities and calculate weighted average prices
        total_opening_quantity = 0
        total_opening_value = 0
        total_closing_quantity = 0
        total_closing_value = 0
        
        for tx in opening_txs:
            qty = tx.get('quantity', 0)
            price = tx.get('price', 0)
            total_opening_quantity += qty
            total_opening_value += qty * price
        
        for tx in closing_txs:
            qty = tx.get('quantity', 0)
            price = tx.get('price', 0)
            total_closing_quantity += qty
            total_closing_value += qty * price
        
        # FIXED: Determine net quantity properly for closing orders
        if opening_txs:
            # Normal case: has opening transactions
            action = str(opening_txs[0].get('action', '')).upper()
            if 'SELL' in action or 'STO' in action:
                net_quantity = -abs(total_opening_quantity)
            else:
                net_quantity = abs(total_opening_quantity)
        else:
            # Pure closing order: net quantity should be the closing quantity
            # For BTC (closing long), quantity should be positive
            # For STC (closing short), quantity should be negative
            if closing_txs:
                action = str(closing_txs[0].get('action', '')).upper()
                if 'BTC' in action:
                    # Closing a long position - quantity should be positive (buying back)
                    net_quantity = abs(total_closing_quantity)
                elif 'STC' in action:
                    # Closing a short position - quantity should be negative (selling to close)
                    net_quantity = -abs(total_closing_quantity)
                else:
                    # Default to positive for other closing actions
                    net_quantity = abs(total_closing_quantity)
            else:
                net_quantity = 0
        
        # Calculate weighted average prices
        avg_opening_price = total_opening_value / total_opening_quantity if total_opening_quantity != 0 else 0
        avg_closing_price = total_closing_value / total_closing_quantity if total_closing_quantity != 0 else None
        
        # Extract position details
        if opening_txs:
            underlying = opening_txs[0].get('underlying_symbol') or opening_txs[0].get('symbol', '')
        elif closing_txs:
            underlying = closing_txs[0].get('underlying_symbol') or closing_txs[0].get('symbol', '')
        else:
            underlying = 'UNKNOWN'
        
        # Parse option details if applicable
        option_type = None
        strike = None
        expiration = None
        
        if 'EQUITY_OPTION' in str(instrument_type):
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                try:
                    expiration_str = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[8:] if len(option_code) > 8 else option_code[7:]
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    # Convert expiration to date
                    year = 2000 + int(expiration_str[:2])
                    month = int(expiration_str[2:4])
                    day = int(expiration_str[4:6])
                    expiration = f"{year:04d}-{month:02d}-{day:02d}"
                except (ValueError, IndexError) as e:
                    print(f"Could not parse option details for {symbol}: {e}")
        
        # Normalize actions
        def normalize_action(action_str):
            """Normalize transaction action"""
            if not action_str:
                return 'UNKNOWN'
            
            action = str(action_str).upper()
            
            # Map to standard actions
            if 'BUY_TO_OPEN' in action or 'BTO' in action:
                return 'BTO'
            elif 'BUY_TO_CLOSE' in action or 'BTC' in action:
                return 'BTC'
            elif 'SELL_TO_OPEN' in action or 'STO' in action:
                return 'STO'
            elif 'SELL_TO_CLOSE' in action or 'STC' in action:
                return 'STC'
            elif 'ASSIGNED' in action:
                return 'ASSIGNED'
            elif 'EXPIRED' in action:
                return 'EXPIRED'
            elif 'EXERCISED' in action:
                return 'EXERCISED'
            elif 'BUY' in action:
                return 'BUY'
            elif 'SELL' in action:
                return 'SELL'
            
            return action
        
        opening_action = normalize_action(opening_txs[0].get('action', '')) if opening_txs else None
        closing_action = normalize_action(closing_txs[0].get('action', '')) if closing_txs else None
        
        # Calculate P&L if closed
        pnl = 0
        status = 'OPEN'
        if closing_txs and avg_closing_price is not None:
            status = 'CLOSED'
            if 'EQUITY_OPTION' in str(instrument_type):
                # Options P&L
                if net_quantity > 0:  # Long option
                    pnl = (avg_closing_price - avg_opening_price) * abs(net_quantity) * 100
                else:  # Short option
                    pnl = (avg_opening_price - avg_closing_price) * abs(net_quantity) * 100
            else:
                # Stock P&L
                if net_quantity > 0:  # Long stock
                    pnl = (avg_closing_price - avg_opening_price) * abs(net_quantity)
                else:  # Short stock
                    pnl = (avg_opening_price - avg_closing_price) * abs(net_quantity)
        
        # Handle cases where we don't have opening transactions
        if not opening_txs and closing_txs:
            # For pure closing orders, use the first closing transaction as a proxy for opening
            # but set the opening price to 0 and opening action to indicate it's a closing-only position
            opening_transaction_id = closing_txs[0].get('id')
            opening_price_for_insert = 0.0  # No opening price available
            opening_action_for_insert = 'CLOSING_ONLY'
        else:
            opening_transaction_id = opening_txs[0].get('id') if opening_txs else None
            opening_price_for_insert = avg_opening_price
            opening_action_for_insert = opening_action
        
        # Insert consolidated position
        cursor.execute("""
            INSERT INTO positions_new (
                order_id, account_number, symbol, underlying, instrument_type,
                option_type, strike, expiration, quantity, opening_price,
                closing_price, opening_transaction_id, closing_transaction_id,
                opening_action, closing_action, status, pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, order[1], symbol, underlying, instrument_type,
            option_type, strike, expiration, net_quantity, opening_price_for_insert,
            avg_closing_price, 
            opening_transaction_id, 
            closing_txs[0].get('id') if closing_txs else None,
            opening_action_for_insert, closing_action, status, pnl
        ))
        
        print(f"Created consolidated position: {symbol}, qty={net_quantity}, status={status}")

def apply_fix_to_specific_orders():
    """Apply the fix specifically to the problematic orders"""
    
    db_path = Path("trade_journal.db")
    if not db_path.exists():
        print("Database not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Applying closing order fix to specific orders...")
        
        # Delete and recreate the position for order 375108991
        order_id = '375108991'
        
        print(f"Deleting existing position for order {order_id}")
        cursor.execute("DELETE FROM positions_new WHERE order_id = ?", (order_id,))
        
        # Get the transactions for this order
        cursor.execute("""
            SELECT * FROM raw_transactions 
            WHERE order_id = ? 
            ORDER BY executed_at
        """, (order_id,))
        
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        transactions = [dict(zip(columns, row)) for row in rows]
        
        if not transactions:
            print(f"No transactions found for order {order_id}")
            return
        
        # Create the order info structure
        order_info = {
            'order_id': order_id,
            'transactions': transactions
        }
        
        print(f"Recreating position for order {order_id} with {len(transactions)} transactions")
        
        # Apply the fixed consolidation logic
        create_positions_from_order_fixed(order_info, conn)
        
        conn.commit()
        
        # Verify the fix
        cursor.execute("SELECT * FROM positions_new WHERE order_id = ?", (order_id,))
        pos = cursor.fetchone()
        if pos:
            print(f"✅ Fixed position: quantity={pos[9]}, closing_price={pos[11]}, status={pos[16]}")
            
            if pos[9] == 9:  # Should be 9 contracts
                print("🎉 SUCCESS: Order 375108991 now shows correct quantity of 9 contracts!")
            else:
                print(f"❌ Issue: Expected 9 contracts, got {pos[9]}")
        else:
            print("❌ Position not found after fix")
            
    except Exception as e:
        print(f"Error applying fix: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    apply_fix_to_specific_orders()