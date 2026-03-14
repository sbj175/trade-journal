/**
 * Position enrichment, capital-at-risk, scenario analysis, and display helpers.
 * All functions are pure — no reactive state dependencies.
 */
import { bsGreeks, bsPrice } from './blackScholes'

// ==================== OCC SYMBOL PARSER ====================
export function parseOCCSymbol(symbol) {
  if (!symbol || symbol.length < 15) return null
  const match = symbol.match(/(\d{6})([CP])(\d{8})\s*$/)
  if (!match) return null
  const dateStr = match[1]
  const optionType = match[2]
  const strikeRaw = parseInt(match[3], 10)
  const strike = strikeRaw / 1000
  const year = 2000 + parseInt(dateStr.substring(0, 2), 10)
  const month = parseInt(dateStr.substring(2, 4), 10) - 1
  const day = parseInt(dateStr.substring(4, 6), 10)
  const expiration = new Date(year, month, day)
  return { optionType, strike, expiration }
}

// ==================== POSITION HELPERS ====================
export function getUnderlying(pos) {
  return pos.underlying_symbol || pos.underlying || ''
}

export function isOptionPosition(pos) {
  const t = (pos.instrument_type || '').toLowerCase()
  return t.includes('option')
}

export function getSignedQty(pos) {
  const qty = Math.abs(parseFloat(pos.quantity) || 0)
  const dir = (pos.quantity_direction || '').toLowerCase()
  return dir === 'short' ? -qty : qty
}

export function getOptionType(pos, occ) {
  const ot = (pos.option_type || '').toUpperCase()
  if (ot === 'C' || ot === 'CALL') return 'C'
  if (ot === 'P' || ot === 'PUT') return 'P'
  if (occ && occ.optionType) return occ.optionType
  const parsed = parseOCCSymbol(pos.symbol)
  return parsed ? parsed.optionType : 'C'
}

export function getDTE(pos, occ) {
  const expiry = pos.expires_at || pos.expiration
  let exp = null
  if (expiry) {
    exp = new Date(expiry)
  } else if (occ && occ.expiration) {
    exp = occ.expiration
  } else {
    const parsed = parseOCCSymbol(pos.symbol)
    if (parsed) exp = parsed.expiration
  }
  if (!exp) return 0
  const now = new Date()
  return Math.max(0, Math.ceil((exp - now) / (1000 * 60 * 60 * 24)))
}

function getIV(pos, quote) {
  if (quote.iv && quote.iv > 0) return quote.iv / 100
  return 0.30
}

// ==================== POSITION ENRICHMENT ====================
function basicPosition(pos, underlying, price) {
  const isOpt = isOptionPosition(pos)
  const signedQty = getSignedQty(pos)
  return {
    ...pos,
    _underlying: underlying,
    _underlyingPrice: price,
    _isOption: isOpt,
    _signedQty: signedQty,
    _strike: 0,
    _optionType: '',
    _dte: 0,
    _iv: 0,
    _posDelta: isOpt ? 0 : signedQty,
    _posGamma: 0, _posTheta: 0, _posVega: 0,
    _deltaDollars: isOpt ? 0 : signedQty * price,
    _notional: isOpt ? 0 : Math.abs(signedQty) * price,
    _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
  }
}

export function enrichPosition(pos, quotesMap) {
  const underlying = getUnderlying(pos)
  if (!underlying) return null
  const quote = quotesMap[underlying] || {}
  const underlyingPrice = quote.price || quote.mark || quote.last || 0
  if (underlyingPrice <= 0) {
    return basicPosition(pos, underlying, 0)
  }

  const isOpt = isOptionPosition(pos)
  const signedQty = getSignedQty(pos)

  if (isOpt) {
    const occ = parseOCCSymbol(pos.symbol)
    const strike = pos.strike_price || (occ ? occ.strike : 0)
    const optType = getOptionType(pos, occ)
    const dte = getDTE(pos, occ)
    if (strike <= 0 || dte <= 0) {
      return basicPosition(pos, underlying, underlyingPrice)
    }
    const T = Math.max(dte, 0.5) / 365
    const iv = getIV(pos, quote)
    const r = 0.045

    const greeks = bsGreeks(underlyingPrice, strike, T, r, iv, optType)

    return {
      ...pos,
      _underlying: underlying,
      _underlyingPrice: underlyingPrice,
      _isOption: true,
      _signedQty: signedQty,
      _strike: strike,
      _optionType: optType,
      _dte: dte,
      _iv: iv * 100,
      _posDelta: greeks.delta * signedQty * 100,
      _posGamma: greeks.gamma * signedQty * 100,
      _posTheta: greeks.theta * signedQty * 100,
      _posVega: greeks.vega * signedQty * 100,
      _deltaDollars: greeks.delta * signedQty * 100 * underlyingPrice,
      _notional: Math.abs(signedQty) * 100 * underlyingPrice,
      _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
    }
  } else {
    return {
      ...pos,
      _underlying: underlying,
      _underlyingPrice: underlyingPrice,
      _isOption: false,
      _signedQty: signedQty,
      _strike: 0,
      _optionType: '',
      _dte: 0,
      _iv: 0,
      _posDelta: signedQty,
      _posGamma: 0,
      _posTheta: 0,
      _posVega: 0,
      _deltaDollars: signedQty * underlyingPrice,
      _notional: Math.abs(signedQty) * underlyingPrice,
      _unrealizedPnl: parseFloat(pos.unrealized_pnl) || 0,
    }
  }
}

