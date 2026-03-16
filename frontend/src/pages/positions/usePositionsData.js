/**
 * Data fetching, WebSocket, quotes, filtering, sorting, and P&L calculations.
 * Composable that manages the core reactive state for the Positions page.
 */
import { ref, computed } from 'vue'
import { buildOptionStratUrl, getGroupStrategyLabel } from './usePositionsDisplay'
import { getRollAnalysis } from './usePositionsAnalysis'

export function usePositionsData(Auth) {
  // --- State ---
  const allChains = ref([])
  const allItems = ref([])
  const filteredItems = ref([])
  const accounts = ref([])
  const underlyingQuotes = ref({})
  const quoteUpdateCounter = ref(0)
  const selectedAccount = ref('')
  const selectedUnderlying = ref('')
  const isLoading = ref(false)
  const isSyncing = ref(false)
  const error = ref(null)
  const liveQuotesActive = ref(false)
  const lastQuoteUpdate = ref(null)
  const syncSummary = ref(null)
  const strategyTargets = ref({})
  const rollAlertSettings = ref({ enabled: true, profitTarget: true, lossLimit: true, lateStage: true, deltaSaturation: true, lowRewardToRisk: true })
  const rollAnalysisMode = ref(localStorage.getItem('rollAnalysisMode') || 'chain')

  // Sorting state
  const sortColumn = ref('underlying')
  const sortDirection = ref('asc')

  // Expanded rows tracking
  const expandedRows = ref(new Set())

  // Non-reactive
  let ws = null
  let wsReconnectTimer = null
  let wsReconnectAttempts = 0
  const WS_MAX_RECONNECT_ATTEMPTS = 5

  // --- Toggle helpers ---
  function toggleRollAnalysisMode() {
    rollAnalysisMode.value = rollAnalysisMode.value === 'spread' ? 'chain' : 'spread'
    localStorage.setItem('rollAnalysisMode', rollAnalysisMode.value)
  }

  function toggleExpanded(groupKey) {
    const s = new Set(expandedRows.value)
    if (s.has(groupKey)) s.delete(groupKey)
    else s.add(groupKey)
    expandedRows.value = s
  }

  // --- Data fetching ---
  async function fetchAccounts() {
    try {
      const response = await Auth.authFetch('/api/accounts')
      const data = await response.json()
      accounts.value = (data.accounts || []).sort((a, b) => {
        const getOrder = (name) => {
          const n = (name || '').toUpperCase()
          if (n.includes('ROTH')) return 1
          if (n.includes('INDIVIDUAL')) return 2
          if (n.includes('TRADITIONAL')) return 3
          return 4
        }
        return getOrder(a.account_name) - getOrder(b.account_name)
      })
    } catch (err) { console.error('Failed to load accounts:', err) }
  }

  async function fetchPositions(includeSync = false, { migrateCommentKeysFn, loadCommentsFn } = {}) {
    // Only show full-screen spinner on initial load (no data yet)
    const hasData = allItems.value.length > 0
    if (!hasData) isLoading.value = true
    if (includeSync) isSyncing.value = true
    error.value = null
    try {
      if (includeSync) {
        syncSummary.value = null
        const syncResp = await Auth.authFetch('/api/sync', { method: 'POST' })
        if (syncResp.ok) {
          const syncData = await syncResp.json()
          const n = syncData.new_transactions || 0
          const syms = syncData.symbols || []
          if (n > 0) {
            syncSummary.value = `Imported ${n} transaction${n === 1 ? '' : 's'} on ${syms.join(', ')}`
          } else {
            syncSummary.value = 'No new transactions'
          }
        }
      }

      const response = await Auth.authFetch('/api/open-chains')
      const data = await response.json()

      allChains.value = []
      allItems.value = []

      if (typeof data === 'object' && !Array.isArray(data)) {
        Object.entries(data).forEach(([accountNumber, accountData]) => {
          const chains = accountData.chains || []
          chains.forEach(chain => {
            // Skip equity-only groups — those belong on the Equities page
            if ((chain.open_legs || []).length === 0 && (chain.equity_legs || []).length > 0) return
            chain.account_number = accountNumber
            allChains.value.push(chain)
            allItems.value.push({
              ...chain,
              groupKey: `${accountNumber}|${chain.chain_id}`,
              displayKey: chain.underlying,
              accountNumber: accountNumber,
              positions: chain.open_legs || [],
              equityLegs: chain.equity_legs || [],
              equitySummary: chain.equity_summary || null,
            })
          })
        })
      }
      if (migrateCommentKeysFn) migrateCommentKeysFn()
      if (loadCommentsFn) await loadCommentsFn()
      applyFilters()
    } catch (err) {
      console.error('Failed to load positions:', err)
      error.value = 'Failed to load positions'
    } finally {
      isLoading.value = false
      isSyncing.value = false
      // Re-subscribe WebSocket with any new symbols from sync
      if (includeSync) requestLiveQuotes()
    }
  }

  // --- Quotes ---
  async function loadCachedQuotes() {
    try {
      const symbols = collectSymbols()
      if (symbols.length === 0) return

      const response = await Auth.authFetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`)
      if (response.ok) {
        const quotes = await response.json()
        const updated = { ...underlyingQuotes.value }
        for (const [symbol, quoteData] of Object.entries(quotes)) {
          if (quoteData && typeof quoteData === 'object') {
            updated[symbol] = { ...updated[symbol], ...quoteData }
          }
        }
        underlyingQuotes.value = updated
        lastQuoteUpdate.value = new Date().toLocaleTimeString()
        quoteUpdateCounter.value++
      }
    } catch (err) { console.error('Error loading cached quotes:', err) }
  }

  function collectSymbols() {
    const symbolSet = new Set()
    filteredItems.value.forEach(item => {
      if (item.underlying) symbolSet.add(item.underlying)
      ;(item.positions || []).forEach(leg => {
        if (leg.symbol) symbolSet.add(leg.symbol)
      })
    })
    return Array.from(symbolSet).filter(s => s && s !== 'Unknown')
  }

  // --- WebSocket ---
  async function initializeWebSocket() {
    try {
      const wsUrl = await Auth.getAuthenticatedWsUrl('/ws/quotes')
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        liveQuotesActive.value = true
        wsReconnectAttempts = 0
        requestLiveQuotes()
      }

      ws.onmessage = (event) => {
        const message = JSON.parse(event.data)
        if (message.type === 'quotes' && message.data) {
          let quotesUpdated = false
          const updated = { ...underlyingQuotes.value }
          for (const [symbol, quoteData] of Object.entries(message.data)) {
            if (quoteData && typeof quoteData === 'object') {
              updated[symbol] = { ...updated[symbol], ...quoteData }
              quotesUpdated = true
            }
          }
          if (quotesUpdated) {
            underlyingQuotes.value = updated
          }
          quoteUpdateCounter.value++
          lastQuoteUpdate.value = new Date().toLocaleTimeString()
        }
      }

      ws.onclose = () => {
        liveQuotesActive.value = false
        if (wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
          wsReconnectAttempts++
          const delay = Math.min(5000 * Math.pow(2, wsReconnectAttempts - 1), 60000)
          wsReconnectTimer = setTimeout(() => initializeWebSocket(), delay)
        }
      }
    } catch (err) { console.error('WebSocket error:', err) }
  }

  function requestLiveQuotes() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    const symbols = collectSymbols()
    if (symbols.length > 0) {
      ws.send(JSON.stringify({ subscribe: symbols }))
    }
  }

  function cleanupWebSocket() {
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer)
      wsReconnectTimer = null
    }
  }

  // --- Filters ---
  function applyFilters() {
    filteredItems.value = allItems.value.filter(item => {
      if (selectedAccount.value && item.accountNumber !== selectedAccount.value) return false
      if (selectedUnderlying.value && item.underlying !== selectedUnderlying.value) return false
      return true
    })
  }

  function filterPositions() { applyFilters() }

  function saveFilterPreferences() {
    localStorage.setItem('trade_journal_selected_account', selectedAccount.value || '')
    localStorage.setItem('trade_journal_selected_underlying', selectedUnderlying.value || '')
  }

  function loadFilterPreferences() {
    const savedAccount = localStorage.getItem('trade_journal_selected_account')
    if (savedAccount !== null) selectedAccount.value = savedAccount

    const savedUnderlying = localStorage.getItem('trade_journal_selected_underlying')
    if (savedUnderlying) selectedUnderlying.value = savedUnderlying

    const savedSort = localStorage.getItem('positions_sort')
    if (savedSort) {
      try {
        const parsed = JSON.parse(savedSort)
        sortColumn.value = parsed.column || 'underlying'
        sortDirection.value = parsed.direction || 'asc'
      } catch (e) { /* Default sort */ }
    }
  }

  async function onAccountChange() {
    applyFilters()
    saveFilterPreferences()
    await loadCachedQuotes()
    requestLiveQuotes()
  }

  function onSymbolFilterCommit() {
    filterPositions()
    requestLiveQuotes()
    saveFilterPreferences()
  }

  // --- Sort ---
  function sortPositions(column) {
    if (sortColumn.value === column) {
      sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortColumn.value = column
      if (['pnl', 'total_pnl', 'realized_pnl', 'open_pnl', 'pnl_percent', 'net_liq', 'price', 'ivr'].includes(column)) {
        sortDirection.value = 'desc'
      } else {
        sortDirection.value = 'asc'
      }
    }
    localStorage.setItem('positions_sort', JSON.stringify({
      column: sortColumn.value,
      direction: sortDirection.value
    }))
  }

  // --- P&L Calculations ---
  function getGroupCostBasis(group) {
    if (group._isSubtotal) return group._subtotalCostBasis
    const optionTotal = (group.positions || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
    const equityTotal = (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
    return optionTotal + equityTotal
  }

  function calculateLegMarketValue(leg) {
    quoteUpdateCounter.value
    const optionSymbol = (leg.symbol || '').trim()
    const optionQuote = underlyingQuotes.value[optionSymbol]
    if (optionQuote && optionQuote.mark !== undefined) {
      const absValue = optionQuote.mark * leg.quantity * 100
      return leg.quantity_direction === 'Short' ? -absValue : absValue
    }
    const absValue = (leg.opening_price || 0) * leg.quantity * 100
    return leg.quantity_direction === 'Short' ? -absValue : absValue
  }

  function calculateLegPnL(leg) {
    const marketValue = calculateLegMarketValue(leg)
    const costBasis = leg.cost_basis || 0
    const absMV = Math.abs(marketValue)
    const absCB = Math.abs(costBasis)
    if (leg.quantity_direction === 'Short') {
      return absCB - absMV
    } else {
      return absMV - absCB
    }
  }

  function hasEquity(group) {
    return (group.equityLegs || []).length > 0
  }

  function calculateEquityMarketValue(group) {
    const eqLegs = group.equityLegs || []
    if (eqLegs.length === 0) return 0
    const quote = underlyingQuotes.value[group.underlying]
    if (!quote || !quote.price) return 0
    let total = 0
    eqLegs.forEach(leg => {
      const signed = leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity
      total += quote.price * signed
    })
    return total
  }

  function getGroupOpenPnL(group) {
    quoteUpdateCounter.value
    if (group._isSubtotal) return group._subtotalOpenPnL
    const optionPnL = (group.positions || []).reduce((sum, leg) => sum + calculateLegPnL(leg), 0)
    const eqLegs = group.equityLegs || []
    if (eqLegs.length === 0) return optionPnL
    const eqCost = eqLegs.reduce((s, l) => s + (l.cost_basis || 0), 0)
    const eqMV = calculateEquityMarketValue(group)
    return optionPnL + eqMV + eqCost
  }

  function getGroupRealizedPnL(group) {
    if (group._isSubtotal) return group._subtotalRealizedPnL
    return group.realized_pnl || 0
  }

  function getGroupTotalPnL(group) {
    if (group._isSubtotal) return group._subtotalTotalPnL
    return getGroupRealizedPnL(group) + getGroupOpenPnL(group)
  }

  function getGroupNetLiqWithLiveQuotes(group) {
    quoteUpdateCounter.value
    if (group._isSubtotal) return group._subtotalNetLiq
    const optionMV = (group.positions || []).reduce((sum, leg) => sum + calculateLegMarketValue(leg), 0)
    const equityMV = calculateEquityMarketValue(group)
    return optionMV + equityMV
  }

  function getGroupPnLPercent(group) {
    const costBasis = getGroupCostBasis(group)
    const openPnL = getGroupOpenPnL(group)
    if (costBasis === 0) return null
    return ((openPnL / Math.abs(costBasis)) * 100).toFixed(1)
  }

  function getGroupDaysOpen(group) {
    if (group._isSubtotal) return null
    const openDate = group.opening_date
    if (!openDate) return null
    const d = new Date(openDate + 'T00:00:00')
    const now = new Date()
    const days = Math.floor((now - d) / (1000 * 60 * 60 * 24))
    return days > 0 ? days : 0
  }

  function getMinDTE(group) {
    if (group._isSubtotal) return null
    const legs = group.positions || []
    let minDTE = null
    for (const leg of legs) {
      if (leg.expiration) {
        const dateStr = leg.expiration.substring(0, 10)
        const expDate = new Date(dateStr + 'T00:00:00')
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        const dte = Math.ceil((expDate - today) / (1000 * 60 * 60 * 24))
        if (minDTE === null || dte < minDTE) minDTE = dte
      }
    }
    return minDTE
  }

  function getUnderlyingQuote(underlying) {
    return underlyingQuotes.value[underlying] || null
  }

  function getUnderlyingIVR(underlying) {
    const quote = getUnderlyingQuote(underlying)
    if (!quote || !quote.ivr) return null
    return Math.round(quote.ivr * 100)
  }

  function getOptionStratUrl(group) {
    if (!group.strategy_type || !group.underlying) return null
    const optionLegs = (group.positions || []).filter(l =>
      l.instrument_type && l.instrument_type.includes('OPTION'))
    if (optionLegs.length !== 2) return null
    const legs = optionLegs.map(l => ({
      expiration: l.expiration,
      option_type: l.option_type,
      strike: l.strike,
      isShort: l.quantity_direction === 'Short',
    }))
    return buildOptionStratUrl(group.strategy_type, group.underlying, legs)
  }

  // --- Subtotals ---
  function insertSubtotals(sorted) {
    const result = []
    let currentKey = null
    let currentGroup = []

    const flushGroup = () => {
      if (currentGroup.length <= 1) {
        result.push(...currentGroup)
        return
      }
      const underlying = currentGroup[0].underlying
      const acct = currentGroup[0].accountNumber
      const subtotal = {
        _isSubtotal: true,
        groupKey: `subtotal_${acct}_${underlying}`,
        displayKey: underlying,
        underlying: underlying,
        accountNumber: acct,
        _subtotalCostBasis: 0,
        _subtotalNetLiq: 0,
        _subtotalOpenPnL: 0,
        _subtotalRealizedPnL: 0,
        _subtotalTotalPnL: 0,
        _childCount: currentGroup.length,
      }
      currentGroup.forEach(item => {
        subtotal._subtotalCostBasis += getGroupCostBasis(item)
        subtotal._subtotalNetLiq += getGroupNetLiqWithLiveQuotes(item)
        subtotal._subtotalOpenPnL += getGroupOpenPnL(item)
        subtotal._subtotalRealizedPnL += getGroupRealizedPnL(item)
        subtotal._subtotalTotalPnL += getGroupTotalPnL(item)
      })
      result.push(subtotal)
      result.push(...currentGroup)
    }

    for (const item of sorted) {
      const key = `${item.accountNumber}|${item.underlying}`
      if (key !== currentKey) {
        if (currentGroup.length > 0) flushGroup()
        currentKey = key
        currentGroup = [item]
      } else {
        currentGroup.push(item)
      }
    }
    if (currentGroup.length > 0) flushGroup()
    return result
  }

  // --- Strategy Targets ---
  async function loadStrategyTargets() {
    try {
      const response = await Auth.authFetch('/api/settings/targets')
      if (response.ok) {
        const data = await response.json()
        const list = Array.isArray(data) ? data : (data.targets || [])
        const mapped = {}
        list.forEach(t => { if (t.strategy_name) mapped[t.strategy_name] = t })
        strategyTargets.value = mapped
      }
    } catch (err) { console.error('Failed to load strategy targets:', err) }
  }

  function loadRollAlertSettings() {
    try {
      const saved = localStorage.getItem('rollAlertSettings')
      if (saved) rollAlertSettings.value = { ...rollAlertSettings.value, ...JSON.parse(saved) }
    } catch (e) { /* use defaults */ }
  }

  // --- Computed ---
  const groupedPositions = computed(() => {
    try {
      if (isLoading.value || !filteredItems.value || filteredItems.value.length === 0) return []

      // Touch counter to ensure recompute on quote changes
      quoteUpdateCounter.value

      const sorted = [...filteredItems.value].sort((a, b) => {
        let aVal, bVal

        switch (sortColumn.value) {
          case 'underlying':
            aVal = a.underlying.toLowerCase()
            bVal = b.underlying.toLowerCase()
            break
          case 'ivr':
            aVal = getUnderlyingIVR(a.underlying) ?? -1
            bVal = getUnderlyingIVR(b.underlying) ?? -1
            break
          case 'price': {
            const aQuote = underlyingQuotes.value[a.underlying]
            const bQuote = underlyingQuotes.value[b.underlying]
            aVal = aQuote?.price || 0
            bVal = bQuote?.price || 0
            break
          }
          case 'cost_basis':
            aVal = getGroupCostBasis(a)
            bVal = getGroupCostBasis(b)
            break
          case 'net_liq':
            aVal = getGroupNetLiqWithLiveQuotes(a)
            bVal = getGroupNetLiqWithLiveQuotes(b)
            break
          case 'pnl':
          case 'total_pnl':
            aVal = getGroupTotalPnL(a)
            bVal = getGroupTotalPnL(b)
            break
          case 'realized_pnl':
            aVal = a.realized_pnl || 0
            bVal = b.realized_pnl || 0
            break
          case 'open_pnl':
            aVal = getGroupOpenPnL(a)
            bVal = getGroupOpenPnL(b)
            break
          case 'pnl_percent':
            aVal = parseFloat(getGroupPnLPercent(a)) || 0
            bVal = parseFloat(getGroupPnLPercent(b)) || 0
            break
          case 'days':
            aVal = getGroupDaysOpen(a) || 0
            bVal = getGroupDaysOpen(b) || 0
            break
          case 'dte':
            aVal = getMinDTE(a) ?? 9999
            bVal = getMinDTE(b) ?? 9999
            break
          case 'strategy':
            aVal = getGroupStrategyLabel(a).toLowerCase()
            bVal = getGroupStrategyLabel(b).toLowerCase()
            break
          default:
            aVal = a.underlying.toLowerCase()
            bVal = b.underlying.toLowerCase()
        }

        if (aVal < bVal) return sortDirection.value === 'asc' ? -1 : 1
        if (aVal > bVal) return sortDirection.value === 'asc' ? 1 : -1
        return 0
      })

      // Attach roll analysis to each group for reactive badge display
      sorted.forEach(group => {
        group.rollAnalysis = getRollAnalysis(group, {
          underlyingQuotes: underlyingQuotes.value,
          rollAlertSettings: rollAlertSettings.value,
          rollAnalysisMode: rollAnalysisMode.value,
          strategyTargets: strategyTargets.value,
          getGroupOpenPnLFn: getGroupOpenPnL,
          getMinDTEFn: getMinDTE,
        })
      })

      // Insert subtotal rows when sorted by underlying
      if (sortColumn.value === 'underlying') {
        return insertSubtotals(sorted)
      }
      return sorted
    } catch (err) {
      console.error('Error in groupedPositions:', err)
      return []
    }
  })

  const underlyings = computed(() => {
    return [...new Set(filteredItems.value.map(item => item.underlying).filter(s => s && s !== 'Unknown'))]
  })

  return {
    // State
    allChains, allItems, filteredItems, accounts,
    underlyingQuotes, quoteUpdateCounter,
    selectedAccount, selectedUnderlying,
    isLoading, isSyncing, error, liveQuotesActive, lastQuoteUpdate, syncSummary,
    strategyTargets, rollAlertSettings, rollAnalysisMode,
    sortColumn, sortDirection, expandedRows,

    // Computed
    groupedPositions, underlyings,

    // Toggle helpers
    toggleRollAnalysisMode, toggleExpanded,

    // Data fetching
    fetchAccounts, fetchPositions, loadCachedQuotes,

    // WebSocket
    initializeWebSocket, requestLiveQuotes, cleanupWebSocket,

    // Filters
    applyFilters, filterPositions, saveFilterPreferences, loadFilterPreferences,
    onAccountChange, onSymbolFilterCommit,

    // Sort
    sortPositions,

    // P&L
    getGroupCostBasis, getGroupOpenPnL, getGroupRealizedPnL, getGroupTotalPnL,
    getGroupNetLiqWithLiveQuotes, getGroupPnLPercent, getGroupDaysOpen, getMinDTE,
    calculateLegMarketValue, calculateLegPnL,
    hasEquity, calculateEquityMarketValue,
    getUnderlyingQuote, getUnderlyingIVR, getOptionStratUrl,

    // Strategy targets & settings
    loadStrategyTargets, loadRollAlertSettings,
  }
}
