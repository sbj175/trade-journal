/**
 * Shared constants for OptionLedger.
 * Loaded globally — Alpine.js components reference via window.STRATEGY_CATEGORIES.
 */

const STRATEGY_CATEGORIES = {
    'Bull Put Spread': { direction: 'bullish', type: 'credit' },
    'Bear Call Spread': { direction: 'bearish', type: 'credit' },
    'Iron Condor': { direction: 'neutral', type: 'credit' },
    'Iron Butterfly': { direction: 'neutral', type: 'credit' },
    'Cash Secured Put': { direction: 'bullish', type: 'credit' },
    'Covered Call': { direction: 'bullish', type: 'credit' },
    'Short Put': { direction: 'bullish', type: 'credit' },
    'Short Call': { direction: 'bearish', type: 'credit' },
    'Short Strangle': { direction: 'neutral', type: 'credit' },
    'Short Straddle': { direction: 'neutral', type: 'credit' },
    'Bull Call Spread': { direction: 'bullish', type: 'debit' },
    'Bear Put Spread': { direction: 'bearish', type: 'debit' },
    'Long Call': { direction: 'bullish', type: 'debit' },
    'Long Put': { direction: 'bearish', type: 'debit' },
    'Long Strangle': { direction: 'neutral', type: 'debit' },
    'Long Straddle': { direction: 'neutral', type: 'debit' },
    'Shares': { direction: null, type: null, isShares: true }
};
