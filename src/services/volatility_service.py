"""Realized volatility calculation and storage.

RV formula for each trade date:
    log_return = ln(P_today / P_yesterday)
    RV_N = stdev(last N log_returns) * sqrt(252)

Windows: RV10, RV20, RV30.
"""

import math
from datetime import date, timedelta
from statistics import stdev
from typing import Dict, List, Optional

from loguru import logger

from src.database.engine import get_session, dialect_insert
from src.database.models import HistoricalPrice, SymbolVolatilityMetric
from src.services.price_service import get_historical_prices

SQRT_252 = math.sqrt(252)
RV_WINDOWS = [10, 20, 30]
MAX_WINDOW = max(RV_WINDOWS)


async def compute_and_store_rv(
    symbol: str,
    target_date: str = None,
) -> Optional[Dict]:
    """Compute realized volatility for a symbol and store it.

    Args:
        symbol: Ticker symbol (e.g. "AAPL").
        target_date: Date to compute RV for (YYYY-MM-DD). Defaults to
            the most recent completed trading day.

    Returns:
        Dict with rv10, rv20, rv30 values, or None if insufficient data.
    """
    symbol = symbol.upper()
    if target_date is None:
        target_date = _last_trading_day().isoformat()

    # We need MAX_WINDOW + 1 prior trading days of prices to compute
    # log returns. Fetch ~50 calendar days to account for weekends/holidays.
    lookback_start = (
        date.fromisoformat(target_date) - timedelta(days=MAX_WINDOW * 2 + 10)
    ).isoformat()

    prices = await get_historical_prices(symbol, lookback_start, target_date)

    if len(prices) < MAX_WINDOW + 1:
        logger.warning(
            f"Insufficient price data for {symbol} RV: {len(prices)} rows "
            f"(need {MAX_WINDOW + 1})"
        )
        return None

    # Compute log returns from adj_close
    log_returns = []
    for i in range(1, len(prices)):
        p_prev = prices[i - 1]["adj_close"]
        p_curr = prices[i]["adj_close"]
        if p_prev and p_curr and p_prev > 0:
            log_returns.append(math.log(p_curr / p_prev))

    if len(log_returns) < MAX_WINDOW:
        logger.warning(f"Insufficient log returns for {symbol}: {len(log_returns)}")
        return None

    # Compute RV for each window
    result = {"symbol": symbol, "date": target_date}
    for window in RV_WINDOWS:
        window_returns = log_returns[-window:]
        if len(window_returns) >= window:
            rv = stdev(window_returns) * SQRT_252
            result[f"rv{window}"] = round(rv, 6)
        else:
            result[f"rv{window}"] = None

    # Persist
    _persist_metric(result)
    logger.info(
        f"{symbol} RV on {target_date}: "
        f"RV10={result.get('rv10')}, RV20={result.get('rv20')}, RV30={result.get('rv30')}"
    )
    return result


async def get_rv(symbol: str, target_date: str = None) -> Optional[Dict]:
    """Get realized volatility — from cache or compute on demand.

    Args:
        symbol: Ticker symbol.
        target_date: Date (YYYY-MM-DD). Defaults to last trading day.

    Returns:
        Dict with rv10, rv20, rv30 or None.
    """
    symbol = symbol.upper()
    if target_date is None:
        target_date = _last_trading_day().isoformat()

    # Check cache
    cached = _load_cached(symbol, target_date)
    if cached:
        return cached

    # Compute and store
    return await compute_and_store_rv(symbol, target_date)


def _load_cached(symbol: str, target_date: str) -> Optional[Dict]:
    """Load cached RV metrics from the database."""
    with get_session(unscoped=True) as session:
        row = (
            session.query(SymbolVolatilityMetric)
            .filter(
                SymbolVolatilityMetric.symbol == symbol,
                SymbolVolatilityMetric.date == target_date,
            )
            .first()
        )
        if row:
            return {
                "symbol": row.symbol,
                "date": row.date,
                "rv10": row.rv10,
                "rv20": row.rv20,
                "rv30": row.rv30,
            }
        return None


def _persist_metric(result: Dict) -> None:
    """Upsert a volatility metric row."""
    with get_session(unscoped=True) as session:
        vals = dict(
            symbol=result["symbol"],
            date=result["date"],
            rv10=result.get("rv10"),
            rv20=result.get("rv20"),
            rv30=result.get("rv30"),
        )
        stmt = dialect_insert(SymbolVolatilityMetric).values(**vals)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_volatility_metric_symbol_date",
            set_={k: v for k, v in vals.items() if k not in ("symbol", "date")},
        )
        session.execute(stmt)


def _last_trading_day() -> date:
    """Return the most recent completed trading day (weekday before today)."""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:  # Skip weekends
        d -= timedelta(days=1)
    return d
