"""Strategy registry — single source of truth for all strategy metadata."""

from .types import StrategyDef

STRATEGIES: dict[str, StrategyDef] = {
    # -- Credit strategies --
    "Bull Put Spread":   StrategyDef("Bull Put Spread",   "bullish",  "credit", 2, "vertical"),
    "Bear Call Spread":  StrategyDef("Bear Call Spread",   "bearish",  "credit", 2, "vertical"),
    "Iron Condor":       StrategyDef("Iron Condor",        "neutral",  "credit", 4, "multi"),
    "Iron Butterfly":    StrategyDef("Iron Butterfly",      "neutral",  "credit", 4, "multi"),
    "Short Call Butterfly": StrategyDef("Short Call Butterfly", "neutral",  "credit", 3, "multi"),
    "Short Put Butterfly":  StrategyDef("Short Put Butterfly",  "neutral",  "credit", 3, "multi"),
    "Inverse Call Broken Wing": StrategyDef("Inverse Call Broken Wing", "neutral", "mixed", 3, "multi"),
    "Inverse Put Broken Wing":  StrategyDef("Inverse Put Broken Wing",  "neutral", "mixed", 3, "multi"),
    "Short Strangle":    StrategyDef("Short Strangle",      "neutral",  "credit", 2, "multi"),
    "Short Straddle":    StrategyDef("Short Straddle",      "neutral",  "credit", 2, "multi"),
    "Cash Secured Put":  StrategyDef("Cash Secured Put",    "bullish",  "credit", 1, "single"),
    "Short Put":         StrategyDef("Short Put",           "bullish",  "credit", 1, "single"),
    "Short Call":        StrategyDef("Short Call",          "bearish",  "credit", 1, "single"),
    "Covered Call":      StrategyDef("Covered Call",        "bullish",  "credit", 2, "combo"),
    "Jade Lizard":       StrategyDef("Jade Lizard",         "bullish",  "credit", 3, "combo"),
    # -- Debit strategies --
    "Bull ZEBRA":        StrategyDef("Bull ZEBRA",          "bullish",  "debit",  2, "vertical"),
    "Bear ZEBRA":        StrategyDef("Bear ZEBRA",          "bearish",  "debit",  2, "vertical"),
    "Bull Call Spread":  StrategyDef("Bull Call Spread",    "bullish",  "debit",  2, "vertical"),
    "Bear Put Spread":   StrategyDef("Bear Put Spread",     "bearish",  "debit",  2, "vertical"),
    "Long Call Butterfly":  StrategyDef("Long Call Butterfly",  "neutral",  "debit",  3, "multi"),
    "Long Put Butterfly":   StrategyDef("Long Put Butterfly",   "neutral",  "debit",  3, "multi"),
    "Call Broken Wing":     StrategyDef("Call Broken Wing",     "neutral",  "mixed",  3, "multi"),
    "Put Broken Wing":      StrategyDef("Put Broken Wing",      "neutral",  "mixed",  3, "multi"),
    "Long Call":         StrategyDef("Long Call",           "bullish",  "debit",  1, "single"),
    "Long Put":          StrategyDef("Long Put",            "bearish",  "debit",  1, "single"),
    "Long Strangle":     StrategyDef("Long Strangle",       "neutral",  "debit",  2, "multi"),
    "Long Straddle":     StrategyDef("Long Straddle",       "neutral",  "debit",  2, "multi"),
    "Calendar Spread":   StrategyDef("Calendar Spread",     "neutral",  "debit",  2, "calendar"),
    "Diagonal Spread":   StrategyDef("Diagonal Spread",     "neutral",  "debit",  2, "calendar"),
    "Diagonal Call Spread": StrategyDef("Diagonal Call Spread", "bullish", "debit", 2, "calendar"),
    # -- Mixed / Neutral --
    "Collar":            StrategyDef("Collar",              "neutral",  "mixed",  3, "combo"),
    # -- Equity --
    "Shares":            StrategyDef("Shares",              None,       None,     1, "single"),
}
