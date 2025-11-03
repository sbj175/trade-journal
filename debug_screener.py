#!/usr/bin/env python3
"""
Debug script to see what's happening with specific tickers in the screener
"""

import sys
import os
from datetime import datetime
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.api.tastytrade_client import TastytradeClient
from tastytrade.instruments import get_option_chain
from tastytrade.market_data import get_market_data_by_type
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")

def debug_ticker(session, ticker):
    """Debug a single ticker to see what data we can get"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Debugging {ticker}")
    logger.info(f"{'='*60}")

    try:
        # Step 1: Get underlying price
        logger.info(f"Step 1: Fetching underlying price for {ticker}...")
        market_data_list = get_market_data_by_type(session, equities=[ticker])
        if not market_data_list:
            logger.error(f"❌ Could not get underlying price for {ticker}")
            return

        underlying_price = float(market_data_list[0].mark)
        logger.info(f"✅ Underlying price: ${underlying_price:.2f}")

        # Step 2: Get options chain
        logger.info(f"\nStep 2: Fetching options chain for {ticker}...")
        chain = get_option_chain(session, ticker)

        if not chain:
            logger.error(f"❌ No options chain found for {ticker}")
            return

        logger.info(f"✅ Found options chain with {len(chain)} expiration dates")

        # Show expiration dates
        today = datetime.now().date()
        expirations = sorted(chain.keys())
        logger.info(f"\nExpiration dates:")
        for exp_date in expirations[:10]:  # Show first 10
            dte = (exp_date - today).days
            num_options = len(chain[exp_date])
            logger.info(f"  {exp_date} ({dte} DTE): {num_options} options")

        if len(expirations) > 10:
            logger.info(f"  ... and {len(expirations) - 10} more")

        # Step 3: Find near-term options (30-45 DTE)
        logger.info(f"\nStep 3: Looking for near-term options (30-45 DTE, ATM)...")
        near_term_found = False

        for exp_date in expirations:
            dte = (exp_date - today).days
            if 30 <= dte <= 45:
                options = chain[exp_date]
                # Find ATM call
                best_atm = None
                best_diff = float('inf')

                for option in options:
                    if option.option_type.value == 'C':
                        strike = float(option.strike_price)
                        diff = abs(strike - underlying_price)
                        if diff < best_diff:
                            best_diff = diff
                            best_atm = option

                if best_atm:
                    near_term_found = True
                    logger.info(f"  Found ATM call at {exp_date} ({dte} DTE)")
                    logger.info(f"    Strike: ${best_atm.strike_price}")
                    logger.info(f"    Symbol: {best_atm.symbol}")

                    # Try to get market data
                    logger.info(f"    Fetching market data...")
                    try:
                        opt_data = get_market_data_by_type(session, options=[best_atm.symbol])
                        if opt_data and len(opt_data) > 0:
                            md = opt_data[0]
                            logger.info(f"    ✅ Market data found:")
                            logger.info(f"       Bid: ${md.bid if md.bid else 'N/A'}")
                            logger.info(f"       Ask: ${md.ask if md.ask else 'N/A'}")
                            logger.info(f"       Mark: ${md.mark if md.mark else 'N/A'}")

                            # Check for IV
                            iv = None
                            for field in ['implied_volatility', 'iv', 'volatility']:
                                if hasattr(md, field):
                                    val = getattr(md, field)
                                    if val is not None:
                                        iv = float(val) * 100
                                        logger.info(f"       IV: {iv:.1f}% (from {field})")
                                        break

                            if iv is None:
                                logger.warning(f"       ⚠️ No IV data available")
                                # Log all available fields
                                fields = [f for f in dir(md) if not f.startswith('_')]
                                logger.info(f"       Available fields: {fields}")

                            # Check for volume/OI
                            volume = getattr(md, 'volume', None)
                            oi = getattr(md, 'open_interest', None)
                            logger.info(f"       Volume: {volume if volume else 'N/A'}")
                            logger.info(f"       OI: {oi if oi else 'N/A'}")
                        else:
                            logger.warning(f"    ⚠️ No market data returned")
                    except Exception as e:
                        logger.error(f"    ❌ Error fetching market data: {str(e)}")

                    break  # Only check first match

        if not near_term_found:
            logger.warning(f"⚠️ No near-term (30-45 DTE) options found")

        # Step 4: Find LEAPS (300+ DTE)
        logger.info(f"\nStep 4: Looking for LEAPS (300+ DTE, 70-80 delta)...")
        leaps_found = False

        for exp_date in expirations:
            dte = (exp_date - today).days
            if dte >= 300:
                options = chain[exp_date]
                # Find calls around 0.75 delta (roughly 0.9 * underlying for estimate)
                target_strike = underlying_price * 0.9
                best_leap = None
                best_diff = float('inf')

                for option in options:
                    if option.option_type.value == 'C':
                        strike = float(option.strike_price)
                        diff = abs(strike - target_strike)
                        if diff < best_diff:
                            best_diff = diff
                            best_leap = option

                if best_leap:
                    leaps_found = True
                    logger.info(f"  Found LEAP call at {exp_date} ({dte} DTE)")
                    logger.info(f"    Strike: ${best_leap.strike_price}")
                    logger.info(f"    Symbol: {best_leap.symbol}")
                    logger.info(f"    Estimated delta: ~0.75")

                    # Try to get market data
                    logger.info(f"    Fetching market data...")
                    try:
                        opt_data = get_market_data_by_type(session, options=[best_leap.symbol])
                        if opt_data and len(opt_data) > 0:
                            md = opt_data[0]
                            logger.info(f"    ✅ Market data found:")
                            logger.info(f"       Mark: ${md.mark if md.mark else 'N/A'}")

                            # Check for IV
                            iv = None
                            for field in ['implied_volatility', 'iv', 'volatility']:
                                if hasattr(md, field):
                                    val = getattr(md, field)
                                    if val is not None:
                                        iv = float(val) * 100
                                        logger.info(f"       IV: {iv:.1f}%")
                                        break

                            if iv is None:
                                logger.warning(f"       ⚠️ No IV data available")

                            volume = getattr(md, 'volume', None)
                            oi = getattr(md, 'open_interest', None)
                            logger.info(f"       Volume: {volume if volume else 'N/A'}")
                            logger.info(f"       OI: {oi if oi else 'N/A'}")
                        else:
                            logger.warning(f"    ⚠️ No market data returned")
                    except Exception as e:
                        logger.error(f"    ❌ Error fetching market data: {str(e)}")

                    break  # Only check first LEAP

        if not leaps_found:
            logger.warning(f"⚠️ No LEAPS (300+ DTE) options found")

        logger.info(f"\n{'='*60}\n")

    except Exception as e:
        logger.error(f"❌ Error debugging {ticker}: {str(e)}", exc_info=True)

def main():
    # Authenticate
    logger.info("Authenticating with Tastytrade...")
    client = TastytradeClient()
    if not client.authenticate():
        logger.error("Authentication failed")
        return

    # Debug each ticker
    tickers = ["ASTS", "OKLO"]
    for ticker in tickers:
        debug_ticker(client.session, ticker)

if __name__ == "__main__":
    main()
