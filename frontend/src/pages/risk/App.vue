<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber } from '@/lib/formatters'

const Auth = useAuth()

// ==================== STATE ====================
const rawPositions = ref({})
const accountBalances = ref({})
const quotes = ref({})
const accounts = ref([])
const selectedAccount = ref('')
const isLoading = ref(true)
const error = ref(null)
const liveQuotesActive = ref(false)
const greeksSource = ref('Black-Scholes')
const sortColumn = ref('deltaDollars')
const sortDirection = ref('desc')

// Nav auth
const authEnabled = ref(false)
const userEmail = ref('')

// Internal (non-reactive)
let ws = null
let chartTimer = null
const charts = {}

// ==================== COMPUTED ====================
const allPositions = computed(() => {
  let all = []
  const sources = selectedAccount.value
    ? { [selectedAccount.value]: rawPositions.value[selectedAccount.value] || [] }
    : rawPositions.value
  for (const [, positions] of Object.entries(sources)) {
    if (Array.isArray(positions)) all.push(...positions)
  }
  return all
})

const enrichedPositions = computed(() => {
  return allPositions.value.map(p => enrichPosition(p)).filter(Boolean)
})

const underlyingGroups = computed(() => {
  const groups = {}
  enrichedPositions.value.forEach(pos => {
    const u = pos._underlying
    if (!groups[u]) {
      groups[u] = {
        underlying: u, positions: [],
        netDelta: 0, netGamma: 0, netTheta: 0, netVega: 0,
        deltaDollars: 0, maxRisk: 0, unrealizedPnl: 0,
        underlyingPrice: 0, positionCount: 0,
      }
    }
    const g = groups[u]
    g.positions.push(pos)
    g.netDelta += pos._posDelta
    g.netGamma += pos._posGamma
    g.netTheta += pos._posTheta
    g.netVega += pos._posVega
    g.deltaDollars += pos._deltaDollars
    g.unrealizedPnl += pos._unrealizedPnl
    g.underlyingPrice = pos._underlyingPrice
    g.positionCount++
  })
  for (const g of Object.values(groups)) {
    g.maxRisk = calcCapitalAtRisk(g.positions)
  }
  return Object.values(groups)
})

const sortedGroups = computed(() => {
  const groups = [...underlyingGroups.value]
  const col = sortColumn.value
  const dir = sortDirection.value === 'asc' ? 1 : -1
  groups.sort((a, b) => {
    const va = a[col], vb = b[col]
    if (col === 'underlying') return dir * String(va).localeCompare(String(vb))
    if (col === 'deltaDollars' || col === 'netDelta' || col === 'netTheta' || col === 'netVega') {
      return dir * (Math.abs(va) - Math.abs(vb))
    }
    return dir * ((va || 0) - (vb || 0))
  })
  return groups
})

const portfolioTotals = computed(() => {
  const groups = underlyingGroups.value
  return {
    netDelta: groups.reduce((s, g) => s + g.netDelta, 0),
    netGamma: groups.reduce((s, g) => s + g.netGamma, 0),
    netTheta: groups.reduce((s, g) => s + g.netTheta, 0),
    netVega: groups.reduce((s, g) => s + g.netVega, 0),
    deltaDollars: groups.reduce((s, g) => s + g.deltaDollars, 0),
    totalMaxRisk: groups.reduce((s, g) => s + g.maxRisk, 0),
    totalPnl: groups.reduce((s, g) => s + g.unrealizedPnl, 0),
    positionCount: enrichedPositions.value.length,
    underlyingCount: groups.length,
  }
})

const currentBalance = computed(() => {
  if (!selectedAccount.value || selectedAccount.value === '') {
    const vals = Object.values(accountBalances.value)
    if (vals.length === 0) return null
    return vals.reduce((acc, b) => ({
      cash_balance: (acc.cash_balance || 0) + (b.cash_balance || 0),
      derivative_buying_power: (acc.derivative_buying_power || 0) + (b.derivative_buying_power || 0),
      equity_buying_power: (acc.equity_buying_power || 0) + (b.equity_buying_power || 0),
      net_liquidating_value: (acc.net_liquidating_value || 0) + (b.net_liquidating_value || 0),
    }), {})
  }
  return accountBalances.value[selectedAccount.value] || null
})

