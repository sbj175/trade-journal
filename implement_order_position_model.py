#!/usr/bin/env python3
"""
Updated Order Position Model Implementation - Fixed Core Logic
Addresses position consolidation, expiration linking, and position-based order chain linking
"""

import sqlite3
from datetime import datetime, date
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
        logger.error(f"Order {order_id} not found")
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
            # Parse option details from symbol (e.g., "IBIT  250404C00050000")
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
                    logger.warning(f"Could not parse option symbol {symbol}: {e}")
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
        
        if not opening_txs:
            # For pure closing orders, we need to handle this differently
            # Don't artificially create opening transactions from closing transactions
            # Instead, we'll create a position that represents the closing of an external position
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
        
        # Determine net quantity 
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
                    logger.warning(f"Could not parse option details for {symbol}: {e}")
        
        # Normalize actions
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
            option_type, strike, expiration, net_quantity, avg_opening_price,
            avg_closing_price, 
            opening_txs[0].get('id') if opening_txs else None, 
            closing_txs[0].get('id') if closing_txs else None,
            opening_action, closing_action, status, pnl
        ))
        
        logger.debug(f"Created consolidated position: {symbol}, qty={net_quantity}, opening=${avg_opening_price:.2f}")

def link_expiration_transactions_to_positions(conn):
    """
    FIXED: Link expiration transactions (with order_id=NULL) to their original positions
    """
    cursor = conn.cursor()
    
    # Find expiration transactions without order_id
    cursor.execute("""
        SELECT id, symbol, quantity, executed_at, description, account_number
        FROM raw_transactions
        WHERE order_id IS NULL 
        AND (description LIKE '%expiration%' OR description LIKE '%Expiration%'
             OR description LIKE '%due to expiration%')
    """)
    
    expiration_txs = cursor.fetchall()
    logger.info(f"Found {len(expiration_txs)} expiration transactions to link")
    
    for tx_id, symbol, quantity, executed_at, description, account_number in expiration_txs:
        logger.info(f"Processing expiration: {symbol}, qty={quantity}, account={account_number}")
        
        # Find matching open position by symbol, account, and quantity
        cursor.execute("""
            SELECT p.position_id, p.order_id, p.quantity
            FROM positions_new p
            WHERE p.symbol = ? 
            AND p.account_number = ?
            AND p.status = 'OPEN'
            AND ABS(p.quantity) = ABS(?)
            ORDER BY p.created_at ASC
            LIMIT 1
        """, (symbol, account_number, quantity))
        
        matching_position = cursor.fetchone()
        
        if matching_position:
            position_id, order_id, pos_quantity = matching_position
            
            logger.info(f"Linking expiration to position {position_id} in order {order_id}")
            
            # Calculate P&L for expired position (short options = premium collected)
            cursor.execute("SELECT opening_price FROM positions_new WHERE position_id = ?", (position_id,))
            opening_price = cursor.fetchone()[0]
            
            # For expired options: short positions keep premium, long positions lose premium
            if pos_quantity < 0:  # Short position - we keep the premium
                option_pnl = abs(pos_quantity) * opening_price * 100
            else:  # Long position - we lose the premium
                option_pnl = -abs(pos_quantity) * opening_price * 100
            
            # Update the position as expired
            cursor.execute("""
                UPDATE positions_new
                SET closing_action = 'EXPIRED',
                    closing_price = 0.0,
                    closing_transaction_id = ?,
                    status = 'CLOSED',
                    pnl = ?
                WHERE position_id = ?
            """, (tx_id, option_pnl, position_id))
            
            # Update the order status
            cursor.execute("""
                UPDATE orders 
                SET status = 'CLOSED',
                    has_expiration = 1,
                    total_pnl = (
                        SELECT COALESCE(SUM(pnl), 0) 
                        FROM positions_new 
                        WHERE order_id = orders.order_id
                    )
                WHERE order_id = ?
            """, (order_id,))
            
            logger.info(f"Updated order {order_id} as CLOSED with expiration, P&L=${option_pnl:.2f}")
        else:
            logger.warning(f"No matching position found for expiration: {symbol}, qty={quantity}, account={account_number}")
    
    conn.commit()

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
        
        strategy_type = determine_strategy_from_positions_enhanced(positions, order_id, conn)
        
        # Update order with strategy type
        cursor.execute("""
            UPDATE orders SET strategy_type = ? WHERE order_id = ?
        """, (strategy_type, order_id))

