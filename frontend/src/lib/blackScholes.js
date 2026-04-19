/**
 * Black-Scholes pricing and Greeks.
 * All functions are pure — no reactive state dependencies.
 */

export function normalCDF(x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911
  const sign = x < 0 ? -1 : 1
  x = Math.abs(x) / Math.sqrt(2)
  const t = 1.0 / (1.0 + p * x)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x)
  return 0.5 * (1.0 + sign * y)
}

export function normalPDF(x) {
  return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI)
}

export function bsGreeks(S, K, T, r, sigma, type) {
  if (T <= 0.0001 || sigma <= 0 || S <= 0 || K <= 0) {
    return { delta: 0, gamma: 0, theta: 0, vega: 0 }
  }
  const sqrtT = Math.sqrt(T)
  const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT
  const nd1 = normalCDF(d1)
  const phid1 = normalPDF(d1)

  let delta, theta
  if (type === 'C') {
    delta = nd1
    theta = (-S * phid1 * sigma / (2 * sqrtT) - r * K * Math.exp(-r * T) * normalCDF(d2)) / 365
  } else {
    delta = nd1 - 1
    theta = (-S * phid1 * sigma / (2 * sqrtT) + r * K * Math.exp(-r * T) * normalCDF(-d2)) / 365
  }
  const gamma = phid1 / (S * sigma * sqrtT)
  const vega = S * phid1 * sqrtT / 100
  return { delta, gamma, theta, vega }
}

export function bsPrice(S, K, T, r, sigma, type) {
  if (T <= 0.0001) {
    return type === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0)
  }
  const sqrtT = Math.sqrt(T)
  const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT
  if (type === 'C') {
    return S * normalCDF(d1) - K * Math.exp(-r * T) * normalCDF(d2)
  } else {
    return K * Math.exp(-r * T) * normalCDF(-d2) - S * normalCDF(-d1)
  }
}
