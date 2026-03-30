"""Tiingo EOD (End of Day) price API client."""

import os
from typing import Dict, List, Optional

import httpx
from loguru import logger


class TiingoAPIError(Exception):
    """Raised when the Tiingo API returns an error."""


class TiingoClient:
    """Async client for the Tiingo EOD stock price API.

    Supports dual-mode credentials: explicit api_key parameter (per-user)
    or fallback to TIINGO_API_KEY environment variable (single-user).
    """

    BASE_URL = "https://api.tiingo.com"

    def __init__(self, api_key: str = None):
        self.api_key = (api_key or os.getenv("TIINGO_API_KEY") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def check_connection(self) -> bool:
        """Verify the API key works by fetching metadata for a known ticker."""
        if not self.is_configured():
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/tiingo/daily/AAPL",
                    params={"token": self.api_key},
                    timeout=10,
                )
            if resp.status_code == 200:
                logger.info("Tiingo connection verified")
                return True
            logger.warning(f"Tiingo connection check failed: {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Tiingo connection check error: {e}")
            return False

    async def fetch_eod_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """Fetch End of Day prices for a ticker.

        Args:
            ticker: Stock symbol (e.g. "AAPL").
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.

        Returns:
            List of dicts with keys: date, close, high, low, open, volume,
            adjClose, adjHigh, adjLow, adjOpen, adjVolume, divCash, splitFactor.

        Raises:
            TiingoAPIError: On non-200 responses or missing API key.
        """
        if not self.is_configured():
            raise TiingoAPIError("Tiingo API key not configured")

        url = f"{self.BASE_URL}/tiingo/daily/{ticker.upper()}/prices"
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "token": self.api_key,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=30)

            if resp.status_code == 404:
                logger.warning(f"Tiingo: ticker {ticker} not found")
                return []
            if resp.status_code != 200:
                raise TiingoAPIError(
                    f"Tiingo API error {resp.status_code}: {resp.text[:200]}"
                )

            data = resp.json()
            logger.debug(f"Tiingo: fetched {len(data)} EOD records for {ticker}")
            return data

        except TiingoAPIError:
            raise
        except Exception as e:
            raise TiingoAPIError(f"Failed to fetch EOD prices for {ticker}: {e}")
