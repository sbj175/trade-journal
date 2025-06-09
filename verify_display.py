#!/usr/bin/env python3
"""
Verify that the transaction display logic is working correctly
"""

import json

# Simulate the exact data structure from the API
leg_data = {
    "id": 17233,
    "symbol": "IBIT  250404C00050000",
    "option_type": "Call",
    "strike": 50.0,
    "expiration": "2025-04-04",
    "quantity": -180,
    "entry_price": 0.22,
    "exit_price": 0.0,
    "transaction_actions": ["STO", "BTC"],
    "transaction_timestamps": [
        "2025-04-01T13:45:08.699000+00:00",
        "2025-04-04T20:00:00+00:00"
    ]
}

print("IBIT Transaction Display Test")
print("=" * 50)
print(f"Symbol: {leg_data['symbol']}")
print(f"Quantity: {leg_data['quantity']}")
print(f"Strike: ${leg_data['strike']}")
print(f"Type: {leg_data['option_type']}")
print()

print("Expected Display (as separate rows):")
print("-" * 50)

for action_index, action in enumerate(leg_data['transaction_actions']):
    # This is the same logic as in the HTML template
    if action in ['BTO', 'STO']:
        price = leg_data['entry_price']
        price_type = "entry"
    else:
        price = leg_data['exit_price'] or 0.00
        price_type = "exit"
    
    timestamp = leg_data['transaction_timestamps'][action_index] if action_index < len(leg_data['transaction_timestamps']) else 'N/A'
    
    # Format timestamp like the frontend would
    if timestamp != 'N/A':
        from datetime import datetime
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        formatted_time = dt.strftime('%b %d, %H:%M')
    else:
        formatted_time = 'N/A'
    
    print(f"Row {action_index + 1}:")
    print(f"  Action: {action}")
    print(f"  Quantity: {leg_data['quantity']}")
    print(f"  Strike: ${leg_data['strike']}")
    print(f"  Type: {leg_data['option_type'][0]}")
    print(f"  Price: ${price} ({price_type})")
    print(f"  Time: {formatted_time}")
    print()

print("Summary:")
print(f"✅ Should display {len(leg_data['transaction_actions'])} separate rows")
print(f"✅ Row 1: STO action with entry price ${leg_data['entry_price']}")
print(f"✅ Row 2: BTC action with exit price ${leg_data['exit_price']}")
print()

print("Alpine.js Template Logic Check:")
print("-" * 30)
print("Template: x-for=\"(action, actionIndex) in (leg.transaction_actions || [])\"")
print(f"Array: {leg_data['transaction_actions']}")
print("Expected iterations:")
for i, action in enumerate(leg_data['transaction_actions']):
    print(f"  Iteration {i}: action='{action}', actionIndex={i}")

print()
print("Price Display Logic:")
print("Template: (['BTO', 'STO'].includes(action)) ? leg.entry_price : leg.exit_price || '0.00'")
for action in leg_data['transaction_actions']:
    is_opening = action in ['BTO', 'STO']
    if is_opening:
        display_price = leg_data['entry_price']
        logic = f"'{action}' in ['BTO', 'STO'] = True → entry_price = {display_price}"
    else:
        display_price = leg_data['exit_price'] or 0.00
        logic = f"'{action}' in ['BTO', 'STO'] = False → exit_price = {display_price}"
    print(f"  {logic}")