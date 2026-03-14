/**
 * Pure display/formatting helpers for the Positions page.
 * No reactive state dependencies — all functions are stateless.
 */
import { formatNumber } from '@/lib/formatters'

export function buildOptionStratUrl(strategyType, underlying, legs) {
  const SLUGS = {
    'Bull Put Spread': 'bull-put-spread',
    'Bull Call Spread': 'bull-call-spread',
    'Bear Put Spread': 'bear-put-spread',
    'Bear Call Spread': 'bear-call-spread',
  }
  const slug = SLUGS[strategyType]
  if (!slug || !underlying || !legs || legs.length !== 2) return null
  if (legs.some(l => !l.expiration || !l.option_type || l.strike == null)) return null

  const encodeLeg = (leg) => {
    const sign = leg.isShort ? '-' : ''
    const d = leg.expiration.replace(/-/g, '').slice(2, 8)
    const type = leg.option_type.toUpperCase().startsWith('P') ? 'P' : 'C'
    const strike = leg.strike % 1 === 0 ? String(Math.trunc(leg.strike)) : String(leg.strike)
    return `${sign}.${underlying}${d}${type}${strike}`
  }

  return `https://optionstrat.com/build/${slug}/${underlying}/${legs.map(encodeLeg).join(',')}`
}

export function formatDollar(value) {
  const abs = Math.abs(value || 0)
  return formatNumber(abs, abs >= 10000 ? 0 : 2)
}

export function dollarSizeClass(value) {
  return Math.abs(value || 0) >= 1000000 ? 'text-xs' : ''
}

export function getOptionType(leg) {
  if (leg.option_type === 'Call' || leg.option_type === 'C') return 'C'
  if (leg.option_type === 'Put' || leg.option_type === 'P') return 'P'
  if (leg.option_type) return leg.option_type.charAt(0).toUpperCase()
  const match = (leg.symbol || '').match(/\d{6}([CP])/)
  if (match) return match[1]
  return '—'
}

export function getSignedQuantity(leg) {
  const qty = leg.quantity || 0
  if (leg.quantity_direction === 'Short') return -qty
  return qty
}

export function getExpirationDate(leg) {
  if (!leg.expiration) return ''
  const dateStr = leg.expiration.substring(0, 10)
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function getStrikePrice(leg) {
  if (leg.strike && leg.strike > 0) return parseFloat(leg.strike.toFixed(2)).toString()
  const symbol = leg.symbol || ''
  const match = symbol.match(/([CP])(\d+)/)
  if (match && match[2].length >= 3) {
    return parseFloat(parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3)).toFixed(2)).toString()
  }
  return ''
}

export function getDTE(leg) {
  if (!leg.expiration) return null
  const dateStr = leg.expiration.substring(0, 10)
  const expDate = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.ceil((expDate - today) / (1000 * 60 * 60 * 24))
}

export function getGroupStrategyLabel(group) {
  if (group._isSubtotal) return ''
  if (group.strategy_type && group.strategy_type !== 'Unknown') return group.strategy_type
  return 'Unknown'
}

export function sortedLegs(positions) {
  return [...(positions || [])].sort((a, b) => {
    const expA = a.expiration || ''
    const expB = b.expiration || ''
    if (expA !== expB) return expA.localeCompare(expB)
    return (a.strike || 0) - (b.strike || 0)
  })
}

export function getAccountSymbol(accounts, accountNumber) {
  const account = accounts.find(a => a.account_number === accountNumber)
  if (!account) return '?'
  const name = (account.account_name || '').toUpperCase()
  if (name.includes('ROTH')) return 'R'
  if (name.includes('INDIVIDUAL')) return 'I'
  if (name.includes('TRADITIONAL')) return 'T'
  return name.charAt(0) || '?'
}