def determine_strategy_from_positions_enhanced(positions, order_id, conn):
    """Enhanced strategy detection that considers historical stock positions for covered calls"""
    # First try the standard logic
    standard_strategy = determine_strategy_from_positions(positions)
    
    # If it's a single short call, check if it could be a covered call
    if (standard_strategy == 'Naked Call' and len(positions) == 1 and 
        'OPTION' in str(positions[0][5]) and positions[0][6] == 'Call' and positions[0][9] < 0):
        
        cursor = conn.cursor()
        
        # Get order details
        cursor.execute("SELECT account_number, order_date, underlying FROM orders WHERE order_id = ?", (order_id,))
        order_info = cursor.fetchone()
        if not order_info:
            return standard_strategy
            
        account_number, order_date, underlying = order_info
        
        # Look for existing long stock positions at or before order time
        # Include both regular order positions AND transfer transactions (ACAT, etc.)
        cursor.execute("""
            SELECT COALESCE(SUM(p.quantity), 0) as total_shares
            FROM orders o
            JOIN positions_new p ON o.order_id = p.order_id
            WHERE o.account_number = ?
            AND p.symbol = ?
            AND p.instrument_type LIKE '%EQUITY%'
            AND p.instrument_type NOT LIKE '%OPTION%'
            AND o.order_date <= ?
            AND p.quantity > 0
            AND p.status = 'OPEN'
        """, (account_number, underlying, order_date))
        
        order_shares = cursor.fetchone()[0] or 0
        
        # ALSO check for transfer transactions (ACAT, etc.) with NULL order_id
        cursor.execute("""
            SELECT COALESCE(SUM(rt.quantity), 0) as transfer_shares
            FROM raw_transactions rt
            WHERE rt.account_number = ?
            AND rt.symbol = ?
            AND rt.order_id IS NULL
            AND rt.quantity > 0
            AND rt.transaction_type = 'Receive Deliver'
            AND rt.transaction_sub_type = 'ACAT'
            AND DATE(rt.executed_at) <= ?
        """, (account_number, underlying, order_date))
        
        transfer_shares = cursor.fetchone()[0] or 0
        total_shares = order_shares + transfer_shares
        
        # If we have long stock positions at or before call sale, consider it a covered call
        # (even if not fully covered, as users may be using partial coverage strategies)
        call_contracts = abs(positions[0][9])  # Number of short call contracts
        shares_needed = call_contracts * 100   # Each contract covers 100 shares
        
        if total_shares > 0:
            coverage_ratio = (total_shares / shares_needed) * 100
            coverage_source = ""
            if order_shares > 0 and transfer_shares > 0:
                coverage_source = f" (orders: {order_shares}, transfers: {transfer_shares})"
            elif order_shares > 0:
                coverage_source = f" (from orders)"
            elif transfer_shares > 0:
                coverage_source = f" (from transfers/ACAT)"
                
            logger.info(f"Order {order_id}: Converting 'Naked Call' to 'Covered Call' "
                       f"({call_contracts} calls, {total_shares} shares of {underlying}, {coverage_ratio:.1f}% coverage{coverage_source})")
            return 'Covered Call'
    
    return standard_strategy

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
                    # Check quantities for ratio spreads
                    qty1, qty2 = abs(opt1[9]), abs(opt2[9])
                    
                    # Check for Zebra pattern (2:1 ratio with long at lower strike)
                    if opt1[6] == 'Call' and opt1[9] > 0 and opt2[9] < 0:
                        # Long calls at lower strike, short calls at higher strike
                        # Check for 2:1 ratio (allowing for multiples like 8:4, 6:3, etc.)
                        ratio = qty1 / qty2 if qty2 > 0 else 0
                        if abs(ratio - 2.0) < 0.1:  # 2:1 ratio (with small tolerance)
                            return 'Zebra'
                        elif qty1 != qty2:  # Other ratio
                            return f'Call Ratio Spread ({qty1}:{qty2})'
                        else:  # 1:1 ratio
                            return 'Bull Call Spread'
                    
                    # Check for Put ratio spreads
                    elif opt1[6] == 'Put' and opt1[9] > 0 and opt2[9] < 0:
                        if qty1 != qty2:
                            return f'Put Ratio Spread ({qty1}:{qty2})'
                        else:
                            return 'Bull Put Spread'
                    
                    # Standard vertical spreads
                    elif opt1[9] > 0 and opt2[9] < 0:  # long/short
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

