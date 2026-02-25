"""Data types for the strategy engine."""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Leg:
    """A single leg of a strategy, normalized from lot data."""
    instrument_type: str        # "Equity" or "Option"
    option_type: Optional[str]  # "C" or "P" (None for equity)
    strike: Optional[float]     # None for equity
    expiration: Optional[date]  # None for equity
    direction: str              # "long" or "short"
    quantity: int               # Always positive


@dataclass(frozen=True)
class StrategyDef:
    """Registry entry defining a strategy's metadata."""
    name: str
    direction: Optional[str]    # "bullish", "bearish", "neutral"
    credit_debit: Optional[str]  # "credit", "debit", "mixed"
    leg_count: int              # Expected number of legs
    category: str               # "single", "vertical", "multi", "calendar", "combo"


@dataclass(frozen=True)
class StrategyResult:
    """Result of strategy recognition."""
    name: str                   # e.g., "Iron Condor"
    direction: Optional[str]    # "bullish", "bearish", "neutral", None
    credit_debit: Optional[str]  # "credit", "debit", "mixed", None
    leg_count: int
    confidence: float           # 0.0-1.0