const bpUtilization = computed(() => {
  const bal = currentBalance.value
  if (!bal || !bal.net_liquidating_value) return 0
  const nlv = bal.net_liquidating_value
  const dbp = bal.derivative_buying_power || 0
  if (nlv <= 0) return 0
  return Math.max(0, Math.min(100, ((nlv - dbp) / nlv) * 100))
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  await Auth.requireAuth()
  await Auth.requireTastytrade()

  // Auth info for nav
  authEnabled.value = Auth.isAuthEnabled?.() || false
  if (authEnabled.value) {
    const user = Auth.getUser?.()
    userEmail.value = user?.email || ''
  }

  await fetchData()
  selectedAccount.value = localStorage.getItem('trade_journal_selected_account') || ''
  connectWebSocket()
})

onUnmounted(() => {
  if (ws) {
    ws.onclose = null // prevent reconnect
    ws.close()
    ws = null
  }
  if (chartTimer) {
    clearTimeout(chartTimer)
    chartTimer = null
  }
  // Destroy charts
  Object.values(charts).forEach(c => c.destroy?.())
})

// ==================== DATA FETCHING ====================
async function fetchData() {
  isLoading.value = true
  try {
    const [posRes, balRes, acctRes] = await Promise.all([
      Auth.authFetch('/api/positions'),
      Auth.authFetch('/api/account-balances'),
      Auth.authFetch('/api/accounts'),
    ])
    if (posRes.ok) rawPositions.value = await posRes.json()
    if (balRes.ok) {
      const balData = await balRes.json()
      const balances = balData.balances || balData
      const balMap = {}
      if (Array.isArray(balances)) {
        balances.forEach(b => { balMap[b.account_number] = b })
      }
      accountBalances.value = balMap
    }
    if (acctRes.ok) {
      const acctData = await acctRes.json()
      const list = acctData.accounts || acctData || []
      list.sort((a, b) => {
        const getOrder = (name) => {
          const n = (name || '').toUpperCase()
          if (n.includes('ROTH')) return 1
          if (n.includes('INDIVIDUAL')) return 2
          if (n.includes('TRADITIONAL')) return 3
          return 4
        }
        return getOrder(a.account_name) - getOrder(b.account_name)
      })
      accounts.value = list
    }
  } catch (e) {
    error.value = e.message
    console.error('Failed to fetch data:', e)
  }
  isLoading.value = false
  await nextTick()
  if (allPositions.value.length > 0) renderAllCharts()
}

// ==================== WEBSOCKET ====================
async function connectWebSocket() {
  const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes')
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    console.log('WebSocket connected')
    setTimeout(() => subscribeToQuotes(), 500)
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'quotes' && msg.data) {
        quotes.value = { ...quotes.value, ...msg.data }
        liveQuotesActive.value = true
        const hasStreamGreeks = Object.values(msg.data).some(q => q.delta != null)
        if (hasStreamGreeks) greeksSource.value = 'DXFeed + Black-Scholes'
        debouncedUpdateCharts()
      }
    } catch (e) { /* ignore parse errors */ }
  }

  ws.onclose = () => {
    liveQuotesActive.value = false
    setTimeout(() => connectWebSocket(), 5000)
  }

  ws.onerror = () => { /* handled by onclose */ }
}

function subscribeToQuotes() {
  const symbols = [...new Set(allPositions.value.map(p => getUnderlying(p)).filter(Boolean))]
  if (symbols.length > 0 && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ subscribe: symbols }))
  }
}

function debouncedUpdateCharts() {
  if (chartTimer) return
  chartTimer = setTimeout(() => {
    chartTimer = null
    renderAllCharts()
  }, 2000)
}

