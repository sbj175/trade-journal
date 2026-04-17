/**
 * Data fetching, WebSocket connection, and position state management.
 */
import { ref, computed, nextTick } from 'vue'
import { enrichPosition, calcCapitalAtRisk, getUnderlying } from './riskCalculations'

export function useRiskData(Auth) {
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

  // Internal (non-reactive)
  let ws = null
  let onQuoteUpdate = null
  const _enrichCache = new Map()

  function cachedEnrichPosition(pos, quotesMap) {
    const underlying = pos.underlying_symbol || pos.symbol?.slice(0, 6).trim() || ''
    const q = quotesMap[underlying] || {}
    const price = q.price || q.mark || q.last || 0
    const iv = q.iv || q.impliedVolatility || 0
    const key = `${pos.lot_id || pos.symbol}:${price}:${iv}`
    if (_enrichCache.has(key)) return _enrichCache.get(key)
    const result = enrichPosition(pos, quotesMap)
    _enrichCache.set(key, result)
    if (_enrichCache.size > 5000) {
      const firstKey = _enrichCache.keys().next().value
      _enrichCache.delete(firstKey)
    }
    return result
  }

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
    return allPositions.value.map(p => cachedEnrichPosition(p, quotes.value)).filter(Boolean)
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
    }
    isLoading.value = false
  }

  // ==================== WEBSOCKET ====================
  function setOnQuoteUpdate(callback) {
    onQuoteUpdate = callback
  }

  async function connectWebSocket() {
    const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes')
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
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
          if (onQuoteUpdate) onQuoteUpdate()
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

  function disconnectWebSocket() {
    if (ws) {
      ws.onclose = null // prevent reconnect
      ws.close()
      ws = null
    }
  }

  // ==================== SORT & ACCOUNT ====================
  function toggleSort(col) {
    if (sortColumn.value === col) {
      sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortColumn.value = col
      sortDirection.value = 'desc'
    }
  }

  function onAccountChange(renderCharts) {
    localStorage.setItem('trade_journal_selected_account', selectedAccount.value || '')
    nextTick(() => {
      subscribeToQuotes()
      if (renderCharts) renderCharts()
    })
  }

  return {
    // State
    rawPositions, accountBalances, quotes, accounts, selectedAccount,
    isLoading, error, liveQuotesActive, greeksSource, sortColumn, sortDirection,
    // Computed
    allPositions, enrichedPositions, underlyingGroups, sortedGroups,
    portfolioTotals, currentBalance, bpUtilization,
    // Methods
    fetchData, connectWebSocket, subscribeToQuotes, disconnectWebSocket,
    setOnQuoteUpdate, toggleSort, onAccountChange,
  }
}
