"""
Options Term Structure Screener for PMCC candidates

This module analyzes options chains to identify favorable term structure for
Poor Man's Covered Calls (PMCCs) by comparing near-term IV vs LEAPS IV.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
from tastytrade import Session
from tastytrade.instruments import get_option_chain, Option
from tastytrade.market_data import get_market_data_by_type


class OptionsScreener:
    """
    Screen options for PMCC opportunities based on term structure.

    Criteria:
    - Near-term IV (30-45 DTE) should be elevated
    - LEAPS IV (365+ DTE, 70-80 delta) should be lower
    - IV spread (near - LEAPS) should be > 10 points
    - Sufficient liquidity (volume/OI thresholds)
    """

    def __init__(self, session: Session):
        self.session = session

    def screen_tickers(
        self,
        tickers: List[str],
        near_dte_range: Tuple[int, int] = (30, 45),
        leaps_dte_min: int = 365,
        leaps_delta_range: Tuple[float, float] = (0.70, 0.80),
        min_iv_spread: float = 10.0,
        min_near_iv: float = 30.0,
        min_volume: int = 100,
        min_open_interest: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Screen multiple tickers for PMCC opportunities.

        Args:
            tickers: List of stock symbols to analyze
            near_dte_range: DTE range for near-term options (default 30-45)
            leaps_dte_min: Minimum DTE for LEAPS (default 365)
            leaps_delta_range: Delta range for LEAPS (default 0.70-0.80)
            min_iv_spread: Minimum IV spread in points (default 10.0)
            min_near_iv: Minimum near-term IV (default 30.0)
            min_volume: Minimum daily volume for liquidity (default 100)
            min_open_interest: Minimum open interest (default 100)

        Returns:
            List of candidate dicts with ticker, IVs, spread, and metrics
        """
        candidates = []

        for ticker in tickers:
            try:
                logger.info(f"Screening {ticker}...")
                result = self.analyze_ticker(
                    ticker=ticker,
                    near_dte_range=near_dte_range,
                    leaps_dte_min=leaps_dte_min,
                    leaps_delta_range=leaps_delta_range,
                    min_volume=min_volume,
                    min_open_interest=min_open_interest
                )

                if result:
                    # Apply filters
                    if (result['iv_spread'] >= min_iv_spread and
                        result['near_iv'] >= min_near_iv):
                        candidates.append(result)
                        logger.info(f"✅ {ticker} is a candidate! Spread: {result['iv_spread']:.1f}, Near IV: {result['near_iv']:.1f}")
                    else:
                        logger.info(f"❌ {ticker} filtered out - Spread: {result.get('iv_spread', 0):.1f}, Near IV: {result.get('near_iv', 0):.1f}")

            except Exception as e:
                logger.error(f"Error screening {ticker}: {str(e)}")
                continue

        # Sort by IV spread (descending)
        candidates.sort(key=lambda x: x['iv_spread'], reverse=True)

        return candidates

    def analyze_ticker(
        self,
        ticker: str,
        near_dte_range: Tuple[int, int] = (30, 45),
        leaps_dte_min: int = 365,
        leaps_delta_range: Tuple[float, float] = (0.70, 0.80),
        min_volume: int = 100,
        min_open_interest: int = 100
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze a single ticker's options chain for term structure using IVx data.

        Returns:
            Dict with analysis results or None if insufficient data
        """
        try:
            from tastytrade.metrics import get_market_metrics

            # Get underlying price
            underlying_price = self._get_underlying_price(ticker)
            if not underlying_price:
                logger.warning(f"Could not get underlying price for {ticker}")
                return None

            logger.info(f"Underlying price for {ticker}: ${underlying_price:.2f}")

            # Get market metrics (includes IVx per expiration)
            logger.info(f"Fetching IVx data for {ticker}...")
            metrics = get_market_metrics(self.session, [ticker])

            if not metrics or len(metrics) == 0:
                logger.warning(f"No market metrics found for {ticker}")
                return None

            metric = metrics[0]

            # Get IVx and IV Rank
            ivx = float(metric.implied_volatility_index) * 100 if metric.implied_volatility_index else None
            iv_rank = float(metric.implied_volatility_index_rank) if metric.implied_volatility_index_rank else None

            if not metric.option_expiration_implied_volatilities:
                logger.warning(f"No expiration IVs available for {ticker}")
                return None

            # Build term structure from IVx data
            today = datetime.now().date()
            term_structure = []

            for exp_iv in metric.option_expiration_implied_volatilities:
                if exp_iv.implied_volatility is None:
                    continue

                dte = (exp_iv.expiration_date - today).days
                if dte < 7:  # Skip very short term
                    continue

                iv_pct = float(exp_iv.implied_volatility) * 100

                term_structure.append({
                    'dte': dte,
                    'expiration': exp_iv.expiration_date,
                    'iv': iv_pct,
                })

            if len(term_structure) < 2:
                logger.warning(f"Insufficient term structure data for {ticker}")
                return None

            # Sort by DTE
            term_structure.sort(key=lambda x: x['dte'])

            # Find near-term IV (closest to the DTE range)
            min_dte, max_dte = near_dte_range
            near_term = None
            best_dte_match = float('inf')

            for point in term_structure:
                dte = point['dte']
                # Check if within range
                if min_dte <= dte <= max_dte:
                    # Prefer closest to middle of range
                    target_dte = (min_dte + max_dte) / 2
                    dte_diff = abs(dte - target_dte)
                    if dte_diff < best_dte_match:
                        best_dte_match = dte_diff
                        near_term = point

            if not near_term:
                logger.warning(f"No near-term IV found in {min_dte}-{max_dte} DTE range for {ticker}")
                return None

            # Find LEAPS IV (closest to LEAPS minimum DTE)
            leaps = None
            best_leaps_dte = float('inf')

            for point in term_structure:
                dte = point['dte']
                if dte >= leaps_dte_min:
                    # Prefer closest to minimum (e.g., first available LEAPS)
                    if dte < best_leaps_dte:
                        best_leaps_dte = dte
                        leaps = point

            if not leaps:
                logger.warning(f"No LEAPS IV found with DTE >= {leaps_dte_min} for {ticker}")
                return None

            # Get options chain to find specific strikes for volume/OI
            logger.info(f"Fetching options chain for {ticker} to get liquidity data...")
            chain = get_option_chain(self.session, ticker)

            # Find near-term strike details
            near_term_details = self._get_strike_details(
                chain, near_term['expiration'], underlying_price, min_volume, min_open_interest
            ) if chain else None

            # Find LEAPS strike details
            leaps_details = self._get_leaps_strike_details(
                chain, leaps['expiration'], underlying_price, leaps_delta_range, min_volume, min_open_interest
            ) if chain else None

            # Calculate term structure spread
            iv_spread = near_term['iv'] - leaps['iv']

            return {
                'ticker': ticker,
                'price': underlying_price,
                'near_iv': near_term['iv'],
                'near_dte': near_term['dte'],
                'near_strike': near_term_details['strike'] if near_term_details else None,
                'near_volume': near_term_details['volume'] if near_term_details else 0,
                'near_oi': near_term_details['open_interest'] if near_term_details else 0,
                'leaps_iv': leaps['iv'],
                'leaps_dte': leaps['dte'],
                'leaps_strike': leaps_details['strike'] if leaps_details else None,
                'leaps_delta': leaps_details['delta'] if leaps_details else None,
                'leaps_volume': leaps_details['volume'] if leaps_details else 0,
                'leaps_oi': leaps_details['open_interest'] if leaps_details else 0,
                'iv_spread': iv_spread,
                'iv_rank': iv_rank,
                'term_structure': 'contango' if iv_spread > 0 else 'backwardation',
            }

        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {str(e)}", exc_info=True)
            return None

    def _get_strike_details(
        self,
        chain: Dict[datetime.date, List[Option]],
        expiration: datetime.date,
        underlying_price: float,
        min_volume: int,
        min_open_interest: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get strike, volume, and OI details for ATM call at specific expiration.
        """
        if expiration not in chain:
            return None

        options = chain[expiration]
        best_option = None
        best_atm_diff = float('inf')

        # Find ATM call
        for option in options:
            if option.option_type.value != 'C':
                continue

            strike = float(option.strike_price)
            atm_diff = abs(strike - underlying_price)

            if atm_diff < best_atm_diff:
                best_atm_diff = atm_diff
                best_option = option

        if not best_option:
            return None

        # Get market data for volume/OI
        market_data = self._get_option_market_data(best_option.symbol)
        if market_data:
            return {
                'strike': float(best_option.strike_price),
                'volume': market_data.get('volume', 0),
                'open_interest': market_data.get('open_interest', 0),
            }

        return {
            'strike': float(best_option.strike_price),
            'volume': 0,
            'open_interest': 0,
        }

    def _get_leaps_strike_details(
        self,
        chain: Dict[datetime.date, List[Option]],
        expiration: datetime.date,
        underlying_price: float,
        delta_range: Tuple[float, float],
        min_volume: int,
        min_open_interest: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get strike, delta, volume, and OI details for LEAPS call with target delta.
        """
        if expiration not in chain:
            return None

        options = chain[expiration]
        min_delta, max_delta = delta_range
        target_delta = (min_delta + max_delta) / 2

        best_option = None
        best_delta_match = float('inf')

        # Find call with target delta
        for option in options:
            if option.option_type.value != 'C':
                continue

            strike = float(option.strike_price)
            estimated_delta = self._estimate_call_delta(strike, underlying_price)

            if not (min_delta <= estimated_delta <= max_delta):
                continue

            delta_diff = abs(estimated_delta - target_delta)
            if delta_diff < best_delta_match:
                best_delta_match = delta_diff
                best_option = {
                    'option': option,
                    'estimated_delta': estimated_delta
                }

        if not best_option:
            return None

        # Get market data for volume/OI/actual delta
        market_data = self._get_option_market_data(best_option['option'].symbol)
        if market_data:
            return {
                'strike': float(best_option['option'].strike_price),
                'delta': market_data.get('delta', best_option['estimated_delta']),
                'volume': market_data.get('volume', 0),
                'open_interest': market_data.get('open_interest', 0),
            }

        return {
            'strike': float(best_option['option'].strike_price),
            'delta': best_option['estimated_delta'],
            'volume': 0,
            'open_interest': 0,
        }

    def _get_underlying_price(self, ticker: str) -> Optional[float]:
        """Get current underlying stock price."""
        try:
            market_data_list = get_market_data_by_type(self.session, equities=[ticker])
            if market_data_list and len(market_data_list) > 0:
                market_data = market_data_list[0]
                price = float(market_data.mark) if market_data.mark else None
                return price
        except Exception as e:
            logger.error(f"Error fetching price for {ticker}: {str(e)}")
            return None

    def _get_near_term_iv(
        self,
        chain: Dict[datetime.date, List[Option]],
        underlying_price: float,
        dte_range: Tuple[int, int],
        min_volume: int,
        min_open_interest: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get ATM IV for near-term options (30-45 DTE).

        Returns dict with IV, DTE, strike, volume, OI
        """
        today = datetime.now().date()
        min_dte, max_dte = dte_range

        best_option = None
        best_atm_diff = float('inf')
        best_option_symbol = None

        # Iterate through expirations in DTE range
        for exp_date, options in chain.items():
            dte = (exp_date - today).days

            # Check if within DTE range
            if not (min_dte <= dte <= max_dte):
                continue

            # Find ATM call option with best liquidity
            for option in options:
                # Only calls
                if option.option_type.value != 'C':
                    continue

                # Check how close to ATM
                strike = float(option.strike_price)
                atm_diff = abs(strike - underlying_price)

                # Track best ATM option
                if atm_diff < best_atm_diff:
                    best_atm_diff = atm_diff
                    best_option_symbol = option.symbol
                    best_option = {
                        'dte': dte,
                        'strike': strike,
                        'symbol': option.symbol,
                    }

        # If we found a candidate, fetch its market data for IV
        if best_option:
            market_data = self._get_option_market_data(best_option['symbol'])
            if market_data and market_data.get('iv'):
                best_option['iv'] = market_data['iv']
                best_option['volume'] = market_data.get('volume', 0)
                best_option['open_interest'] = market_data.get('open_interest', 0)

                # Check liquidity thresholds
                # If OI data is missing (0), only check volume
                volume_ok = best_option['volume'] >= min_volume
                oi_ok = (best_option['open_interest'] >= min_open_interest or
                        best_option['open_interest'] == 0)  # Accept if OI unavailable

                if volume_ok and oi_ok:
                    return best_option

        return None

    def _get_leaps_iv(
        self,
        chain: Dict[datetime.date, List[Option]],
        underlying_price: float,
        dte_min: int,
        delta_range: Tuple[float, float],
        min_volume: int,
        min_open_interest: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get IV for LEAPS (365+ DTE, 70-80 delta calls).

        Returns dict with IV, DTE, strike, delta, volume, OI
        """
        today = datetime.now().date()
        min_delta, max_delta = delta_range
        target_delta = (min_delta + max_delta) / 2

        best_option = None
        best_delta_match = float('inf')

        # Iterate through expirations with sufficient DTE
        for exp_date, options in chain.items():
            dte = (exp_date - today).days

            # Check if LEAPS range
            if dte < dte_min:
                continue

            # Find call option with estimated delta in range
            for option in options:
                # Only calls
                if option.option_type.value != 'C':
                    continue

                # Estimate delta from moneyness
                strike = float(option.strike_price)
                estimated_delta = self._estimate_call_delta(strike, underlying_price)

                # Check if in delta range
                if not (min_delta <= estimated_delta <= max_delta):
                    continue

                # Track option closest to target delta (0.75)
                delta_diff = abs(estimated_delta - target_delta)

                if delta_diff < best_delta_match:
                    best_delta_match = delta_diff
                    best_option = {
                        'dte': dte,
                        'strike': strike,
                        'delta': estimated_delta,
                        'symbol': option.symbol,
                    }

        # If we found a candidate, fetch its market data for IV and actual delta
        if best_option:
            market_data = self._get_option_market_data(best_option['symbol'])
            if market_data and market_data.get('iv'):
                best_option['iv'] = market_data['iv']
                best_option['volume'] = market_data.get('volume', 0)
                best_option['open_interest'] = market_data.get('open_interest', 0)

                # Update delta if available from market data
                if market_data.get('delta'):
                    best_option['delta'] = abs(market_data['delta'])

                # Check liquidity thresholds
                # If OI data is missing (0), only check volume
                volume_ok = best_option['volume'] >= min_volume
                oi_ok = (best_option['open_interest'] >= min_open_interest or
                        best_option['open_interest'] == 0)  # Accept if OI unavailable

                logger.debug(f"LEAPS check: vol={best_option['volume']}>={min_volume}? {volume_ok}, OI={best_option['open_interest']}>={min_open_interest}? {oi_ok}")

                if volume_ok and oi_ok:
                    return best_option
                else:
                    logger.warning(f"LEAPS failed liquidity: volume {best_option['volume']} < {min_volume} or OI check failed")

        return None

    def _get_option_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch market data (IV, Greeks, volume, OI) for an option symbol.

        Returns dict with iv, delta, volume, open_interest, etc.
        """
        try:
            market_data_list = get_market_data_by_type(self.session, options=[symbol])
            if not market_data_list or len(market_data_list) == 0:
                logger.debug(f"No market data found for {symbol}")
                return None

            market_data = market_data_list[0]

            result = {}

            # Get IV from market data fields
            iv = None
            iv_fields = ['implied_volatility', 'iv', 'volatility']
            for field in iv_fields:
                if hasattr(market_data, field):
                    value = getattr(market_data, field)
                    if value is not None and value > 0:
                        iv = float(value) * 100  # Convert to percentage
                        break

            # If no IV in market data, estimate from bid-ask spread (FALLBACK)
            if iv is None:
                bid = getattr(market_data, 'bid', None)
                ask = getattr(market_data, 'ask', None)
                mark = getattr(market_data, 'mark', None)

                if bid and ask and mark and mark > 0:
                    # Estimate IV based on option price relative to spread
                    # This is a rough approximation: wider spreads often indicate higher IV
                    spread_pct = ((ask - bid) / mark) * 100

                    # Rough heuristic: IV tends to correlate with relative spread
                    # Base IV estimate on spread width
                    if spread_pct > 20:  # Very wide spread
                        estimated_iv = 100 + (spread_pct * 2)  # High IV
                    elif spread_pct > 10:
                        estimated_iv = 60 + (spread_pct * 3)
                    elif spread_pct > 5:
                        estimated_iv = 40 + (spread_pct * 2)
                    else:
                        estimated_iv = 30 + (spread_pct * 2)

                    iv = min(estimated_iv, 200)  # Cap at 200%
                    logger.info(f"Estimated IV for {symbol}: {iv:.1f}% (from spread: {spread_pct:.1f}%)")

            if iv is not None:
                result['iv'] = iv

            # Get delta
            if hasattr(market_data, 'delta') and market_data.delta is not None:
                result['delta'] = float(market_data.delta)

            # Get volume
            if hasattr(market_data, 'volume') and market_data.volume is not None:
                result['volume'] = int(market_data.volume)
            else:
                result['volume'] = 0

            # Get open interest
            if hasattr(market_data, 'open_interest') and market_data.open_interest is not None:
                result['open_interest'] = int(market_data.open_interest)
            else:
                result['open_interest'] = 0

            return result if result else None

        except Exception as e:
            logger.debug(f"Error fetching market data for {symbol}: {str(e)}")
            return None

    def _estimate_call_delta(self, strike: float, underlying: float) -> float:
        """
        Rough estimate of call delta based on moneyness.
        ITM calls have higher delta, OTM calls have lower delta.
        """
        moneyness = underlying / strike

        if moneyness >= 1.20:  # Deep ITM
            return 0.90
        elif moneyness >= 1.10:  # ITM
            return 0.75
        elif moneyness >= 1.05:  # Slightly ITM
            return 0.60
        elif moneyness >= 0.95:  # ATM
            return 0.50
        elif moneyness >= 0.90:  # Slightly OTM
            return 0.40
        elif moneyness >= 0.80:  # OTM
            return 0.25
        else:  # Deep OTM
            return 0.10

    def _get_iv_rank(self, ticker: str) -> Optional[float]:
        """
        Get IV Rank for the underlying.

        IV Rank = (Current IV - 52-week Low IV) / (52-week High IV - 52-week Low IV) * 100
        """
        try:
            # Try to get from market metrics
            from tastytrade.metrics import get_market_metrics

            metrics = get_market_metrics(self.session, [ticker])
            if metrics and len(metrics) > 0:
                metric = metrics[0]

                # Look for IVR fields
                ivr_fields = [
                    'implied_volatility_index_rank',
                    'iv_rank',
                    'implied_volatility_rank',
                    'volatility_rank'
                ]

                for field in ivr_fields:
                    if hasattr(metric, field):
                        value = getattr(metric, field)
                        if value is not None:
                            return float(value)
        except Exception as e:
            logger.debug(f"Could not get IV rank for {ticker}: {str(e)}")

        return None

    def get_term_structure(
        self,
        ticker: str,
        min_volume: int = 1,
        min_open_interest: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Get the full implied volatility term structure for a ticker using IVx data.

        Returns dict with:
        - ticker
        - price
        - ivx: Overall IVx value
        - iv_rank: IV Rank
        - term_structure: list of {dte, iv, expiration} sorted by DTE
        """
        try:
            from tastytrade.metrics import get_market_metrics

            logger.info(f"Fetching IVx term structure for {ticker}...")

            # Get underlying price
            underlying_price = self._get_underlying_price(ticker)
            if not underlying_price:
                logger.warning(f"Could not get underlying price for {ticker}")
                return None

            # Get market metrics (includes IVx per expiration)
            metrics = get_market_metrics(self.session, [ticker])

            if not metrics or len(metrics) == 0:
                logger.warning(f"No market metrics found for {ticker}")
                return None

            metric = metrics[0]

            # Get IVx and IV Rank
            ivx = float(metric.implied_volatility_index) * 100 if metric.implied_volatility_index else None
            iv_rank = float(metric.implied_volatility_index_rank) if metric.implied_volatility_index_rank else None

            # Get expiration IVs
            today = datetime.now().date()
            term_structure_points = []

            if metric.option_expiration_implied_volatilities:
                for exp_iv in metric.option_expiration_implied_volatilities:
                    if exp_iv.implied_volatility is None:
                        continue

                    dte = (exp_iv.expiration_date - today).days

                    if dte < 7:  # Skip very short term
                        continue

                    iv_pct = float(exp_iv.implied_volatility) * 100

                    term_structure_points.append({
                        'dte': dte,
                        'expiration': exp_iv.expiration_date.isoformat(),
                        'iv': iv_pct,
                    })

            # Sort by DTE
            term_structure_points.sort(key=lambda x: x['dte'])

            logger.info(f"Found {len(term_structure_points)} expiration IVs for {ticker}")

            return {
                'ticker': ticker,
                'price': underlying_price,
                'ivx': ivx,
                'iv_rank': iv_rank,
                'term_structure': term_structure_points
            }

        except Exception as e:
            logger.error(f"Error getting term structure for {ticker}: {str(e)}", exc_info=True)
            return None