// ==================== OCC SYMBOL PARSER ====================
function parseOCCSymbol(symbol) {
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

// ==================== POSITION ENRICHMENT ====================
function enrichPosition(pos) {
  const underlying = getUnderlying(pos)
  if (!underlying) return null
  const quote = quotes.value[underlying] || {}
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

function getIV(pos, quote) {
  if (quote.iv && quote.iv > 0) return quote.iv / 100
  return 0.30
}

function getUnderlying(pos) {
  return pos.underlying_symbol || pos.underlying || ''
}

function isOptionPosition(pos) {
  const t = (pos.instrument_type || '').toLowerCase()
  return t.includes('option')
}

function getOptionType(pos, occ) {
  const ot = (pos.option_type || '').toUpperCase()
  if (ot === 'C' || ot === 'CALL') return 'C'
  if (ot === 'P' || ot === 'PUT') return 'P'
  if (occ && occ.optionType) return occ.optionType
  const parsed = parseOCCSymbol(pos.symbol)
  return parsed ? parsed.optionType : 'C'
}

function getDTE(pos, occ) {
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

// ==================== CAPITAL AT RISK ====================
function calcCapitalAtRisk(positions) {
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

function getSignedQty(pos) {
  const qty = Math.abs(parseFloat(pos.quantity) || 0)
  const dir = (pos.quantity_direction || '').toLowerCase()
  return dir === 'short' ? -qty : qty
}

// ==================== BLACK-SCHOLES ====================
function normalCDF(x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911
  const sign = x < 0 ? -1 : 1
  x = Math.abs(x) / Math.sqrt(2)
  const t = 1.0 / (1.0 + p * x)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x)
  return 0.5 * (1.0 + sign * y)
}

function normalPDF(x) {
  return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI)
}

function bsGreeks(S, K, T, r, sigma, type) {
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

function bsPrice(S, K, T, r, sigma, type) {
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

// ==================== CHART RENDERING ====================
function renderAllCharts() {
  if (underlyingGroups.value.length === 0) return
  renderDeltaChart()
  renderThetaChart()
  renderTreemapChart()
  renderScenarioChart()
}

function renderDeltaChart() {
  const groups = [...underlyingGroups.value].sort((a, b) => Math.abs(b.deltaDollars) - Math.abs(a.deltaDollars)).slice(0, 15)
  const categories = groups.map(g => g.underlying)
  const values = groups.map(g => Math.round(g.deltaDollars))

  const options = {
    chart: {
      type: 'bar', height: 280, background: 'transparent', toolbar: { show: false },
      animations: { enabled: true, easing: 'easeinout', speed: 400 },
    },
    series: [{ name: 'Delta $', data: values }],
    plotOptions: {
      bar: {
        horizontal: true, borderRadius: 3, barHeight: '70%',
        colors: { ranges: [{ from: -9999999, to: -0.01, color: '#fe676c' }, { from: 0, to: 9999999, color: '#55aa71' }] },
      },
    },
    xaxis: {
      categories,
      labels: { style: { colors: '#868c99', fontSize: '11px' }, formatter: v => '$' + shortNumber(v) },
    },
    yaxis: { labels: { style: { colors: '#d1d4dc', fontSize: '12px', fontWeight: 600 } } },
    grid: { borderColor: '#2a2e39', xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } } },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) + ' delta exposure' },
    },
    dataLabels: { enabled: false },
  }

  if (charts.delta) {
    charts.delta.updateOptions(options, true, true)
  } else {
    charts.delta = new window.ApexCharts(document.querySelector('#chart-delta'), options)
    charts.delta.render()
  }
}

