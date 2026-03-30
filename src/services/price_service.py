"""Historical price service — cache-aside pattern over Tiingo EOD API."""

from datetime import date, timedelta
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy import and_

from src.api.tiingo_client import TiingoClient
from src.database.engine import get_session, dialect_insert
from src.database.models import HistoricalPrice


_tiingo = TiingoClient()


async def get_historical_prices(
    symbol: str,
    start_date: str,
    end_date: str,
) -> List[Dict]:
    """Get EOD prices for a symbol, fetching from Tiingo only for missing dates.

    Args:
        symbol: Ticker symbol (e.g. "AAPL").
        start_date: Start date YYYY-MM-DD.
        end_date: End date YYYY-MM-DD.

    Returns:
        List of dicts with keys: symbol, date, open, high, low, close,
        adj_close, volume — sorted by date ascending.
    """
    symbol = symbol.upper()

    # 1. Load cached rows from DB
    cached = _load_cached(symbol, start_date, end_date)
    cached_dates = {row["date"] for row in cached}

    # 2. Determine missing date range
    needed_start, needed_end = _find_missing_range(
        start_date, end_date, cached_dates
    )

    # 3. Fetch missing data from Tiingo if needed
    if needed_start and needed_end:
        if not _tiingo.is_configured():
            logger.warning("Tiingo API key not configured — returning cached data only")
        else:
            fetched = await _tiingo.fetch_eod_prices(
                symbol, needed_start, needed_end
            )
            if fetched:
                _persist(symbol, fetched)
                # Reload from DB for a consistent result set
                cached = _load_cached(symbol, start_date, end_date)

    return cached


def _load_cached(symbol: str, start_date: str, end_date: str) -> List[Dict]:
    """Load cached prices from the database."""
    with get_session(unscoped=True) as session:
        rows = (
            session.query(HistoricalPrice)
            .filter(
                HistoricalPrice.symbol == symbol,
                HistoricalPrice.date >= start_date,
                HistoricalPrice.date <= end_date,
            )
            .order_by(HistoricalPrice.date)
            .all()
        )
        return [
            {
                "symbol": r.symbol,
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "adj_close": r.adj_close,
                "volume": r.volume,
            }
            for r in rows
        ]


def _find_missing_range(
    start_date: str, end_date: str, cached_dates: set
) -> tuple:
    """Find the contiguous date range that needs fetching.

    Returns (needed_start, needed_end) or (None, None) if fully cached.
    We fetch the entire missing range rather than individual gaps to
    minimise API calls.
    """
    d = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    today = date.today()

    missing = []
    while d <= end:
        # Skip weekends (no trading data)
        if d.weekday() < 5 and d < today and d.isoformat() not in cached_dates:
            missing.append(d)
        d += timedelta(days=1)

    if not missing:
        return None, None

    return missing[0].isoformat(), missing[-1].isoformat()


def _persist(symbol: str, tiingo_rows: List[Dict]) -> None:
    """Persist Tiingo API response rows to the database."""
    with get_session(unscoped=True) as session:
        for row in tiingo_rows:
            price_date = row["date"][:10]  # "2026-03-27T00:00:00.000Z" → "2026-03-27"
            vals = dict(
                symbol=symbol,
                date=price_date,
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=row.get("close"),
                adj_close=row.get("adjClose"),
                volume=row.get("volume"),
            )
            stmt = dialect_insert(HistoricalPrice).values(**vals)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_historical_price_symbol_date",
                set_={k: v for k, v in vals.items() if k not in ("symbol", "date")},
            )
            session.execute(stmt)

        logger.info(f"Cached {len(tiingo_rows)} EOD prices for {symbol}")
