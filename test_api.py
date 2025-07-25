#!/usr/bin/env python3
"""Test the API endpoint with consolidation"""

import requests
import json

# Test the chains API endpoint
try:
    response = requests.get('http://localhost:8000/api/chains?limit=5')
    
    if response.status_code == 200:
        data = response.json()
        chains = data.get('chains', [])
        
        print(f"Found {len(chains)} chains")
        
        # Look for the chain containing order 375557880
        for chain in chains:
            orders = chain.get('orders', [])
            for order in orders:
                if order['order_id'] == '375557880':
                    print(f"\nFound order 375557880:")
                    print(f"  Order type: {order['order_type']}")
                    print(f"  Total P&L: ${order['total_pnl']}")
                    print(f"  Positions: {len(order['positions'])}")
                    
                    for i, pos in enumerate(order['positions']):
                        print(f"    Position {i+1}:")
                        print(f"      Symbol: {pos['symbol']}")
                        print(f"      Quantity: {pos['quantity']}")
                        print(f"      Fill Count: {pos['fill_count']}")
                        print(f"      Action: {pos['opening_action']}")
                        print(f"      Price: ${pos['opening_price']}")
                        print(f"      P&L: ${pos['pnl']}")
                    break
            else:
                continue
            break
        else:
            print("Order 375557880 not found in chains")
            
        # Look for a multi-leg strategy
        for chain in chains:
            orders = chain.get('orders', [])
            for order in orders:
                positions = order.get('positions', [])
                if len(positions) > 1:
                    symbols = set(pos['symbol'] for pos in positions)
                    if len(symbols) > 1:
                        print(f"\nFound multi-leg order {order['order_id']}:")
                        print(f"  Strategy: {order.get('strategy_type', 'Unknown')}")
                        print(f"  Positions: {len(positions)}")
                        print(f"  Symbols: {len(symbols)}")
                        
                        for i, pos in enumerate(positions):
                            print(f"    Position {i+1}: {pos['symbol']} - Qty: {pos['quantity']}, Fill Count: {pos['fill_count']}")
                        break
            else:
                continue
            break
    else:
        print(f"API request failed with status {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"Error testing API: {e}")