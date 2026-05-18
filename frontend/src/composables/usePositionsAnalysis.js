/**
 * Black-Scholes math, Greeks, and roll analysis for the Positions page.
 * Pure functions — no reactive state dependencies.
 */
import { formatNumber } from '@/lib/formatters'
import { getGroupStrategyLabel } from '@/composables/usePositionsDisplay'

export function normalCDF(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327
  const p = d * Math.exp(-x * x / 2) * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x > 0 ? 1 - p : p
}

export function normalPDF(x) {
  return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI)
}

export function bsDelta(S, K, T, r, sigma, isCall) {
  if (T <= 0 || sigma <= 0) return isCall ? (S > K ? 1 : 0) : (S < K ? -1 : 0)
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T))
  return isCall ? normalCDF(d1) : normalCDF(d1) - 1
}

export function bsGreeks(S, K, T, r, sigma, isCall) {
  if (T <= 0.0001 || sigma <= 0 || S <= 0 || K <= 0) {
    return { delta: 0, gamma: 0, theta: 0, vega: 0 }
  }
  const sqrtT = Math.sqrt(T)
  const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT
  const nd1 = normalCDF(d1)
  const phid1 = normalPDF(d1)
  const Kert = K * Math.exp(-r * T)

  const delta = isCall ? nd1 : nd1 - 1
  const gamma = phid1 / (S * sigma * sqrtT)
  const theta = isCall
    ? (-(S * phid1 * sigma) / (2 * sqrtT) - r * Kert * normalCDF(d2)) / 365
    : (-(S * phid1 * sigma) / (2 * sqrtT) + r * Kert * normalCDF(-d2)) / 365
  const vega = S * phid1 * sqrtT / 100

  return { delta, gamma, theta, vega }
}

export function getEffectiveIV(underlyingQuotes, underlying) {
  const quote = underlyingQuotes[underlying]
  if (quote && quote.iv && quote.iv > 0) return quote.iv / 100
  return 0.30
}

export function getLegGreeks(leg, underlyingPrice, underlyingQuotes, getMinDTEFn) {
  const optionQuote = underlyingQuotes[leg.symbol]

  // Prefer broker Greeks from DXFeed streaming
  if (optionQuote && optionQuote.delta != null) {
    return {
      delta: optionQuote.delta,
      gamma: optionQuote.gamma || 0,
      theta: optionQuote.theta || 0,
      vega: optionQuote.vega || 0,
      source: 'broker',
    }
  }

  // Fallback: Black-Scholes
  const getStrike = (l) => {
    if (l.strike && l.strike > 0) return l.strike
    const match = (l.symbol || '').match(/([CP])(\d+)/)
    if (match && match[2].length >= 3) return parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3))
    return null
  }
  const getOptType = (l) => {
    if (l.option_type === 'Call') return 'C'
    if (l.option_type === 'Put') return 'P'
    const match = (l.symbol || '').match(/\d{6}([CP])/)
    return match ? match[1] : null
  }

  const strike = getStrike(leg)
  const isCall = getOptType(leg) === 'C'
  const dte = getMinDTEFn({ positions: [leg] }) || 0
  if (!strike || dte <= 0) return { delta: 0, gamma: 0, theta: 0, vega: 0, source: 'none' }

  const T = Math.max(dte, 0.5) / 365
  const iv = getEffectiveIV(underlyingQuotes, leg.underlying || '')
  const greeks = bsGreeks(underlyingPrice, strike, T, 0.045, iv, isCall)
  return { ...greeks, source: 'bs' }
}

/**
 * Compute roll analysis for a spread position group.
 * All reactive values are passed in explicitly.
 */
