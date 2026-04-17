/**
 * Shared constants for OptionLedger Vue pages.
 */

export function accountDotColor(accountSymbol) {
  if (accountSymbol === 'R') return '#f59e0b'
  if (accountSymbol === 'I') return '#38bdf8'
  if (accountSymbol === 'T') return '#4ade80'
  return '#9ca3af'
}

export function getAccountTooltip(accounts, accountNumber) {
  const acct = accounts.find(a => a.account_number === accountNumber)
  return acct?.account_name || accountNumber
}

export function tickerLogoUrl(symbol) {
  return `https://img.logokit.com/ticker/${symbol}?token=pk_fr7585c85ca0d987ceb070`
}

export const DEFAULT_TAG_COLOR = '#6b7280'

export function accountSortOrder(accountName) {
  const n = (accountName || '').toUpperCase()
  if (n.includes('ROTH')) return 1
  if (n.includes('INDIVIDUAL')) return 2
  if (n.includes('TRADITIONAL')) return 3
  return 4
}

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
  'Bull ZEBRA': { direction: 'bullish', type: 'debit' },
  'Bear ZEBRA': { direction: 'bearish', type: 'debit' },
  'Bull Call Spread': { direction: 'bullish', type: 'debit' },
  'Bear Put Spread': { direction: 'bearish', type: 'debit' },
  'Long Call': { direction: 'bullish', type: 'debit' },
  'Long Put': { direction: 'bearish', type: 'debit' },
  'Long Strangle': { direction: 'neutral', type: 'debit' },
  'Long Straddle': { direction: 'neutral', type: 'debit' },
  'Calendar Spread': { direction: 'neutral', type: 'debit' },
  'Diagonal Spread': { direction: 'neutral', type: 'debit' },
  'Diagonal Call Spread': { direction: 'bullish', type: 'debit' },
  'Jade Lizard': { direction: 'bullish', type: 'credit' },
  'Collar': { direction: 'neutral', type: 'mixed' },
  'Shares': { direction: null, type: null, isShares: true },
}
