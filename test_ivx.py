#!/usr/bin/env python3
"""Test fetching IVx data from Tastytrade"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from tastytrade.metrics import get_market_metrics
from datetime import datetime

# Authenticate
client = TastytradeClient()
if not client.authenticate():
    print("Authentication failed")
    sys.exit(1)

# Get market metrics for OKLO
print("Fetching market metrics for OKLO...")
metrics = get_market_metrics(client.session, ["OKLO"])

if metrics and len(metrics) > 0:
    metric = metrics[0]

    print(f"\nSymbol: {metric.symbol}")
    print(f"IVx (implied_volatility_index): {metric.implied_volatility_index}")
    print(f"IV Rank: {metric.implied_volatility_index_rank}")
    print(f"30-day IV: {metric.implied_volatility_30_day}")
    print(f"30-day HV: {metric.historical_volatility_30_day}")

    print(f"\nOption Expiration IVs:")
    if metric.option_expiration_implied_volatilities:
        today = datetime.now().date()
        for exp_iv in metric.option_expiration_implied_volatilities:
            dte = (exp_iv.expiration_date - today).days
            iv_pct = float(exp_iv.implied_volatility) * 100 if exp_iv.implied_volatility else None
            print(f"  {exp_iv.expiration_date} ({dte} DTE): IV = {iv_pct:.2f}%" if iv_pct else f"  {exp_iv.expiration_date}: No IV")
    else:
        print("  No expiration IVs available")
else:
    print("No metrics found")
