#!/usr/bin/env python3
"""
Implement Order and Position model as per requirements
This script adds the necessary tables and migrates existing data
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import json
from loguru import logger

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
            opening_price REAL NOT NULL,
            closing_price REAL,
            opening_transaction_id TEXT NOT NULL,
            closing_transaction_id TEXT,
            opening_action TEXT NOT NULL, -- 'BTO', 'STO', 'BUY', 'SELL'
            closing_action TEXT, -- 'BTC', 'STC', 'SELL', 'BUY', 'EXPIRED', 'ASSIGNED', etc.
            status TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED'
            pnl REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (account_number) REFERENCES accounts(account_number)
        )
    """)
    
    # Create Order Chains table for tracking relationships
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_chains (
            chain_id TEXT PRIMARY KEY,
            underlying TEXT NOT NULL,
            account_number TEXT NOT NULL,
            opening_order_id TEXT NOT NULL,
            strategy_type TEXT NOT NULL, -- From opening order
            chain_status TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED'
            total_pnl REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (opening_order_id) REFERENCES orders(order_id),
            FOREIGN KEY (account_number) REFERENCES accounts(account_number)
        )
    """)
    
    # Create Order Chain Members table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_chain_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL, -- Order in the chain
            FOREIGN KEY (chain_id) REFERENCES order_chains(chain_id),
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            UNIQUE(chain_id, order_id)
        )
    """)
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_underlying ON orders(underlying)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_order ON positions_new(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_account ON positions_new(account_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions_new(symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chains_account ON order_chains(account_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_chain_members_chain ON order_chain_members(chain_id)")
    
    logger.info("Created Orders and Positions tables successfully")

def detect_order_type(transactions):
    """Detect if an order is OPENING, CLOSING, or ROLLING based on its transactions"""
    has_opening = False
    has_closing = False
    
    for tx in transactions:
        action = str(tx.get('action', '')).upper()
        
        # Check for closing actions
        if any(close_action in action for close_action in ['BTC', 'STC', 'CLOSE', 'RECEIVE_DELIVER', 
                                                           'ASSIGNED', 'EXPIRED', 'EXERCISED']):
            has_closing = True
        # Check for opening actions
        elif any(open_action in action for open_action in ['BTO', 'STO', 'OPEN']):
            has_opening = True
    
    if has_opening and has_closing:
        return 'ROLLING'
    elif has_closing:
        return 'CLOSING'
    else:
        return 'OPENING'

def group_transactions_by_order(conn):
    """Group raw transactions by order_id"""
    cursor = conn.cursor()
    
    # Get all transactions with order_ids
    cursor.execute("""
        SELECT * FROM raw_transactions 
        WHERE order_id IS NOT NULL AND order_id != ''
        ORDER BY account_number, order_id, executed_at
    """)
    
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    
    # Group by order_id
    orders = {}
    for row in rows:
        tx = dict(zip(columns, row))
        order_id = tx['order_id']
        
        if order_id not in orders:
            orders[order_id] = {
                'order_id': order_id,
                'account_number': tx['account_number'],
                'transactions': []
            }
        
        orders[order_id]['transactions'].append(tx)
    
    logger.info(f"Found {len(orders)} unique orders from transactions")
    return orders

def create_order_from_transactions(order_data, conn):
    """Create an Order record from grouped transactions"""
    transactions = order_data['transactions']
    if not transactions:
        return None
    
    # Sort transactions by time
    transactions.sort(key=lambda x: x.get('executed_at', ''))
    
    # Extract order details
    first_tx = transactions[0]
    order_id = order_data['order_id']
    account_number = order_data['account_number']
    
    # Get underlying - prefer underlying_symbol, fallback to symbol
    underlying = first_tx.get('underlying_symbol') or first_tx.get('symbol', 'UNKNOWN')
    
    # Parse order date from first transaction
    order_date = first_tx.get('executed_at', '')[:10] if first_tx.get('executed_at') else datetime.now().date()
    
    # Detect order type
    order_type = detect_order_type(transactions)
    
    # Calculate total quantity (sum of all transaction quantities)
    total_quantity = sum(abs(tx.get('quantity', 0)) for tx in transactions)
    
    # Check for system-generated transactions
    has_assignment = False
    has_expiration = False
    has_exercise = False
    
    for tx in transactions:
        action = str(tx.get('action', '')).upper()
        description = str(tx.get('description', '')).upper()
        sub_type = str(tx.get('transaction_sub_type', '')).upper()
        
        if any(indicator in action + description + sub_type for indicator in ['ASSIGNED', 'ASSIGNMENT']):
            has_assignment = True
        if any(indicator in action + description + sub_type for indicator in ['EXPIRED', 'EXPIRATION']):
            has_expiration = True
        if any(indicator in action + description + sub_type for indicator in ['EXERCISE', 'EXERCISED']):
            has_exercise = True
    
    cursor = conn.cursor()
    
    # Insert order
    cursor.execute("""
        INSERT OR IGNORE INTO orders (
            order_id, account_number, underlying, order_type, order_date,
            status, total_quantity, has_assignment, has_expiration, has_exercise
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id, account_number, underlying, order_type, order_date,
        'OPEN', total_quantity, has_assignment, has_expiration, has_exercise
    ))
    
    return {
        'order_id': order_id,
        'order_type': order_type,
        'transactions': transactions
    }

def create_positions_from_order(order_info, conn):
    """Create Position records from an order's transactions"""
    order_id = order_info['order_id']
    transactions = order_info['transactions']
    
    cursor = conn.cursor()
    
    # Get order details
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        logger.error(f"Order {order_id} not found")
        return
    
    # Group transactions by instrument
    positions = {}
    
    for tx in transactions:
        instrument_type = tx.get('instrument_type', '')
        symbol = tx.get('symbol', '')
        
        if not symbol:
            continue
        
        # Create position key
        if 'EQUITY_OPTION' in str(instrument_type):
            # Parse option details from symbol (e.g., "SPX   240117C04700000")
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                # Extract components
                expiration = option_code[:6]  # YYMMDD
                option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                strike_str = option_code[7:] if len(option_code) > 7 else '0'
                strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                
                position_key = (symbol, expiration, strike, option_type)
            else:
                position_key = (symbol,)
        else:
            position_key = (symbol,)
        
        if position_key not in positions:
            positions[position_key] = {
                'symbol': symbol,
                'instrument_type': instrument_type,
                'transactions': []
            }
        
        positions[position_key]['transactions'].append(tx)
    
    # Create position records
    for position_key, position_data in positions.items():
        symbol = position_data['symbol']
        instrument_type = position_data['instrument_type']
        position_txs = position_data['transactions']
        
        # Determine opening and closing transactions
        opening_tx = None
        closing_tx = None
        
        for tx in position_txs:
            action = str(tx.get('action', '')).upper()
            
            if any(open_action in action for open_action in ['BTO', 'STO', 'OPEN']) and not opening_tx:
                opening_tx = tx
            elif any(close_action in action for close_action in ['BTC', 'STC', 'CLOSE', 'ASSIGNED', 'EXPIRED']):
                closing_tx = tx
        
        if not opening_tx:
            # If no explicit opening, use first transaction
            opening_tx = position_txs[0]
        
        # Extract position details
        underlying = opening_tx.get('underlying_symbol') or opening_tx.get('symbol', '')
        quantity = opening_tx.get('quantity', 0)
        
        # Make quantity negative for short positions
        action = str(opening_tx.get('action', '')).upper()
        if 'SELL' in action or 'STO' in action:
            quantity = -abs(quantity)
        else:
            quantity = abs(quantity)
        
        opening_price = opening_tx.get('price', 0)
        closing_price = closing_tx.get('price', 0) if closing_tx else None
        
        # Parse option details if applicable
        option_type = None
        strike = None
        expiration = None
        
        if 'EQUITY_OPTION' in str(instrument_type):
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                expiration_str = option_code[:6]  # YYMMDD
                option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                strike_str = option_code[7:] if len(option_code) > 7 else '0'
                strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                
                # Convert expiration to date
                year = 2000 + int(expiration_str[:2])
                month = int(expiration_str[2:4])
                day = int(expiration_str[4:6])
                expiration = f"{year:04d}-{month:02d}-{day:02d}"
        
        # Normalize actions
        opening_action = normalize_action(opening_tx.get('action', ''))
        closing_action = normalize_action(closing_tx.get('action', '')) if closing_tx else None
        
        # Calculate P&L if closed
        pnl = 0
        status = 'OPEN'
        if closing_tx and closing_price is not None:
            status = 'CLOSED'
            if 'EQUITY_OPTION' in str(instrument_type):
                # Options P&L
                if quantity > 0:  # Long option
                    pnl = (closing_price - opening_price) * quantity * 100
                else:  # Short option
                    pnl = (opening_price - closing_price) * abs(quantity) * 100
            else:
                # Stock P&L
                if quantity > 0:  # Long stock
                    pnl = (closing_price - opening_price) * quantity
                else:  # Short stock
                    pnl = (opening_price - closing_price) * abs(quantity)
        
        # Insert position
        cursor.execute("""
            INSERT INTO positions_new (
                order_id, account_number, symbol, underlying, instrument_type,
                option_type, strike, expiration, quantity, opening_price,
                closing_price, opening_transaction_id, closing_transaction_id,
                opening_action, closing_action, status, pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, order[1], symbol, underlying, instrument_type,
            option_type, strike, expiration, quantity, opening_price,
            closing_price, opening_tx.get('id'), closing_tx.get('id') if closing_tx else None,
            opening_action, closing_action, status, pnl
        ))

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

def recognize_order_strategies(conn):
    """Recognize strategy types for orders based on their positions"""
    cursor = conn.cursor()
    
    # Get all orders that need strategy recognition
    cursor.execute("SELECT order_id FROM orders WHERE strategy_type IS NULL")
    order_ids = [row[0] for row in cursor.fetchall()]
    
    for order_id in order_ids:
        # Get positions for this order
        cursor.execute("""
            SELECT * FROM positions_new WHERE order_id = ?
            ORDER BY symbol
        """, (order_id,))
        
        positions = cursor.fetchall()
        if not positions:
            continue
        
        strategy_type = determine_strategy_from_positions(positions)
        
        # Update order with strategy type
        cursor.execute("""
            UPDATE orders SET strategy_type = ? WHERE order_id = ?
        """, (strategy_type, order_id))

def determine_strategy_from_positions(positions):
    """Determine strategy type from position data"""
    option_positions = [p for p in positions if 'OPTION' in str(p[5])]  # instrument_type
    stock_positions = [p for p in positions if 'EQUITY' in str(p[5]) and 'OPTION' not in str(p[5])]
    
    # Single position strategies
    if len(positions) == 1:
        pos = positions[0]
        if 'OPTION' in str(pos[5]):  # option position
            if pos[9] > 0:  # quantity positive = long
                return 'Long Call' if pos[6] == 'Call' else 'Long Put'  # option_type
            else:  # short
                return 'Naked Call' if pos[6] == 'Call' else 'Cash Secured Put'
        else:  # stock position
            return 'Long Stock' if pos[9] > 0 else 'Short Stock'
    
    # Two position strategies
    elif len(positions) == 2:
        if len(option_positions) == 2:
            # Both options - check for spreads/straddles/strangles
            opt1, opt2 = sorted(option_positions, key=lambda x: x[7] or 0)  # sort by strike
            
            # Same expiration
            if opt1[8] == opt2[8]:  # same expiration
                if opt1[6] == opt2[6]:  # same option type
                    # Vertical spread
                    if opt1[9] > 0 and opt2[9] < 0:  # long/short
                        return 'Bull Call Spread' if opt1[6] == 'Call' else 'Bull Put Spread'
                    elif opt1[9] < 0 and opt2[9] > 0:  # short/long
                        return 'Bear Call Spread' if opt1[6] == 'Call' else 'Bear Put Spread'
                else:
                    # Different types
                    if opt1[7] == opt2[7]:  # same strike
                        return 'Straddle'
                    else:
                        return 'Strangle'
            else:
                # Different expirations
                return 'Calendar Spread' if opt1[7] == opt2[7] else 'Diagonal Spread'
        
        elif len(option_positions) == 1 and len(stock_positions) == 1:
            # Stock + option combo
            opt = option_positions[0]
            if opt[6] == 'Call' and opt[9] < 0:  # short call
                return 'Covered Call'
            else:
                return 'Complex Strategy'
    
    # Multi-leg strategies
    elif len(option_positions) == 4:
        calls = [p for p in option_positions if p[6] == 'Call']
        puts = [p for p in option_positions if p[6] == 'Put']
        
        if len(calls) == 2 and len(puts) == 2:
            # Check for Iron Condor/Butterfly
            all_strikes = sorted(set(p[7] for p in option_positions if p[7]))
            if len(all_strikes) == 3:
                return 'Iron Butterfly'
            elif len(all_strikes) == 4:
                return 'Iron Condor'
    
    elif len(option_positions) == 3:
        # Check for butterfly
        if all(p[6] == option_positions[0][6] for p in option_positions):  # same type
            return 'Butterfly'
    
    return 'Complex Strategy'

def detect_order_chains(conn):
    """Detect order chains based on rolling relationships"""
    cursor = conn.cursor()
    
    # First recognize strategies for all orders
    recognize_order_strategies(conn)
    conn.commit()
    
    # Get all orders grouped by underlying and account
    cursor.execute("""
        SELECT * FROM orders
        ORDER BY account_number, underlying, order_date
    """)
    
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    
    # Group by account and underlying
    by_account_underlying = {}
    for row in rows:
        order = dict(zip(columns, row))
        key = (order['account_number'], order['underlying'])
        
        if key not in by_account_underlying:
            by_account_underlying[key] = []
        
        by_account_underlying[key].append(order)
    
    # Detect chains
    chain_id_counter = 1
    
    for (account, underlying), orders in by_account_underlying.items():
        processed_orders = set()
        
        for order in orders:
            if order['order_id'] in processed_orders:
                continue
            
            # Start a new chain
            chain_id = f"CHAIN_{account}_{underlying}_{chain_id_counter:04d}"
            chain_id_counter += 1
            
            chain_members = [order]
            processed_orders.add(order['order_id'])
            
            # Look for rolling orders that continue this chain
            if order['order_type'] != 'CLOSING':
                for candidate in orders:
                    if (candidate['order_id'] not in processed_orders and
                        candidate['order_type'] == 'ROLLING' and
                        is_roll_continuation(order, candidate)):
                        
                        chain_members.append(candidate)
                        processed_orders.add(candidate['order_id'])
                        
                        # Update linked_order_id
                        cursor.execute("""
                            UPDATE orders SET linked_order_id = ?
                            WHERE order_id = ?
                        """, (order['order_id'], candidate['order_id']))
            
            # Create chain record
            if chain_members:
                opening_order = chain_members[0]
                
                # Calculate chain P&L
                cursor.execute("""
                    SELECT SUM(pnl) FROM positions_new
                    WHERE order_id IN ({})
                """.format(','.join('?' * len(chain_members))), 
                [m['order_id'] for m in chain_members])
                
                total_pnl = cursor.fetchone()[0] or 0
                
                # Determine chain status
                last_order = chain_members[-1]
                chain_status = 'CLOSED' if last_order['order_type'] == 'CLOSING' else 'OPEN'
                
                # Use strategy_type from opening order, default to 'UNKNOWN' if null
                strategy_type = opening_order.get('strategy_type') or 'UNKNOWN'
                
                # Insert chain
                cursor.execute("""
                    INSERT INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id,
                        strategy_type, chain_status, total_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain_id, underlying, account, opening_order['order_id'],
                    strategy_type, chain_status, total_pnl
                ))
                
                # Insert chain members
                for i, member in enumerate(chain_members):
                    cursor.execute("""
                        INSERT INTO order_chain_members (
                            chain_id, order_id, sequence_number
                        ) VALUES (?, ?, ?)
                    """, (chain_id, member['order_id'], i + 1))

def is_roll_continuation(prev_order, candidate_order):
    """Check if candidate order is a roll continuation of previous order"""
    # Must be within reasonable time frame (30 days)
    try:
        from datetime import datetime, timedelta
        prev_date = datetime.fromisoformat(prev_order['order_date'])
        candidate_date = datetime.fromisoformat(candidate_order['order_date'])
        
        if candidate_date <= prev_date or (candidate_date - prev_date) > timedelta(days=30):
            return False
    except:
        pass
    
    return True

def update_order_pnl(conn):
    """Update P&L for all orders"""
    cursor = conn.cursor()
    
    # Update order P&L from positions
    cursor.execute("""
        UPDATE orders 
        SET total_pnl = (
            SELECT COALESCE(SUM(pnl), 0) 
            FROM positions_new 
            WHERE positions_new.order_id = orders.order_id
        )
    """)
    
    # Update order status based on positions
    cursor.execute("""
        UPDATE orders
        SET status = CASE
            WHEN (SELECT COUNT(*) FROM positions_new WHERE order_id = orders.order_id AND status = 'OPEN') = 0
            THEN 'CLOSED'
            ELSE 'OPEN'
        END
    """)

def main():
    """Run the migration"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        logger.error("Database not found")
        return
    
    logger.info("Starting Order/Position model implementation")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Create new tables
        create_order_position_tables(conn)
        conn.commit()
        
        # Check if raw_transactions table exists
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='raw_transactions'
        """)
        
        if not cursor.fetchone():
            logger.warning("raw_transactions table not found. Please run add_order_id_support.py first")
            return
        
        # Group transactions by order_id
        logger.info("Grouping transactions by order_id...")
        orders = group_transactions_by_order(conn)
        
        # Create Order records
        logger.info("Creating Order records...")
        order_infos = []
        for order_id, order_data in orders.items():
            order_info = create_order_from_transactions(order_data, conn)
            if order_info:
                order_infos.append(order_info)
        
        conn.commit()
        logger.info(f"Created {len(order_infos)} orders")
        
        # Create Position records
        logger.info("Creating Position records...")
        for order_info in order_infos:
            create_positions_from_order(order_info, conn)
        
        conn.commit()
        
        # Update order P&L
        logger.info("Updating order P&L...")
        update_order_pnl(conn)
        conn.commit()
        
        # Detect order chains
        logger.info("Detecting order chains...")
        detect_order_chains(conn)
        conn.commit()
        
        # Update chain P&L
        cursor.execute("""
            UPDATE order_chains
            SET total_pnl = (
                SELECT COALESCE(SUM(o.total_pnl), 0)
                FROM orders o
                JOIN order_chain_members ocm ON o.order_id = ocm.order_id
                WHERE ocm.chain_id = order_chains.chain_id
            )
        """)
        conn.commit()
        
        logger.info("Order/Position model implementation completed successfully!")
        
        # Print summary
        cursor.execute("SELECT COUNT(*) FROM orders")
        order_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM positions_new")
        position_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM order_chains")
        chain_count = cursor.fetchone()[0]
        
        logger.info(f"Summary: {order_count} orders, {position_count} positions, {chain_count} chains")
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()