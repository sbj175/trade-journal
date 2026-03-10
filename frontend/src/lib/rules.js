/**
 * Rules-based advice engine for Roll Analysis.
 *
 * Each rule evaluates position metrics and returns a signal (or null).
 * Signals are composable — multiple rules can fire simultaneously.
 * Results are sorted by priority (highest first).
 */

/**
 * @typedef {Object} Signal
 * @property {string} id       - Unique rule identifier
 * @property {'action'|'warning'|'hold'} type - Signal category
 * @property {number} priority - Sort order (higher = more urgent, displayed first)
 * @property {string} label    - Short badge-style label
 * @property {string} color    - Tailwind color key: 'red'|'orange'|'yellow'|'green'|'blue'
 * @property {string} message  - Human-readable recommendation
 */

/**
 * @typedef {Object} RuleMetrics
 * @property {number} pctMaxProfit      - Current P&L as % of max profit (positive = profit)
 * @property {number} pctMaxLoss        - Current loss as % of max loss (0 if profitable)
 * @property {number} currentPnL        - Raw current P&L in dollars
 * @property {number} rewardToRiskRaw   - Remaining reward / remaining risk ratio
 * @property {number} proximityToShort  - Distance from underlying to short strike (%)
 * @property {number} deltaSaturation   - Short delta as % (0–100)
 * @property {number} netTheta          - Net theta in $/day
 * @property {number} dte               - Days to expiration
 * @property {boolean} isCredit         - True for credit spreads
 * @property {number} maxProfit         - Max profit in dollars (raw, not formatted)
 * @property {number} maxLoss           - Max loss in dollars (raw, positive number)
 * @property {number} profitTarget      - Configured profit target %
 * @property {number} lossLimit         - Configured loss limit %
 */

const RULES = [
  // ── High-priority actions ──────────────────────────────────────────

  {
    id: 'loss-limit',
    evaluate: (m) => {
      if (m.currentPnL >= 0) return null
      const lossMetric = m.isCredit
        ? Math.abs(m.pctMaxProfit)
        : m.pctMaxLoss
      if (lossMetric < m.lossLimit) return null
      const lossDesc = m.isCredit ? 'of credit received' : 'of debit paid'
      return {
        id: 'loss-limit',
        type: 'action',
        priority: 100,
        label: 'Loss Limit',
        color: 'red',
        message: `Loss limit hit: ${lossMetric.toFixed(1)}% ${lossDesc}. Consider closing or rolling.`,
      }
    },
  },

  {
    id: 'dte-in-loss',
    evaluate: (m) => {
      if (m.dte > 21 || m.dte <= 0 || m.currentPnL >= 0) return null
      return {
        id: 'dte-in-loss',
        type: 'action',
        priority: 90,
        label: 'Urgent',
        color: 'red',
        message: `${m.dte}d to expiry and in a loss — evaluate closing or rolling immediately.`,
      }
    },
  },

  // ── Medium-priority actions ────────────────────────────────────────

  {
    id: 'near-short-strike',
    evaluate: (m) => {
      if (m.proximityToShort >= 5 || m.dte <= 21) return null
      return {
        id: 'near-short-strike',
        type: 'action',
        priority: 70,
        label: 'Near Short',
        color: 'orange',
        message: `Price is ${m.proximityToShort}% from short strike with ${m.dte}d remaining. Consider rolling or closing.`,
      }
    },
  },

  {
    id: 'poor-rr-with-loss',
    evaluate: (m) => {
      if (m.rewardToRiskRaw >= 1 || m.currentPnL >= 0) return null
      const lossPct = m.isCredit
        ? Math.abs(m.pctMaxProfit)
        : m.pctMaxLoss
      if (lossPct < 20) return null
      return {
        id: 'poor-rr-with-loss',
        type: 'action',
        priority: 60,
        label: 'Poor R:R',
        color: 'orange',
        message: `Reward:Risk is ${m.rewardToRiskRaw.toFixed(1)}:1 with ${lossPct.toFixed(0)}% loss incurred. Evaluate rolling or closing.`,
      }
    },
  },

  {
    id: 'profit-target',
    evaluate: (m) => {
      if (m.pctMaxProfit < m.profitTarget) return null
      return {
        id: 'profit-target',
        type: 'action',
        priority: 50,
        label: 'Profit Target',
        color: 'green',
        message: `Consider closing: ${m.pctMaxProfit.toFixed(1)}% of max profit captured.`,
      }
    },
  },

  // ── Warnings ───────────────────────────────────────────────────────

  {
    id: 'delta-saturation',
    evaluate: (m) => {
      if (m.deltaSaturation < 40) return null
      const severity = m.deltaSaturation >= 65 ? 'High' : 'Elevated'
      return {
        id: 'delta-saturation',
        type: 'warning',
        priority: 40,
        label: `${severity} Delta`,
        color: m.deltaSaturation >= 65 ? 'red' : 'orange',
        message: `Delta saturation at ${m.deltaSaturation.toFixed(0)}% — directional risk is ${severity.toLowerCase()}.`,
      }
    },
  },

  {
    id: 'late-stage',
    evaluate: (m) => {
      // Only fire as standalone warning when NOT already in a loss
      // (dte-in-loss covers the loss + low DTE case)
      if (m.dte > 21 || m.dte <= 0 || m.currentPnL < 0) return null
      const isClose = m.dte <= 14
      return {
        id: 'late-stage',
        type: isClose ? 'action' : 'warning',
        priority: isClose ? 35 : 30,
        label: `${m.dte}d Left`,
        color: isClose ? 'orange' : 'yellow',
        message: isClose
          ? `${m.dte} days to expiry — consider closing to lock in profit and free up capital.`
          : `${m.dte} days to expiry — approaching close window, evaluate taking profits.`,
      }
    },
  },

  // ── Hold signals ───────────────────────────────────────────────────

  {
    id: 'hold-favorable',
    evaluate: (m) => {
      if (m.netTheta <= 0 || m.dte <= 45 || m.proximityToShort <= 15) return null
      return {
        id: 'hold-favorable',
        type: 'hold',
        priority: 10,
        label: 'Hold',
        color: 'blue',
        message: `Favorable position: positive theta, ${m.dte}d remaining, price ${m.proximityToShort}% from short strike.`,
      }
    },
  },
]

/**
 * Evaluate all rules against position metrics.
 *
 * @param {RuleMetrics} metrics - Computed position metrics
 * @returns {Signal[]} Sorted signals (highest priority first)
 */
export function evaluateRules(metrics) {
  const signals = []
  for (const rule of RULES) {
    const signal = rule.evaluate(metrics)
    if (signal) signals.push(signal)
  }
  signals.sort((a, b) => b.priority - a.priority)
  return signals
}