function renderThetaChart() {
  const projection = calcThetaProjection()
  const options = {
    chart: {
      type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
      animations: { enabled: true, easing: 'easeinout', speed: 400 },
    },
    series: [{ name: 'Cumulative Theta', data: projection.cumulative }],
    xaxis: {
      categories: projection.days,
      labels: {
        style: { colors: '#868c99', fontSize: '11px' },
        formatter: (v, i) => {
          if (i === 0) return 'Today'
          if (i % 7 === 0) return 'Day ' + v
          return ''
        },
      },
      tickAmount: 7,
    },
    yaxis: {
      labels: { style: { colors: '#868c99', fontSize: '11px' }, formatter: v => '$' + shortNumber(v) },
    },
    stroke: { curve: 'smooth', width: 2 },
    fill: {
      type: 'gradient',
      gradient: {
        shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05,
        stops: [0, 90, 100],
        colorStops: [
          { offset: 0, color: '#55aa71', opacity: 0.4 },
          { offset: 100, color: '#55aa71', opacity: 0.05 },
        ],
      },
    },
    colors: ['#55aa71'],
    grid: { borderColor: '#2a2e39' },
    tooltip: {
      theme: 'dark',
      x: { formatter: (v) => 'Day ' + v },
      y: { formatter: v => '+$' + formatNumber(v) + ' projected income' },
    },
    annotations: {
      xaxis: projection.expirationMarkers.map(m => ({
        x: m.day,
        borderColor: '#868c99',
        strokeDashArray: 4,
        label: {
          text: m.label,
          style: { color: '#d1d4dc', background: '#2a2e39', fontSize: '10px' },
          borderColor: '#2a2e39', orientation: 'horizontal', offsetY: -5,
        },
      })),
    },
    dataLabels: { enabled: false },
  }

  if (charts.theta) {
    charts.theta.updateOptions(options, true, true)
  } else {
    charts.theta = new window.ApexCharts(document.querySelector('#chart-theta'), options)
    charts.theta.render()
  }
}

function renderTreemapChart() {
  const groups = underlyingGroups.value.filter(g => g.maxRisk > 0)
  const data = groups.map(g => ({
    x: g.underlying + ' ($' + shortNumber(g.maxRisk) + ')',
    y: Math.round(g.maxRisk),
    fillColor: g.unrealizedPnl >= 0 ? '#55aa71' : '#fe676c',
  }))

  const options = {
    chart: {
      type: 'treemap', height: 280, background: 'transparent', toolbar: { show: false },
      animations: { enabled: true, speed: 400 },
    },
    series: [{ data }],
    plotOptions: {
      treemap: {
        distributed: true, enableShades: true, shadeIntensity: 0.3,
        colorScale: { ranges: [] },
      },
    },
    legend: { show: false },
    tooltip: {
      theme: 'dark',
      y: {
        formatter: (v, { dataPointIndex }) => {
          const g = groups[dataPointIndex]
          if (!g) return '$' + formatNumber(v)
          return '$' + formatNumber(v) + ' max risk | P&L: ' +
            (g.unrealizedPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(g.unrealizedPnl))
        },
      },
    },
    dataLabels: {
      enabled: true,
      style: { fontSize: '13px', fontWeight: 600, colors: ['#fff'] },
      formatter: (text, op) => [text.split(' ')[0], '$' + shortNumber(op.value)],
      offsetY: -2,
    },
  }

  if (charts.treemap) {
    charts.treemap.updateOptions(options, true, true)
  } else {
    charts.treemap = new window.ApexCharts(document.querySelector('#chart-treemap'), options)
    charts.treemap.render()
  }
}