def detect_order_chains_fixed(conn):
    """
    FIXED: Detect order chains with proper position-based linking
    """
    cursor = conn.cursor()
    
    # First recognize strategies for all orders
    recognize_order_strategies(conn)
    conn.commit()
    
    # Get all orders grouped by account
    cursor.execute("""
        SELECT * FROM orders
        ORDER BY account_number, order_date
    """)
    
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    
    # Group by account
    by_account = {}
    for row in rows:
        order = dict(zip(columns, row))
        account = order['account_number']
        
        if account not in by_account:
            by_account[account] = []
        
        by_account[account].append(order)
    
    # Detect chains
    chain_id_counter = 1
    
    for account, orders in by_account.items():
        processed_orders = set()
        
        for order in orders:
            if order['order_id'] in processed_orders:
                continue
            
            # FIXED: Exclude expired/assigned orders from chain linking
            # They should be standalone chains
            is_system_closed = (order['has_expiration'] or order['has_assignment'] or order['has_exercise'])
            
            # Start a new chain
            chain_id = f"CHAIN_{account}_{order['underlying']}_{chain_id_counter:04d}"
            chain_id_counter += 1
            
            chain_members = [order]
            processed_orders.add(order['order_id'])
            
            # FIXED: Build chains by finding continuation orders (ROLLING or CLOSING)
            # Use position-based matching for proper linking
            if not is_system_closed and order['order_type'] != 'CLOSING':
                current_order = order
                
                # Continue building chain by finding rolling orders that close current positions
                while True:
                    # FIXED: Find ALL continuations from current order, not just the first one
                    continuations_found = []
                    
                    for candidate in orders:
                        if (candidate['order_id'] not in processed_orders and
                            candidate['order_type'] in ['ROLLING', 'CLOSING'] and
                            is_position_based_roll_continuation(current_order, candidate, conn)):
                            
                            continuations_found.append(candidate)
                    
                    if not continuations_found:
                        break
                    
                    # Sort continuations by date to maintain chronological order
                    continuations_found.sort(key=lambda x: x['order_date'])
                    
                    # Add all continuations to the chain
                    for continuation in continuations_found:
                        chain_members.append(continuation)
                        processed_orders.add(continuation['order_id'])
                        
                        # Update linked_order_id
                        cursor.execute("""
                            UPDATE orders SET linked_order_id = ?
                            WHERE order_id = ?
                        """, (current_order['order_id'], continuation['order_id']))
                    
                    # If any continuations are CLOSING orders, stop building the chain
                    has_closing = any(c['order_type'] == 'CLOSING' for c in continuations_found)
                    if has_closing:
                        break
                    
                    # Continue from the last (most recent) continuation for further chain building
                    current_order = continuations_found[-1]
            
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
                
                # FIXED: Determine chain status more accurately
                has_closing = any(m['order_type'] == 'CLOSING' for m in chain_members)
                has_expiration = any(m['has_expiration'] for m in chain_members)
                has_assignment = any(m['has_assignment'] for m in chain_members)
                has_exercise = any(m['has_exercise'] for m in chain_members)
                
                # Chain is closed if it has explicit closing orders OR system closures (expiration/assignment/exercise)
                chain_status = 'CLOSED' if (has_closing or has_expiration or has_assignment or has_exercise) else 'OPEN'
                
                # Use strategy_type from opening order, default to 'UNKNOWN' if null
                strategy_type = opening_order.get('strategy_type') or 'UNKNOWN'
                
                # Insert chain
                cursor.execute("""
                    INSERT INTO order_chains (
                        chain_id, underlying, account_number, opening_order_id,
                        strategy_type, chain_status, total_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    chain_id, opening_order['underlying'], account, opening_order['order_id'],
                    strategy_type, chain_status, total_pnl
                ))
                
                # Insert chain members
                for i, member in enumerate(chain_members):
                    cursor.execute("""
                        INSERT INTO order_chain_members (
                            chain_id, order_id, sequence_number
                        ) VALUES (?, ?, ?)
                    """, (chain_id, member['order_id'], i + 1))
                
                logger.info(f"Created chain {chain_id} with {len(chain_members)} orders, status={chain_status}")

def is_position_based_roll_continuation(prev_order, candidate_order, conn):
    """
    FIXED: Check if candidate order is a roll continuation based on matching positions
    Per requirements: closing transactions in rolling order must match exact positions
    from earlier open order (same account, underlying, expiration, strike, option type)
    """
    cursor = conn.cursor()
    
    # Must be within reasonable time frame (30 days) and after previous order
    try:
        from datetime import datetime, timedelta
        prev_date = datetime.fromisoformat(prev_order['order_date'])
        candidate_date = datetime.fromisoformat(candidate_order['order_date'])
        
        if candidate_date <= prev_date or (candidate_date - prev_date) > timedelta(days=30):
            return False
    except:
        return False
    
    # Must be same account and underlying
    if (prev_order['account_number'] != candidate_order['account_number'] or
        prev_order['underlying'] != candidate_order['underlying']):
        return False
    
    # Get open positions from previous order
    cursor.execute("""
        SELECT symbol, underlying, option_type, strike, expiration, quantity
        FROM positions_new 
        WHERE order_id = ? AND status = 'OPEN'
    """, (prev_order['order_id'],))
    
    prev_open_positions = cursor.fetchall()
    if not prev_open_positions:
        return False
    
    # Get closing transactions from candidate rolling order
    cursor.execute("""
        SELECT rt.symbol, rt.underlying_symbol, rt.quantity, rt.action
        FROM raw_transactions rt
        WHERE rt.order_id = ? 
        AND (rt.action LIKE '%BTC%' OR rt.action LIKE '%STC%' OR rt.action LIKE '%CLOSE%')
    """, (candidate_order['order_id'],))
    
    closing_transactions = cursor.fetchall()
    if not closing_transactions:
        return False
    
    # Convert closing transactions to position keys for matching
    closing_position_keys = set()
    for tx in closing_transactions:
        symbol = tx[0]
        instrument_type = 'EQUITY_OPTION' if symbol and len(symbol.split()) >= 2 else 'EQUITY'
        
        if instrument_type == 'EQUITY_OPTION':
            parts = symbol.split()
            if len(parts) >= 2:
                option_code = parts[1]
                try:
                    expiration = option_code[:6]  # YYMMDD
                    option_type = 'Call' if 'C' in option_code[6:8] else 'Put'
                    strike_str = option_code[8:] if len(option_code) > 8 else option_code[7:]
                    strike = float(strike_str) / 1000 if strike_str.isdigit() else 0
                    
                    # Convert expiration to same format as positions table
                    year = 2000 + int(expiration[:2])
                    month = int(expiration[2:4])
                    day = int(expiration[4:6])
                    exp_date = f"{year:04d}-{month:02d}-{day:02d}"
                    
                    position_key = (symbol.strip(), option_type, strike, exp_date)
                    closing_position_keys.add(position_key)
                except (ValueError, IndexError):
                    continue
        else:
            # Stock position
            position_key = (symbol.strip(), None, None, None)
            closing_position_keys.add(position_key)
    
    # Convert previous open positions to same format for comparison
    prev_position_keys = set()
    for pos in prev_open_positions:
        symbol, underlying, option_type, strike, expiration = pos[:5]
        position_key = (symbol.strip(), option_type, strike, expiration)
        prev_position_keys.add(position_key)
    
    # Check if closing transactions match any previous open positions
    # At least one closing transaction must match a previous open position
    matches = closing_position_keys.intersection(prev_position_keys)
    
    logger.debug(f"Roll check: {prev_order['order_id']} -> {candidate_order['order_id']}")
    logger.debug(f"Prev positions: {prev_position_keys}")
    logger.debug(f"Closing positions: {closing_position_keys}")
    logger.debug(f"Matches: {matches}")
    
    return len(matches) > 0

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
    """Run the migration with fixed logic"""
    db_path = Path("trade_journal.db")
    
    if not db_path.exists():
        logger.error("Database not found")
        return
    
    logger.info("Starting FIXED Order/Position model implementation")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check if raw_transactions table exists
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='raw_transactions'
        """)
        
        if not cursor.fetchone():
            logger.warning("raw_transactions table not found. Please run add_order_id_support.py first")
            return
        
        # Drop existing tables to rebuild with fixed logic
        logger.info("Dropping existing Order/Position tables for clean rebuild...")
        cursor.execute("DROP TABLE IF EXISTS order_chain_members")
        cursor.execute("DROP TABLE IF EXISTS order_chains")
        cursor.execute("DROP TABLE IF EXISTS positions_new")
        cursor.execute("DROP TABLE IF EXISTS orders")
        conn.commit()
        
        # Create new tables
        create_order_position_tables(conn)
        conn.commit()
        
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
        
        # Create Position records with FIXED consolidation logic
        logger.info("Creating consolidated Position records...")
        for order_info in order_infos:
            create_positions_from_order_fixed(order_info, conn)
        
        conn.commit()
        
        # FIXED: Link expiration transactions
        logger.info("Linking expiration transactions to positions...")
        link_expiration_transactions_to_positions(conn)
        
        # Update order P&L
        logger.info("Updating order P&L...")
        update_order_pnl(conn)
        conn.commit()
        
        # FIXED: Detect order chains with improved logic
        logger.info("Detecting order chains with fixed logic...")
        detect_order_chains_fixed(conn)
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
        
        logger.info("FIXED Order/Position model implementation completed successfully!")
        
        # Print summary
        cursor.execute("SELECT COUNT(*) FROM orders")
        order_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM positions_new")
        position_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM order_chains")
        chain_count = cursor.fetchone()[0]
        
        # Print specific improvements
        cursor.execute("SELECT COUNT(*) FROM orders WHERE has_expiration = 1")
        expired_orders = cursor.fetchone()[0]
        
        logger.info(f"Summary: {order_count} orders, {position_count} positions, {chain_count} chains")
        logger.info(f"Fixed: {expired_orders} orders with proper expiration handling")
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()