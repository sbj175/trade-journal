#!/usr/bin/env python3
"""Test reprocessing to debug strategy detection"""

import requests
import time

print("Starting reprocess test...")

# Trigger reprocessing
response = requests.post("http://localhost:8000/api/reprocess-chains")
print(f"Reprocess response: {response.json()}")

# Wait a moment for processing
time.sleep(2)

# Check CSX chain
response = requests.get("http://localhost:8000/api/chains?underlying=CSX")
chains = response.json().get('chains', [])
if chains:
    chain = chains[0]
    print(f"\nCSX chain strategy: {chain.get('strategy_type')}")
else:
    print("\nNo CSX chains found")

# Check debug endpoint
response = requests.get("http://localhost:8000/api/debug/strategy/CSX_OPENING_20250729_39786951")
debug_data = response.json()
print(f"\nDebug endpoint strategy: {debug_data.get('detected_strategy')}")

print("\nDone.")