function renderScenarioChart() {
  const scenarios = calcScenarios()
  const options = {
    chart: {
      type: 'area', height: 280, background: 'transparent', toolbar: { show: false },
      animations: { enabled: true, easing: 'easeinout', speed: 400 },
    },
    series: [{ name: 'Portfolio P&L Change', data: scenarios.pnl }],
    xaxis: {
      categories: scenarios.labels,
      labels: { style: { colors: '#868c99', fontSize: '11px' } },
      axisBorder: { show: false },
    },
    yaxis: {
      labels: {
        style: { colors: '#868c99', fontSize: '11px' },
        formatter: v => (v >= 0 ? '+$' : '-$') + shortNumber(Math.abs(v)),
      },
    },
    stroke: { curve: 'smooth', width: 3 },
    fill: {
      type: 'gradient',
      gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05, stops: [0, 90, 100] },
    },
    colors: ['#2962ff'],
    grid: { borderColor: '#2a2e39' },
    annotations: {
      yaxis: [{
        y: 0, borderColor: '#868c99', strokeDashArray: 3,
        label: { text: 'Break Even', style: { color: '#868c99', background: 'transparent', fontSize: '10px' } },
      }],
      xaxis: [{
        x: '0%', borderColor: '#868c99', strokeDashArray: 3,
        label: { text: 'Current', style: { color: '#d1d4dc', background: '#2a2e39', fontSize: '10px' }, borderColor: '#2a2e39' },
      }],
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => (v >= 0 ? '+$' : '-$') + formatNumber(Math.abs(v)) },
    },
    dataLabels: { enabled: false },
  }

  if (charts.scenario) {
    charts.scenario.updateOptions(options, true, true)
  } else {
    charts.scenario = new window.ApexCharts(document.querySelector('#chart-scenario'), options)
    charts.scenario.render()
  }
}