// ==================== CAPITAL AT RISK ====================
export function calcCapitalAtRisk(positions) {
  let totalRisk = 0
  const equities = positions.filter(p => !p._isOption)
  const options = positions.filter(p => p._isOption)

  equities.forEach(p => {
    totalRisk += Math.abs(p._signedQty) * p._underlyingPrice
  })

  const byExp = {}
  options.forEach(p => {
    const key = p._dte
    if (!byExp[key]) byExp[key] = []
    byExp[key].push(p)
  })

  for (const group of Object.values(byExp)) {
    const puts = group.filter(p => p._optionType === 'P')
    const calls = group.filter(p => p._optionType === 'C')
    totalRisk += matchSpreads(puts, 'P')
    totalRisk += matchSpreads(calls, 'C')
  }
  return totalRisk
}

function matchSpreads(legs, type) {
  if (legs.length === 0) return 0
  let risk = 0
  const shorts = legs.filter(p => p._signedQty < 0)
    .map(p => ({
      strike: p._strike, qty: Math.abs(p._signedQty), origQty: Math.abs(p._signedQty),
      price: p._underlyingPrice, mktVal: Math.abs(parseFloat(p.market_value) || 0),
      costBasis: parseFloat(p.cost_basis) || 0,
    }))
  const longs = legs.filter(p => p._signedQty > 0)
    .map(p => ({
      strike: p._strike, qty: Math.abs(p._signedQty), origQty: Math.abs(p._signedQty),
      price: p._underlyingPrice, mktVal: Math.abs(parseFloat(p.market_value) || 0),
      costBasis: parseFloat(p.cost_basis) || 0,
    }))

  for (const s of shorts) {
    const available = longs.filter(l => l.qty > 0 && l.strike !== s.strike)
    available.sort((a, b) => Math.abs(a.strike - s.strike) - Math.abs(b.strike - s.strike))

    for (const l of available) {
      if (s.qty <= 0) break
      if (l.qty <= 0) continue
      const matched = Math.min(s.qty, l.qty)
      const width = Math.abs(s.strike - l.strike)

      const sCostPer = s.costBasis / (s.origQty || 1)
      const lCostPer = l.costBasis / (l.origQty || 1)
      const netCost = (sCostPer + lCostPer) * matched

      if (netCost < 0) {
        risk += Math.abs(netCost)
      } else {
        risk += Math.max(0, width * matched * 100 - netCost)
      }

      s.qty -= matched
      l.qty -= matched
    }
    if (s.qty > 0) {
      risk += (type === 'P' ? s.strike : s.price) * s.qty * 100
    }
  }
  for (const l of longs) {
    if (l.qty > 0) risk += l.mktVal > 0 ? l.mktVal : 0
  }
  return risk
}

// ==================== THETA PROJECTION ====================
export function calcThetaProjection(enrichedPositions) {
  const days = []
  const dailyTheta = []
  const cumulative = []
  const expirationMarkers = []
  const optionPositions = enrichedPositions.filter(p => p._isOption && p._dte > 0)
  const r = 0.045
  let totalCum = 0

  const expirations = {}
  optionPositions.forEach(p => {
    const dte = p._dte
    if (dte > 0 && dte <= 45) {
      if (!expirations[dte]) expirations[dte] = []
      expirations[dte].push(p._underlying)
    }
  })

  for (let day = 0; day <= 45; day++) {
    days.push(day)
    let dayTheta = 0
    optionPositions.forEach(p => {
      const remainingDTE = p._dte - day
      if (remainingDTE <= 0) return
      const T = Math.max(remainingDTE, 0.5) / 365
      const iv = (p._iv || 30) / 100
      const greeks = bsGreeks(p._underlyingPrice, p._strike, T, r, iv, p._optionType)
      dayTheta += greeks.theta * p._signedQty * 100
    })
    totalCum += dayTheta
    dailyTheta.push(Math.round(dayTheta * 100) / 100)
    cumulative.push(Math.round(totalCum * 100) / 100)

    if (expirations[day]) {
      const symbols = [...new Set(expirations[day])]
      expirationMarkers.push({
        day,
        label: symbols.slice(0, 2).join(', ') + (symbols.length > 2 ? '...' : '') + ' exp',
      })
    }
  }

  return { days, dailyTheta, cumulative, expirationMarkers }
}

// ==================== SCENARIO ANALYSIS ====================
export function calcScenarios(enrichedPositions) {
  const moves = [-10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10]
  const labels = moves.map(m => (m >= 0 ? '+' : '') + m + '%')
  const pnl = []
  const r = 0.045

  moves.forEach(pctMove => {
    let totalPnlChange = 0
    enrichedPositions.forEach(pos => {
      const currentPrice = pos._underlyingPrice
      if (currentPrice <= 0) return
      const newPrice = currentPrice * (1 + pctMove / 100)

      if (pos._isOption) {
        const T = Math.max(pos._dte, 0.5) / 365
        const iv = (pos._iv || 30) / 100
        const currentOptPrice = bsPrice(currentPrice, pos._strike, T, r, iv, pos._optionType)
        const newOptPrice = bsPrice(newPrice, pos._strike, T, r, iv, pos._optionType)
        totalPnlChange += (newOptPrice - currentOptPrice) * pos._signedQty * 100
      } else {
        totalPnlChange += (newPrice - currentPrice) * pos._signedQty
      }
    })
    pnl.push(Math.round(totalPnlChange))
  })

  return { labels, pnl }
}

// ==================== DISPLAY HELPERS ====================
export function formatDelta(v) {
  if (v == null || isNaN(v)) return '0.0'
  const sign = v >= 0 ? '+' : ''
  return sign + v.toFixed(1)
}

export function shortNumber(v) {
  v = Math.abs(v)
  if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
  if (v >= 1000) return (v / 1000).toFixed(1) + 'K'
  return v.toFixed(0)
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
