#!/usr/bin/env python3
"""Test API for specific order 375557880"""

import requests
import json

# Test for order 375557880 specifically
response = requests.get('http://localhost:8000/api/chains?limit=1000')
if response.status_code == 200:
    data = response.json()
    chains = data.get('chains', [])
    
    found = False
    for chain in chains:
        orders = chain.get('orders', [])
        for order in orders:
            if order['order_id'] == '375557880':
                print(f'Found order 375557880 in chain {chain["chain_id"]}')
                print(f'  Positions before consolidation: 19 (expected)')
                print(f'  Positions after consolidation: {len(order["positions"])}')
                if len(order["positions"]) > 0:
                    pos = order["positions"][0]
                    print(f'  Consolidated quantity: {pos["quantity"]}')
                    print(f'  Fill count: {pos["fill_count"]}')
                    print(f'  P&L: ${pos["pnl"]}')
                found = True
                break
        if found:
            break
    
    if not found:
        print('Order 375557880 not found')
else:
    print(f'API error: {response.status_code}')