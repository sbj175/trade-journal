"""Strategy Engine — position-snapshot-based strategy recognition.

Public API:
    recognize(legs) -> StrategyResult
    lots_to_legs(lots) -> List[Leg]
"""

from .recognizer import recognize
from .adapters import lots_to_legs
from .types import Leg, StrategyResult, StrategyDef
from .constants import STRATEGIES

__all__ = ["recognize", "lots_to_legs", "Leg", "StrategyResult", "StrategyDef", "STRATEGIES"]
