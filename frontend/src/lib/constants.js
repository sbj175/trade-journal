/**
 * Shared constants for OptionLedger Vue pages.
 * Mirrors static/js/constants.js for Alpine pages.
 */

export const STRATEGY_CATEGORIES = {
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
  'Calendar Spread': { direction: 'neutral', type: 'debit' },
  'Diagonal Spread': { direction: 'neutral', type: 'debit' },
  'PMCC': { direction: 'bullish', type: 'debit' },
  'Jade Lizard': { direction: 'bullish', type: 'credit' },
  'Collar': { direction: 'neutral', type: 'mixed' },
  'Shares': { direction: null, type: null, isShares: true },
}