export function getRollAnalysis(group, {
  underlyingQuotes, rollAlertSettings, rollAnalysisMode, strategyTargets,
  getGroupOpenPnLFn, getMinDTEFn,
}) {
  const strategy = getGroupStrategyLabel(group)
  const supportedStrategies = ['Bull Call Spread', 'Bear Put Spread', 'Bull Put Spread', 'Bear Call Spread']
  if (!supportedStrategies.includes(strategy)) return null
  if (!rollAlertSettings.enabled) return null

  const positions = group.positions || []
  const underlying = group.underlying
  const quote = underlyingQuotes[underlying]
  if (!quote || !quote.price) return null
  const underlyingPrice = quote.price

  const getStrike = (p) => {
    if (p.strike && p.strike > 0) return p.strike
    const match = (p.symbol || '').match(/([CP])(\d+)/)
    if (match && match[2].length >= 3) return parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3))
    return null
  }
  const isShort = (p) => p.quantity_direction === 'Short' || (p.quantity || 0) < 0
  const getOptType = (p) => {
    if (p.option_type === 'Call') return 'C'
    if (p.option_type === 'Put') return 'P'
    const match = (p.symbol || '').match(/\d{6}([CP])/)
    return match ? match[1] : null
  }

  const optionPositions = positions.filter(p => p.instrument_type && p.instrument_type.includes('OPTION'))
  if (optionPositions.length < 2) return null

  let longLeg = null, shortLeg = null
  for (const p of optionPositions) {
    if (isShort(p)) shortLeg = p
    else longLeg = p
  }
  if (!longLeg || !shortLeg) return null

  const longStrike = getStrike(longLeg)
  const shortStrike = getStrike(shortLeg)
  if (!longStrike || !shortStrike) return null

  const spreadWidth = Math.abs(shortStrike - longStrike)
  const numContracts = Math.abs(longLeg.quantity || 0)
  const totalCostBasis = Math.abs(positions.reduce((sum, p) => sum + (p.cost_basis || 0), 0))

  const isCredit = strategy === 'Bull Put Spread' || strategy === 'Bear Call Spread'

  let maxProfit, maxLoss
  if (isCredit) {
    maxProfit = totalCostBasis
    maxLoss = (spreadWidth * 100 * numContracts) - totalCostBasis
  } else {
    maxProfit = (spreadWidth * 100 * numContracts) - totalCostBasis
    maxLoss = totalCostBasis
  }

  if (maxProfit <= 0 || maxLoss <= 0) return null

  const openPnL = getGroupOpenPnLFn(group)
  const realizedPnL = group.realized_pnl || 0
  const useChainMode = rollAnalysisMode === 'chain' && realizedPnL !== 0

  const currentPnL = useChainMode ? openPnL + realizedPnL : openPnL

  let effectiveMaxProfit = maxProfit
  let effectiveMaxLoss = maxLoss
  if (useChainMode) {
    effectiveMaxProfit = Math.max(maxProfit + Math.min(realizedPnL, 0), 1)
    effectiveMaxLoss = Math.max(maxLoss - Math.min(realizedPnL, 0), 1)
  }

  const pctMaxProfit = ((currentPnL / effectiveMaxProfit) * 100).toFixed(1)
  const pctMaxLoss = currentPnL < 0 ? ((Math.abs(currentPnL) / effectiveMaxLoss) * 100).toFixed(1) : '0.0'

  let pnlLabel, pnlValue, pnlPositive, pnlTooltip
  if (currentPnL >= 0) {
    pnlLabel = '%Max'
    pnlValue = pctMaxProfit + '%'
    pnlPositive = true
    pnlTooltip = `${pctMaxProfit}% of the $${effectiveMaxProfit.toFixed(0)} maximum profit has been captured.\nMax profit = ${isCredit ? 'credit received' : 'spread width − debit paid'}.`
  } else {
    pnlLabel = '%Max Loss'
    const lossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss)
    pnlValue = lossMetric.toFixed(1) + '%'
    pnlPositive = false
    pnlTooltip = `${lossMetric.toFixed(1)}% of the $${effectiveMaxLoss.toFixed(0)} maximum loss has been incurred.\nMax loss = ${isCredit ? 'spread width − credit received' : 'debit paid'}.`
  }

  const rewardRemaining = effectiveMaxProfit - currentPnL
  const riskRemaining = effectiveMaxLoss + currentPnL
  const rewardToRiskRaw = riskRemaining > 0 ? rewardRemaining / riskRemaining : 99
  const rewardToRisk = rewardToRiskRaw >= 10 ? '10:1+' : rewardToRiskRaw.toFixed(1) + ':1'

  const dte = getMinDTEFn(group) || 0

  // Per-share exit prices for the trader's standard close-out rules. Pulled
  // from the same StrategyTarget row the rest of the app uses; default to
  // 50% / 50% when unset.
  const targets = strategyTargets?.[strategy] || {}
  const exitProfitPct = targets.profit_target_pct ?? 50
  const exitLossPct = targets.loss_target_pct ?? 50
  const basisPerShare = numContracts > 0 ? totalCostBasis / (numContracts * 100) : 0
  let profitExitPrice = null, lossExitPrice = null
  if (basisPerShare > 0 && spreadWidth > 0) {
    if (isCredit) {
      // Credit: opened at +C, close by buying back. Lower buy-back = more profit kept.
      profitExitPrice = basisPerShare * (1 - exitProfitPct / 100)
      lossExitPrice = basisPerShare + (spreadWidth - basisPerShare) * (exitLossPct / 100)
    } else {
      // Debit: opened at -D, close by selling back. Higher sell-back = more profit.
      profitExitPrice = basisPerShare + (spreadWidth - basisPerShare) * (exitProfitPct / 100)
      lossExitPrice = basisPerShare * (1 - exitLossPct / 100)
    }
  }

  // Net position Greeks
  const longGreeks = getLegGreeks(longLeg, underlyingPrice, underlyingQuotes, getMinDTEFn)
  const shortGreeks = getLegGreeks(shortLeg, underlyingPrice, underlyingQuotes, getMinDTEFn)
  const longQty = Math.abs(longLeg.quantity || 0)
  const shortQty = Math.abs(shortLeg.quantity || 0)

  const netDelta = ((longGreeks.delta * longQty) + (shortGreeks.delta * -shortQty)) * 100
  const netGamma = ((longGreeks.gamma * longQty) + (shortGreeks.gamma * -shortQty)) * 100
  const netTheta = ((longGreeks.theta * longQty) + (shortGreeks.theta * -shortQty)) * 100
  const netVega = ((longGreeks.vega * longQty) + (shortGreeks.vega * -shortQty)) * 100

  const gcd = (a, b) => b === 0 ? a : gcd(b, a % b)
  const qtyGcd = gcd(longQty, shortQty)
  const deltaPerQty = qtyGcd > 0 ? netDelta / qtyGcd : netDelta

  // Current per-share market value of the spread (the order price to close
  // now). Derived from openPnL vs the entry basis — sign convention flips
  // between debit (sell-to-close, want price up) and credit (buy-to-close,
  // want price down).
  let currentPricePerShare = null
  if (basisPerShare > 0 && numContracts > 0) {
    const openPnLPerShare = openPnL / (numContracts * 100)
    currentPricePerShare = isCredit
      ? basisPerShare - openPnLPerShare
      : basisPerShare + openPnLPerShare
  }

  // Context column — Entry / Current / two target exits, sorted highest-to-
  // lowest by per-share price so the relative order across debit vs credit
  // (and across different stages of the trade) reads naturally.
  const contextRows = []
  if (basisPerShare > 0) {
    contextRows.push({ label: 'Entry Price', value: basisPerShare })
  }
  if (currentPricePerShare != null) {
    contextRows.push({ label: 'Current Price', value: currentPricePerShare })
  }
  if (profitExitPrice != null) {
    contextRows.push({
      label: `${exitProfitPct}% Max Profit Exit`,
      value: profitExitPrice,
      tooltip: `Per-share close-out price at which ${exitProfitPct}% of max profit is captured (configure in Settings → Strategy Targets).`,
    })
  }
  if (lossExitPrice != null) {
    contextRows.push({
      label: `${exitLossPct}% Max Loss Exit`,
      value: lossExitPrice,
      tooltip: `Per-share close-out price at which ${exitLossPct}% of max loss is realized (configure in Settings → Strategy Targets).`,
    })
  }
  contextRows.sort((a, b) => b.value - a.value)

  return {
    pnlLabel, pnlValue, pnlPositive, pnlTooltip,
    pctMaxProfit, pctMaxLoss, rewardToRisk, rewardToRiskRaw,
    rewardRemaining: formatNumber(rewardRemaining, 0),
    riskRemaining: formatNumber(riskRemaining, 0),
    isCredit,
    maxProfit: formatNumber(effectiveMaxProfit, 0),
    maxLoss: formatNumber(effectiveMaxLoss, 0),
    netDelta, deltaPerQty, qtyGcd, netGamma, netTheta, netVega,
    exitProfitPct, exitLossPct, profitExitPrice, lossExitPrice,
    entryPricePerShare: basisPerShare, currentPricePerShare,
    contextRows,
  }
}
