#!/usr/bin/env python3
"""
Direct test of the options screener to debug issues
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.options_screener import OptionsScreener
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")

def main():
    # Authenticate
    logger.info("Authenticating with Tastytrade...")
    client = TastytradeClient()
    if not client.authenticate():
        logger.error("Authentication failed")
        return

    # Create screener
    screener = OptionsScreener(client.session)

    # Test with a single ticker
    ticker = "ASTS"
    logger.info(f"Testing screener with {ticker}")

    result = screener.analyze_ticker(
        ticker=ticker,
        near_dte_range=(30, 45),
        leaps_dte_min=300,  # Lower for testing
        leaps_delta_range=(0.60, 0.85),  # Wider range
        min_volume=1,  # Very low threshold for testing
        min_open_interest=0  # Accept any OI
    )

    if result:
        logger.info(f"✅ Result: {result}")
    else:
        logger.warning(f"❌ No result for {ticker}")

if __name__ == "__main__":
    main()