// ==================== THETA PROJECTION ====================
function calcThetaProjection() {
  const days = []
  const dailyTheta = []
  const cumulative = []
  const expirationMarkers = []
  const optionPositions = enrichedPositions.value.filter(p => p._isOption && p._dte > 0)
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
function calcScenarios() {
  const moves = [-10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10]
  const labels = moves.map(m => (m >= 0 ? '+' : '') + m + '%')
  const pnl = []
  const r = 0.045

  moves.forEach(pctMove => {
    let totalPnlChange = 0
    enrichedPositions.value.forEach(pos => {
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

// ==================== UTILITIES ====================
function onAccountChange() {
  localStorage.setItem('trade_journal_selected_account', selectedAccount.value || '')
  nextTick(() => {
    subscribeToQuotes()
    renderAllCharts()
  })
}

function toggleSort(col) {
  if (sortColumn.value === col) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = col
    sortDirection.value = 'desc'
  }
}

function formatDelta(v) {
  if (v == null || isNaN(v)) return '0.0'
  const sign = v >= 0 ? '+' : ''
  return sign + v.toFixed(1)
}

function getAccountSymbol(accountNumber) {
  const account = accounts.value.find(a => a.account_number === accountNumber)
  if (!account) return '?'
  const name = (account.account_name || '').toUpperCase()
  if (name.includes('ROTH')) return 'R'
  if (name.includes('INDIVIDUAL')) return 'I'
  if (name.includes('TRADITIONAL')) return 'T'
  return name.charAt(0) || '?'
}

function shortNumber(v) {
  v = Math.abs(v)
  if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
  if (v >= 1000) return (v / 1000).toFixed(1) + 'K'
  return v.toFixed(0)
}

// ==================== NAV ====================
const navLinks = [
  { href: '/positions', label: 'Positions' },
  { href: '/ledger', label: 'Ledger' },
  { href: '/reports', label: 'Reports' },
  { href: '/risk', label: 'Risk' },
]
</script>

<template>
  <!-- Navigation -->
  <nav class="bg-tv-panel border-b border-tv-border sticky top-0 z-50">
    <div class="flex items-center justify-between h-16 px-4">
      <div class="flex items-center gap-8">
        <span class="text-tv-blue font-semibold text-2xl">
          <i class="fas fa-chart-line mr-2"></i>OptionLedger
        </span>
        <div class="flex items-center border-l border-tv-border pl-8 gap-4">
          <a v-for="link in navLinks" :key="link.href" :href="link.href"
             class="px-4 py-2 text-lg"
             :class="link.href === '/risk' ? 'text-tv-text bg-tv-border rounded-sm' : 'text-tv-muted hover:text-tv-text'">
            {{ link.label }}
          </a>
        </div>
      </div>
      <div class="flex items-center gap-6 text-base">
        <select v-model="selectedAccount" @change="onAccountChange()"
                class="bg-tv-bg border border-tv-border text-tv-text text-base px-4 py-2 focus:outline-none focus:border-tv-blue">
          <option value="">All Accounts</option>
          <option v-for="account in accounts" :key="account.account_number"
                  :value="account.account_number">
            ({{ getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
          </option>
        </select>
        <div v-if="authEnabled && userEmail" class="flex items-center gap-3 border-l border-tv-border pl-6">
          <span class="text-tv-muted text-sm truncate max-w-[150px]" :title="userEmail">{{ userEmail }}</span>
          <button @click="Auth.signOut()" class="text-tv-muted hover:text-tv-red" title="Sign out">
            <i class="fas fa-sign-out-alt"></i>
          </button>
        </div>
        <a href="/settings" class="border-l border-tv-border pl-6 text-tv-muted hover:text-tv-text">
          <i class="fas fa-cog"></i>
        </a>
      </div>
    </div>
  </nav>

  <!-- Status Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center justify-between text-sm">
    <div class="flex items-center gap-6">
      <span class="text-tv-muted">
        <i class="fas fa-shield-halved mr-1 text-tv-blue"></i>Portfolio Risk X-Ray
      </span>
      <span v-if="enrichedPositions.length > 0" class="text-tv-muted">
        <span class="text-tv-text">{{ enrichedPositions.length }}</span> positions across
        <span class="text-tv-text">{{ underlyingGroups.length }}</span> underlyings
      </span>
    </div>
    <div class="flex items-center gap-4">
      <span class="flex items-center gap-2">
        <span class="pulse-dot" :class="liveQuotesActive ? 'bg-tv-green' : 'bg-tv-red'"></span>
        <span class="text-tv-muted">{{ liveQuotesActive ? 'Live' : 'Offline' }}</span>
      </span>
      <span v-if="greeksSource" class="text-tv-muted">
        Greeks: <span class="text-tv-text">{{ greeksSource }}</span>
      </span>
    </div>
  </div>

  <!-- Loading State -->
  <div v-if="isLoading" class="text-center py-24">
    <div class="spinner mx-auto mb-4" style="width: 48px; height: 48px; border-width: 4px;"></div>
    <p class="text-tv-muted text-lg">Calculating portfolio risk...</p>
  </div>

  <!-- Empty State -->
  <div v-else-if="allPositions.length === 0" class="text-center py-24">
    <i class="fas fa-shield-halved text-6xl text-tv-border mb-6"></i>
    <p class="text-tv-muted text-xl mb-2">No open positions found</p>
    <p class="text-tv-muted">Sync your data from the <a href="/positions" class="text-tv-blue hover:underline">Positions</a> page first.</p>
  </div>

  <!-- Main Content -->
  <main v-else class="p-4">

    <!-- Summary Cards -->
    <div class="grid grid-cols-6 gap-3 mb-4">
      <!-- Net Liquidating Value -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-blue">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Net Liquidating Value</div>
        <div class="text-2xl font-bold text-tv-text">
          ${{ formatNumber(currentBalance?.net_liquidating_value || 0) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          Cash: ${{ formatNumber(currentBalance?.cash_balance || 0) }}
        </div>
      </div>

      <!-- Daily Theta -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="portfolioTotals.netTheta >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#920;</span> Daily Theta
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
          {{ portfolioTotals.netTheta >= 0 ? '+' : '' }}${{ formatNumber(Math.abs(portfolioTotals.netTheta)) }}<span class="text-sm font-normal text-tv-muted">/day</span>
        </div>
        <div class="text-xs mt-1" :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green/70' : 'text-tv-red/70'">
          ${{ formatNumber(Math.abs(portfolioTotals.netTheta * 30)) }}/month projected
        </div>
      </div>

      <!-- Net Delta -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="portfolioTotals.netDelta >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#916;</span> Net Delta
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
          {{ formatDelta(portfolioTotals.netDelta) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          ${{ formatNumber(Math.abs(portfolioTotals.deltaDollars)) }} delta-adjusted
        </div>
      </div>

      <!-- Net Gamma -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-amber-500">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#915;</span> Net Gamma
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netGamma >= 0 ? 'text-amber-400' : 'text-amber-500'">
          {{ formatDelta(portfolioTotals.netGamma) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          Delta change per $1 move
        </div>
      </div>

      <!-- Net Vega -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-purple-500">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">
          <span class="greek-symbol">&#957;</span> Net Vega
        </div>
        <div class="text-2xl font-bold" :class="portfolioTotals.netVega >= 0 ? 'text-purple-400' : 'text-purple-500'">
          {{ portfolioTotals.netVega >= 0 ? '+' : '' }}${{ formatNumber(Math.abs(portfolioTotals.netVega)) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          P&amp;L per 1% IV change
        </div>
      </div>

      <!-- Buying Power Utilization -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="bpUtilization < 50 ? 'border-l-tv-green' : bpUtilization < 75 ? 'border-l-amber-500' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">BP Utilization</div>
        <div class="text-2xl font-bold"
             :class="bpUtilization < 50 ? 'text-tv-green' : bpUtilization < 75 ? 'text-amber-400' : 'text-tv-red'">
          {{ bpUtilization.toFixed(1) }}%
        </div>
        <div class="text-xs text-tv-muted mt-1">
          ${{ formatNumber(Math.abs((currentBalance?.net_liquidating_value || 0) - (currentBalance?.derivative_buying_power || 0))) }}
          / ${{ formatNumber(currentBalance?.net_liquidating_value || 0) }}
        </div>
      </div>
    </div>

    <!-- Charts Row 1 -->
    <div class="grid grid-cols-2 gap-3 mb-3">
      <!-- Delta Exposure -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-arrows-left-right mr-1 text-tv-blue"></i>Delta Exposure by Underlying
          <span class="text-xs font-normal ml-2">(delta dollars)</span>
        </div>
        <div id="chart-delta" style="min-height: 280px;"></div>
      </div>

      <!-- Theta Income Projection -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-chart-area mr-1 text-tv-green"></i>Theta Income Projection
          <span class="text-xs font-normal ml-2">(cumulative over 45 days)</span>
        </div>
        <div id="chart-theta" style="min-height: 280px;"></div>
      </div>
    </div>

    <!-- Charts Row 2 -->
    <div class="grid grid-cols-2 gap-3 mb-3">
      <!-- Portfolio Concentration Treemap -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-th-large mr-1 text-cyan-400"></i>Portfolio Concentration
          <span class="text-xs font-normal ml-2">(sized by max risk, colored by P&amp;L)</span>
        </div>
        <div id="chart-treemap" style="min-height: 280px;"></div>
      </div>

      <!-- Market Scenario Analysis -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-sm text-tv-muted uppercase tracking-wider mb-3">
          <i class="fas fa-flask mr-1 text-amber-400"></i>Market Scenario Analysis
          <span class="text-xs font-normal ml-2">(P&amp;L at correlated market moves)</span>
        </div>
        <div id="chart-scenario" style="min-height: 280px;"></div>
      </div>
    </div>

    <!-- Risk Detail Table -->
    <div class="bg-tv-panel border border-tv-border">
      <div class="px-4 py-3 border-b border-tv-border flex items-center justify-between">
        <span class="text-sm text-tv-muted uppercase tracking-wider">
          <i class="fas fa-table mr-1 text-tv-blue"></i>Per-Underlying Risk Breakdown
        </span>
        <span class="text-xs text-tv-muted">
          Click column headers to sort
        </span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-tv-muted text-xs uppercase tracking-wider border-b border-tv-border">
              <th class="text-left px-4 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('underlying')">
                Underlying <span v-if="sortColumn === 'underlying'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('positionCount')">
                Pos <span v-if="sortColumn === 'positionCount'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('underlyingPrice')">
                Price <span v-if="sortColumn === 'underlyingPrice'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netDelta')">
                Delta <span v-if="sortColumn === 'netDelta'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('deltaDollars')">
                Delta $ <span v-if="sortColumn === 'deltaDollars'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netGamma')">
                Gamma <span v-if="sortColumn === 'netGamma'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netTheta')">
                Theta <span v-if="sortColumn === 'netTheta'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('netVega')">
                Vega <span v-if="sortColumn === 'netVega'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('maxRisk')">
                Max Risk <span v-if="sortColumn === 'maxRisk'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3 cursor-pointer hover:text-tv-text" @click="toggleSort('unrealizedPnl')">
                Unreal P&amp;L <span v-if="sortColumn === 'unrealizedPnl'">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
              </th>
              <th class="text-right px-3 py-3">% Port</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in sortedGroups" :key="group.underlying"
                class="border-b border-tv-border/50 hover:bg-tv-border/20 transition-colors">
              <td class="px-4 py-3 font-semibold text-tv-text">{{ group.underlying }}</td>
              <td class="text-right px-3 py-3 text-tv-muted">{{ group.positionCount }}</td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(group.underlyingPrice) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ formatDelta(group.netDelta) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.deltaDollars >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.deltaDollars >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.deltaDollars)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-amber-400">
                {{ formatDelta(group.netGamma) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.netTheta >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.netTheta)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-purple-400">
                {{ (group.netVega >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.netVega)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(group.maxRisk) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="group.unrealizedPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (group.unrealizedPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(group.unrealizedPnl)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-muted">
                {{ portfolioTotals.totalMaxRisk > 0 ? (group.maxRisk / portfolioTotals.totalMaxRisk * 100).toFixed(1) + '%' : '-' }}
              </td>
            </tr>
            <!-- Totals Row -->
            <tr class="border-t-2 border-tv-border bg-tv-bg/50 font-semibold">
              <td class="px-4 py-3 text-tv-text">PORTFOLIO</td>
              <td class="text-right px-3 py-3 text-tv-text">{{ portfolioTotals.positionCount }}</td>
              <td class="text-right px-3 py-3"></td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.netDelta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ formatDelta(portfolioTotals.netDelta) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.deltaDollars >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.deltaDollars >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.deltaDollars)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-amber-400">
                {{ formatDelta(portfolioTotals.netGamma) }}
              </td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.netTheta >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.netTheta >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.netTheta)) }}
              </td>
              <td class="text-right px-3 py-3 font-mono text-purple-400">
                {{ (portfolioTotals.netVega >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.netVega)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">${{ formatNumber(portfolioTotals.totalMaxRisk) }}</td>
              <td class="text-right px-3 py-3 font-mono"
                  :class="portfolioTotals.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                {{ (portfolioTotals.totalPnl >= 0 ? '+$' : '-$') + formatNumber(Math.abs(portfolioTotals.totalPnl)) }}
              </td>
              <td class="text-right px-3 py-3 text-tv-text">100%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Footer Note -->
    <div class="text-center text-xs text-tv-muted mt-4 pb-4">
      Greeks calculated via Black-Scholes model using underlying IV. Values are estimates and update with live quotes.
      Risk-free rate: 4.5%. Options multiplier: 100.
    </div>
  </main>
</template>

<style>
.spinner {
  border: 2px solid #2a2e39;
  border-top: 2px solid #2962ff;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  animation: spin 1s linear infinite;
  display: inline-block;
}
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

.metric-card { transition: border-color 0.2s ease; }
.metric-card:hover { border-color: #363a45; }

.greek-symbol {
  font-family: 'Times New Roman', Georgia, serif;
  font-style: italic;
  font-weight: bold;
}

.apexcharts-tooltip { background: #1e222d !important; border: 1px solid #2a2e39 !important; color: #d1d4dc !important; }
.apexcharts-tooltip-title { background: #131722 !important; border-bottom: 1px solid #2a2e39 !important; color: #d1d4dc !important; }
.apexcharts-xaxistooltip, .apexcharts-yaxistooltip { background: #1e222d !important; border: 1px solid #2a2e39 !important; color: #d1d4dc !important; }
.apexcharts-xaxistooltip:after, .apexcharts-xaxistooltip:before { border-bottom-color: #2a2e39 !important; }

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>
