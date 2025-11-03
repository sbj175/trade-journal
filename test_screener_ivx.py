#!/usr/bin/env python3
"""
Test the updated screener with IVx data
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from src.models.options_screener import OptionsScreener
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")

def main():
    # Authenticate
    logger.info("Authenticating with Tastytrade...")
    client = TastytradeClient()
    if not client.authenticate():
        logger.error("Authentication failed")
        return

    # Create screener
    screener = OptionsScreener(client.session)

    # Test with OKLO (known to have good data)
    tickers = ["OKLO", "ASTS"]

    logger.info(f"Testing IVx-based screener with: {', '.join(tickers)}")

    for ticker in tickers:
        logger.info(f"\n{'='*60}")
        logger.info(f"Analyzing {ticker}...")
        logger.info(f"{'='*60}")

        result = screener.analyze_ticker(
            ticker=ticker,
            near_dte_range=(30, 45),
            leaps_dte_min=150,  # Lower for testing
            leaps_delta_range=(0.60, 0.85),
            min_volume=1,
            min_open_interest=0
        )

        if result:
            logger.info(f"\n✅ {ticker} Results:")
            logger.info(f"  Price: ${result['price']:.2f}")
            logger.info(f"  Near-term: {result['near_dte']} DTE, IV={result['near_iv']:.1f}%")
            logger.info(f"  LEAPS: {result['leaps_dte']} DTE, IV={result['leaps_iv']:.1f}%")
            logger.info(f"  IV Spread: {result['iv_spread']:.1f}% ({result['term_structure']})")
            logger.info(f"  IV Rank: {result['iv_rank']:.1f}%" if result['iv_rank'] else "  IV Rank: N/A")
        else:
            logger.warning(f"\n❌ No result for {ticker}")

if __name__ == "__main__":
    main()
