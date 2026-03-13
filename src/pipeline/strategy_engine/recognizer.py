"""Main strategy recognition dispatcher.

Uses a scoring/partition approach (OPT-206):
1. Generate candidate strategy matches for all leg subsets (size 1–4)
2. Score each candidate (larger strategies score higher)
3. Find the best non-overlapping partition that covers all legs
4. Return the result (single strategy or combined name)

This replaces the old ordered-dispatch approach which could misclassify
when the same legs belonged to multiple valid strategies (e.g., Jade Lizard
vs Bear Call Spread + Short Put).
"""

from itertools import combinations
from typing import FrozenSet, List, Optional, Tuple

from .types import Leg, StrategyResult
from .constants import STRATEGIES
from .patterns_single import match_single
from .patterns_vertical import match_vertical
from .patterns_multi import match_multi
from .patterns_calendar import match_calendar
from .patterns_combo import match_combo

# (leg_indices, strategy_name, score)
Candidate = Tuple[FrozenSet[int], str, int]


def recognize(legs: List[Leg]) -> StrategyResult:
    """Recognize the strategy formed by a set of legs.

    Uses a best-partition approach:
    1. Generate candidate matches for all subsets of size 1–4
    2. Score each candidate (larger strategies score higher)
    3. Find the non-overlapping partition with highest total score
    4. Return the result (single strategy or combined name)
    """
    if not legs:
        return _custom_result(0)

    n = len(legs)

    # Generate all candidate matches
    candidates: List[Candidate] = []
    for size in range(1, min(n, 4) + 1):
        for combo_indices in combinations(range(n), size):
            combo = [legs[i] for i in combo_indices]
            name = _try_match(combo)
            if name:
                score = _score(name, size, n)
                candidates.append((frozenset(combo_indices), name, score))

    if not candidates:
        return _custom_result(n)

    # Find best partition covering all legs
    best_partition = _solve_partition(candidates, n)

    if not best_partition:
        return _custom_result(n)

    # Build result
    if len(best_partition) == 1:
        _, name, _ = best_partition[0]
        return _result(name)

    # Multiple strategies — combine names, largest first, deduplicated
    sorted_parts = sorted(best_partition, key=lambda c: -_strategy_leg_count(c[1]))
    names = [name for _, name, _ in sorted_parts]
    # Deduplicate: "Short Call + Short Call" -> "Short Call"
    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    combined = " + ".join(seen)
    # Build sub_strategies for group splitting
    subs = tuple((name, indices) for indices, name, _ in sorted_parts)
    return StrategyResult(
        name=combined, direction=None, credit_debit=None,
        leg_count=n, confidence=0.9, sub_strategies=subs,
    )


def _try_match(legs: List[Leg]) -> Optional[str]:
    """Try all pattern matchers on a subset of legs. Returns name or None.

    Each matcher validates its own preconditions, so we can safely call
    them on any subset. Order: combo → multi → vertical → calendar → single.
    """
    equity = [l for l in legs if l.instrument_type == "Equity"]
    options = [l for l in legs if l.instrument_type == "Option"]

    # Combo patterns (equity + options)
    if equity:
        name = match_combo(equity, options)
        if name:
            return name

    # Option-only 3-leg combo (Jade Lizard)
    if not equity and len(options) == 3:
        name = match_combo([], options)
        if name:
            return name

    # Multi-leg (Iron Condor, Iron Butterfly, strangles, straddles)
    if options:
        name = match_multi(options)
        if name:
            return name

    # Vertical spread
    if len(options) == 2:
        name = match_vertical(options)
        if name:
            return name

    # Calendar / diagonal
    if len(options) == 2:
        name = match_calendar(options)
        if name:
            return name

    # Single leg
    if len(legs) == 1:
        name = match_single(legs[0])
        if name:
            return name

    return None


def _score(name: str, leg_count: int, total_legs: int) -> int:
    """Score a strategy match. Higher = better.

    Larger strategies score higher, with a bonus for covering all legs.
    This ensures e.g. Jade Lizard (3-leg) beats Bear Call Spread + Short Put (2+1).
    """
    base = {4: 10, 3: 8, 2: 5, 1: 2}.get(leg_count, 1)
    # Bonus for covering all legs in one strategy
    if leg_count == total_legs:
        base += 5
    return base


def _solve_partition(candidates: List[Candidate], n: int) -> Optional[List[Candidate]]:
    """Find the best non-overlapping set of candidates.

    Prioritizes: (1) maximum leg coverage, (2) highest total score.
    With typical retail positions (2–6 legs), this is trivially fast.
    """
    all_indices = frozenset(range(n))
    best: List[Candidate] = []
    best_score = -1
    best_coverage = 0

    def search(remaining: FrozenSet[int], chosen: List[Candidate],
               score: int, coverage: int, start: int):
        nonlocal best, best_score, best_coverage

        # Update best if better coverage, or same coverage with higher score
        if coverage > best_coverage or (coverage == best_coverage and score > best_score):
            best_coverage = coverage
            best_score = score
            best = list(chosen)

        if not remaining:
            return

        for i in range(start, len(candidates)):
            indices, name, s = candidates[i]
            if indices.issubset(remaining):
                search(remaining - indices, chosen + [(indices, name, s)],
                       score + s, coverage + len(indices), i + 1)

    search(all_indices, [], 0, 0, 0)
    return best if best else None


def _strategy_leg_count(name: str) -> int:
    """Get the leg count for a strategy name from the registry."""
    defn = STRATEGIES.get(name)
    return defn.leg_count if defn else 0


def _result(name: str) -> StrategyResult:
    """Build a StrategyResult from a strategy name using the registry."""
    defn = STRATEGIES.get(name)
    if defn:
        return StrategyResult(
            name=defn.name,
            direction=defn.direction,
            credit_debit=defn.credit_debit,
            leg_count=defn.leg_count,
            confidence=1.0,
        )
    # Name not in registry — treat as recognized but unregistered
    return StrategyResult(name=name, direction=None, credit_debit=None,
                          leg_count=0, confidence=0.5)


def _custom_result(leg_count: int) -> StrategyResult:
    """Build a fallback Custom result."""
    return StrategyResult(
        name=f"Custom ({leg_count}-leg)",
        direction=None,
        credit_debit=None,
        leg_count=leg_count,
        confidence=0.0,
    )
