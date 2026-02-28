<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber } from '@/lib/formatters'

const Auth = useAuth()

// --- State ---
const allChains = ref([])
const allItems = ref([])
const filteredItems = ref([])
const accounts = ref([])
const accountBalances = ref({})
const underlyingQuotes = ref({})
const quoteUpdateCounter = ref(0)
const positionComments = ref({})
const selectedAccount = ref('')
const selectedUnderlying = ref('')
const isLoading = ref(false)
const error = ref(null)
const liveQuotesActive = ref(false)
const lastQuoteUpdate = ref(null)
const reconciliation = ref(null)
const strategyTargets = ref({})
const rollAlertSettings = ref({ enabled: true, profitTarget: true, lossLimit: true, lateStage: true, deltaSaturation: true, lowRewardToRisk: true })
const privacyMode = ref('off')

// Tag state
const availableTags = ref([])
const tagPopoverGroup = ref(null)
const tagSearch = ref('')

// Sorting state
const sortColumn = ref('underlying')
const sortDirection = ref('asc')

// Nav auth
const authEnabled = ref(false)
const userEmail = ref('')

// Expanded rows tracking
const expandedRows = ref(new Set())

function toggleExpanded(groupKey) {
  const s = new Set(expandedRows.value)
  if (s.has(groupKey)) s.delete(groupKey)
  else s.add(groupKey)
  expandedRows.value = s
}

// Non-reactive
let ws = null
let wsReconnectTimer = null
const _noteSaveTimers = {}

// Nav links
const navLinks = [
  { href: '/positions', label: 'Positions' },
  { href: '/ledger', label: 'Ledger' },
  { href: '/reports', label: 'Reports' },
  { href: '/risk', label: 'Risk' },
]

// --- OptionStrat URL builder ---
function buildOptionStratUrl(strategyType, underlying, legs) {
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

// --- Computed ---
const currentAccountBalance = computed(() => {
  if (!selectedAccount.value || selectedAccount.value === '') {
    const values = Object.values(accountBalances.value)
    if (values.length === 0) return null
    return values.reduce((acc, balance) => ({
      cash_balance: (acc.cash_balance || 0) + (balance.cash_balance || 0),
      derivative_buying_power: (acc.derivative_buying_power || 0) + (balance.derivative_buying_power || 0),
      equity_buying_power: (acc.equity_buying_power || 0) + (balance.equity_buying_power || 0),
      net_liquidating_value: (acc.net_liquidating_value || 0) + (balance.net_liquidating_value || 0)
    }), { cash_balance: 0, derivative_buying_power: 0, equity_buying_power: 0, net_liquidating_value: 0 })
  }
  return accountBalances.value[selectedAccount.value] || null
})

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
      group.rollAnalysis = getRollAnalysis(group)
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

const filteredTagSuggestions = computed(() => {
  const search = (tagSearch.value || '').toLowerCase()
  const group = allItems.value.find(g => g.group_id === tagPopoverGroup.value)
  const appliedIds = (group?.tags || []).map(t => t.id)
  return availableTags.value
    .filter(t => !appliedIds.includes(t.id))
    .filter(t => !search || t.name.toLowerCase().includes(search))
})

// --- Methods ---

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

async function fetchPositions(includeSync = false) {
  isLoading.value = true
  error.value = null
  try {
    if (includeSync) {
      const syncResp = await Auth.authFetch('/api/sync', { method: 'POST' })
      if (syncResp.ok) {
        const syncData = await syncResp.json()
        if (syncData.reconciliation) {
          reconciliation.value = syncData.reconciliation
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
    migrateCommentKeys()
    await loadComments()
    applyFilters()
  } catch (err) {
    console.error('Failed to load positions:', err)
    error.value = 'Failed to load positions'
  } finally {
    isLoading.value = false
  }
}

// --- Tag Methods ---

async function loadAvailableTags() {
  try {
    const resp = await Auth.authFetch('/api/tags')
    availableTags.value = await resp.json()
  } catch (e) { console.error('Error loading tags:', e) }
}

function openTagPopover(groupId, event) {
  if (event) event.stopPropagation()
  tagPopoverGroup.value = tagPopoverGroup.value === groupId ? null : groupId
  tagSearch.value = ''
  if (tagPopoverGroup.value) {
    setTimeout(() => {
      const input = document.getElementById('tag-input-' + groupId)
      if (input) input.focus()
    }, 0)
  }
}

function closeTagPopover() {
  tagPopoverGroup.value = null
  tagSearch.value = ''
}

async function addTagToGroup(group, nameOrTag) {
  const payload = typeof nameOrTag === 'string'
    ? { name: nameOrTag.trim() }
    : { tag_id: nameOrTag.id }
  if (payload.name === '' && !payload.tag_id) return
  try {
    const resp = await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const tag = await resp.json()
    if (!group.tags) group.tags = []
    if (!group.tags.find(t => t.id === tag.id)) {
      group.tags.push(tag)
    }
    await loadAvailableTags()
    tagSearch.value = ''
  } catch (e) { console.error('Error adding tag:', e) }
}

async function removeTagFromGroup(group, tagId, event) {
  if (event) event.stopPropagation()
  try {
    await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags/${tagId}`, {
      method: 'DELETE',
    })
    group.tags = (group.tags || []).filter(t => t.id !== tagId)
  } catch (e) { console.error('Error removing tag:', e) }
}

function handleTagInput(event, group) {
  if (event.key === 'Enter') {
    event.preventDefault()
    const search = tagSearch.value.trim()
    if (!search) return
    const exactMatch = filteredTagSuggestions.value.find(
      t => t.name.toLowerCase() === search.toLowerCase()
    )
    addTagToGroup(group, exactMatch || search)
  } else if (event.key === 'Escape') {
    closeTagPopover()
  }
}

// --- Account Balances & Quotes ---

async function loadAccountBalances() {
  try {
    const response = await Auth.authFetch('/api/account-balances')
    const data = await response.json()
    const balances = data.balances || data
    const newBalances = {}
    if (Array.isArray(balances)) {
      balances.forEach(balance => { newBalances[balance.account_number] = balance })
    }
    accountBalances.value = newBalances
  } catch (err) { console.error('Failed to load account balances:', err) }
}

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
      wsReconnectTimer = setTimeout(() => initializeWebSocket(), 5000)
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

// --- Filters ---

function applyFilters() {
  filteredItems.value = allItems.value.filter(item => {
    if (selectedAccount.value && item.accountNumber !== selectedAccount.value) return false
    if (selectedUnderlying.value && item.underlying !== selectedUnderlying.value) return false
    return true
  })

  if (selectedAccount.value && filteredItems.value.length === 0 && allItems.value.length > 0) {
    selectedAccount.value = ''
    filteredItems.value = allItems.value.filter(item => {
      if (selectedUnderlying.value && item.underlying !== selectedUnderlying.value) return false
      return true
    })
  }
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

function onSymbolInput(event) {
  selectedUnderlying.value = event.target.value.toUpperCase()
}

function onSymbolEnterOrBlur() {
  filterPositions()
  requestLiveQuotes()
  saveFilterPreferences()
}

function clearSymbolFilter() {
  selectedUnderlying.value = ''
  filterPositions()
  requestLiveQuotes()
  saveFilterPreferences()
}

// --- Utility methods ---

function formatDollar(value) {
  const abs = Math.abs(value || 0)
  return formatNumber(abs, abs >= 100000 ? 0 : 2)
}

function dollarSizeClass(value) {
  return Math.abs(value || 0) >= 1000000 ? 'text-xs' : ''
}

// --- P&L Calculations ---

function getGroupCostBasis(group) {
  if (group._isSubtotal) return group._subtotalCostBasis
  const optionTotal = (group.positions || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
  const equityTotal = (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
  return optionTotal + equityTotal
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

// --- Live P&L for individual legs ---

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

function getGroupStrategyLabel(group) {
  if (group._isSubtotal) return ''
  if (group.strategy_type && group.strategy_type !== 'Unknown') return group.strategy_type
  return 'Unknown'
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

// --- Leg display helpers ---

function getOptionType(leg) {
  if (leg.option_type === 'Call' || leg.option_type === 'C') return 'C'
  if (leg.option_type === 'Put' || leg.option_type === 'P') return 'P'
  if (leg.option_type) return leg.option_type.charAt(0).toUpperCase()
  const match = (leg.symbol || '').match(/\d{6}([CP])/)
  if (match) return match[1]
  return '—'
}

function getSignedQuantity(leg) {
  const qty = leg.quantity || 0
  if (leg.quantity_direction === 'Short') return -qty
  return qty
}

function getExpirationDate(leg) {
  if (!leg.expiration) return ''
  const dateStr = leg.expiration.substring(0, 10)
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function getStrikePrice(leg) {
  if (leg.strike && leg.strike > 0) return parseFloat(leg.strike.toFixed(2)).toString()
  const symbol = leg.symbol || ''
  const match = symbol.match(/([CP])(\d+)/)
  if (match && match[2].length >= 3) {
    return parseFloat(parseFloat(match[2].slice(0, -3) + '.' + match[2].slice(-3)).toFixed(2)).toString()
  }
  return ''
}

function getDTE(leg) {
  if (!leg.expiration) return null
  const dateStr = leg.expiration.substring(0, 10)
  const expDate = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.ceil((expDate - today) / (1000 * 60 * 60 * 24))
}

function getUnderlyingQuote(underlying) {
  return underlyingQuotes.value[underlying] || null
}

function getUnderlyingIVR(underlying) {
  const quote = getUnderlyingQuote(underlying)
  if (!quote || !quote.ivr) return null
  return Math.round(quote.ivr * 100)
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

// --- Roll Analysis ---

function normalCDF(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327
  const p = d * Math.exp(-x * x / 2) * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x > 0 ? 1 - p : p
}

function normalPDF(x) {
  return Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI)
}

function bsDelta(S, K, T, r, sigma, isCall) {
  if (T <= 0 || sigma <= 0) return isCall ? (S > K ? 1 : 0) : (S < K ? -1 : 0)
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T))
  return isCall ? normalCDF(d1) : normalCDF(d1) - 1
}

function bsGreeks(S, K, T, r, sigma, isCall) {
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

function getEffectiveIV(underlying) {
  const quote = underlyingQuotes.value[underlying]
  if (quote && quote.iv && quote.iv > 0) return quote.iv / 100
  return 0.30
}

function getLegGreeks(leg, underlyingPrice, getStrikeFn, getOptTypeFn) {
  const optionQuote = underlyingQuotes.value[leg.symbol]

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
  const strike = getStrikeFn(leg)
  const isCall = getOptTypeFn(leg) === 'C'
  const dte = getMinDTE({ positions: [leg] }) || 0
  if (!strike || dte <= 0) return { delta: 0, gamma: 0, theta: 0, vega: 0, source: 'none' }

  const T = Math.max(dte, 0.5) / 365
  const iv = getEffectiveIV(leg.underlying || '')
  const greeks = bsGreeks(underlyingPrice, strike, T, 0.045, iv, isCall)
  return { ...greeks, source: 'bs' }
}

function getRollAnalysis(group) {
  const strategy = getGroupStrategyLabel(group)
  const supportedStrategies = ['Bull Call Spread', 'Bear Put Spread', 'Bull Put Spread', 'Bear Call Spread']
  if (!supportedStrategies.includes(strategy)) return null
  if (!rollAlertSettings.value.enabled) return null

  const positions = group.positions || []
  const underlying = group.underlying
  const quote = underlyingQuotes.value[underlying]
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

  const currentPnL = getGroupOpenPnL(group)
  const pctMaxProfit = ((currentPnL / maxProfit) * 100).toFixed(1)
  const pctMaxLoss = currentPnL < 0 ? ((Math.abs(currentPnL) / maxLoss) * 100).toFixed(1) : '0.0'

  let pnlLabel, pnlValue, pnlPositive
  if (currentPnL >= 0) {
    pnlLabel = 'Profit Captured'
    pnlValue = pctMaxProfit + '%'
    pnlPositive = true
  } else {
    pnlLabel = 'Loss Incurred'
    const lossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss)
    pnlValue = lossMetric.toFixed(1) + '%'
    pnlPositive = false
  }

  const rewardRemaining = maxProfit - currentPnL
  const riskRemaining = maxLoss + currentPnL
  const rewardToRiskRaw = riskRemaining > 0 ? rewardRemaining / riskRemaining : 99
  const rewardToRisk = rewardToRiskRaw >= 10 ? '10+' : rewardToRiskRaw.toFixed(2)

  const dte = getMinDTE(group) || 0

  // Delta saturation
  let deltaSaturation = '0.0'
  const iv = getEffectiveIV(underlying)
  if (iv > 0 && dte > 0) {
    const T = dte / 365
    const shortDelta = Math.abs(bsDelta(underlyingPrice, shortStrike, T, 0.04, iv, getOptType(shortLeg) === 'C'))
    deltaSaturation = (shortDelta * 100).toFixed(1)
  }

  const proximityToShort = ((Math.abs(underlyingPrice - shortStrike) / underlyingPrice) * 100).toFixed(1)

  // Badges
  const badges = []
  const targets = strategyTargets.value[strategy] || {}
  const profitTarget = targets.profit_target_pct || 50
  const lossLimit = targets.loss_target_pct || 100

  if (rollAlertSettings.value.profitTarget && parseFloat(pctMaxProfit) >= profitTarget) {
    badges.push({ label: 'Profit Target', color: 'green' })
  }
  if (rollAlertSettings.value.lossLimit) {
    const lossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss)
    if (currentPnL < 0 && lossMetric >= lossLimit) {
      badges.push({ label: 'Loss Limit', color: 'red' })
    }
  }
  if (rollAlertSettings.value.lateStage && dte <= 21 && dte > 0) {
    badges.push({ label: `${dte}d Left`, color: 'yellow' })
  }
  if (rollAlertSettings.value.lowRewardToRisk && rewardToRiskRaw < (isCredit ? 0.3 : 0.6)) {
    badges.push({ label: `R:R ${rewardToRisk}`, color: 'orange' })
  }

  let convexity
  if (isCredit) {
    const creditLoss = currentPnL < 0 ? Math.abs(parseFloat(pctMaxProfit)) : 0
    if (creditLoss < 50) convexity = 'Low Risk'
    else if (creditLoss < 100) convexity = 'Elevated Risk'
    else convexity = 'High Risk'
  } else {
    if (rewardToRiskRaw > 2) convexity = 'High'
    else if (rewardToRiskRaw > 0.8) convexity = 'Diminishing'
    else convexity = 'Low'
  }

  let borderColor = 'blue'
  if (badges.some(b => b.color === 'red')) borderColor = 'red'
  else if (badges.some(b => b.color === 'yellow' || b.color === 'orange')) borderColor = 'yellow'
  else if (badges.some(b => b.color === 'green')) borderColor = 'green'

  // Net position Greeks
  const longGreeks = getLegGreeks(longLeg, underlyingPrice, getStrike, getOptType)
  const shortGreeks = getLegGreeks(shortLeg, underlyingPrice, getStrike, getOptType)
  const longQty = Math.abs(longLeg.quantity || 0)
  const shortQty = Math.abs(shortLeg.quantity || 0)

  const netDelta = ((longGreeks.delta * longQty) + (shortGreeks.delta * -shortQty)) * 100
  const netGamma = ((longGreeks.gamma * longQty) + (shortGreeks.gamma * -shortQty)) * 100
  const netTheta = ((longGreeks.theta * longQty) + (shortGreeks.theta * -shortQty)) * 100
  const netVega = ((longGreeks.vega * longQty) + (shortGreeks.vega * -shortQty)) * 100

  let suggestion = null
  let urgency = 'low'
  if (parseFloat(pctMaxProfit) >= profitTarget) {
    suggestion = `Consider closing: ${pctMaxProfit}% of max profit captured.`
    urgency = 'medium'
  }
  const suggestionLossMetric = isCredit ? Math.abs(parseFloat(pctMaxProfit)) : parseFloat(pctMaxLoss)
  if (currentPnL < 0 && suggestionLossMetric >= lossLimit) {
    const lossDesc = isCredit ? 'of credit received' : 'of debit paid'
    suggestion = `Loss limit hit: ${suggestionLossMetric.toFixed(1)}% ${lossDesc}. Consider closing or rolling.`
    urgency = 'high'
  }

  return {
    pnlLabel, pnlValue, pnlPositive,
    pctMaxProfit, pctMaxLoss, rewardToRisk, rewardToRiskRaw,
    deltaSaturation, proximityToShort, convexity, isCredit,
    maxProfit: formatNumber(maxProfit, 0),
    maxLoss: formatNumber(maxLoss, 0),
    netDelta, netGamma, netTheta, netVega,
    badges, borderColor, suggestion, urgency
  }
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

// --- Notes (DB-persisted) ---

async function loadComments() {
  try {
    const response = await Auth.authFetch('/api/position-notes')
    if (response.ok) {
      const data = await response.json()
      positionComments.value = data.notes || {}
    } else {
      positionComments.value = {}
    }
  } catch (err) {
    console.error('Error loading position notes:', err)
    positionComments.value = {}
  }
  // One-time migration from localStorage
  try {
    const stored = localStorage.getItem('positionComments')
    if (stored) {
      const local = JSON.parse(stored)
      let migrated = false
      for (const [key, value] of Object.entries(local)) {
        if (value && !positionComments.value[key]) {
          positionComments.value[key] = value
          Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: value })
          }).catch(err => console.error('Migration save error:', err))
          migrated = true
        }
      }
      localStorage.removeItem('positionComments')
      if (migrated) console.log('Migrated position notes from localStorage to DB')
    }
  } catch (e) { /* ignore migration errors */ }
}

function migrateCommentKeys() {
  try {
    for (const item of allItems.value) {
      if (item._isSubtotal) continue
      const groupId = item.group_id || item.chain_id
      const sourceChainId = item.source_chain_id
      if (!groupId || !sourceChainId || groupId === sourceChainId) continue

      const newKey = `group_${groupId}`
      const oldKey = `chain_${sourceChainId}`

      if (positionComments.value[oldKey] && !positionComments.value[newKey]) {
        positionComments.value[newKey] = positionComments.value[oldKey]
        Auth.authFetch(`/api/position-notes/${encodeURIComponent(newKey)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: positionComments.value[oldKey] })
        }).catch(err => console.error('Comment key migration error:', err))
      }
      if (positionComments.value[oldKey]) {
        delete positionComments.value[oldKey]
        Auth.authFetch(`/api/position-notes/${encodeURIComponent(oldKey)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: '' })
        }).catch(err => console.error('Old key cleanup error:', err))
      }

      const oldChainKey = `chain_${groupId}`
      if (positionComments.value[oldChainKey] && !positionComments.value[newKey]) {
        positionComments.value[newKey] = positionComments.value[oldChainKey]
        Auth.authFetch(`/api/position-notes/${encodeURIComponent(newKey)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: positionComments.value[oldChainKey] })
        }).catch(err => console.error('Comment key migration error:', err))
      }
      if (positionComments.value[oldChainKey]) {
        delete positionComments.value[oldChainKey]
        Auth.authFetch(`/api/position-notes/${encodeURIComponent(oldChainKey)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: '' })
        }).catch(err => console.error('Old key cleanup error:', err))
      }
    }
  } catch (e) { /* ignore migration errors */ }
}

function getCommentKey(group) {
  if (group._isSubtotal) return null
  const groupId = group.group_id || group.chain_id || group.chainId
  if (groupId) return `group_${groupId}`
  return `pos_${group.underlying}_${group.accountNumber || 'default'}`
}

function getPositionComment(group) {
  const key = getCommentKey(group)
  if (!key) return ''
  return positionComments.value[key] || ''
}

function updatePositionComment(group, value) {
  const key = getCommentKey(group)
  if (!key) return
  positionComments.value[key] = value
  if (_noteSaveTimers[key]) {
    clearTimeout(_noteSaveTimers[key])
  }
  _noteSaveTimers[key] = setTimeout(() => {
    Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: value })
    }).catch(err => console.error('Error saving position note:', err))
    delete _noteSaveTimers[key]
  }, 500)
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

function sortedLegs(positions) {
  return [...(positions || [])].sort((a, b) => {
    const expA = a.expiration || ''
    const expB = b.expiration || ''
    if (expA !== expB) return expA.localeCompare(expB)
    return (a.strike || 0) - (b.strike || 0)
  })
}

// --- Lifecycle ---

function onDocumentClick(event) {
  if (tagPopoverGroup.value && !event.target.closest('[data-tag-popover]')) {
    closeTagPopover()
  }
}

onMounted(async () => {
  document.addEventListener('click', onDocumentClick)
  await Auth.requireAuth()
  await Auth.requireTastytrade()

  authEnabled.value = Auth.isAuthEnabled()
  if (authEnabled.value) {
    const user = await Auth.getUser()
    if (user) userEmail.value = user.email || ''
  }

  await loadComments()
  loadRollAlertSettings()
  privacyMode.value = localStorage.getItem('privacyMode') || 'off'
  await fetchAccounts()
  await loadStrategyTargets()
  loadFilterPreferences()
  await loadAccountBalances()
  await fetchPositions()
  await loadCachedQuotes()
  await loadAvailableTags()
  initializeWebSocket()
})

onUnmounted(() => {
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
  document.removeEventListener('click', onDocumentClick)
  Object.values(_noteSaveTimers).forEach(t => clearTimeout(t))
})
</script>

<template>
  <!-- Nav Bar -->
  <nav class="bg-tv-panel border-b border-tv-border sticky top-0 z-50">
    <div class="flex items-center justify-between h-16 px-4">
      <div class="flex items-center gap-8">
        <span class="text-tv-blue font-semibold text-2xl">
          <i class="fas fa-chart-line mr-2"></i>OptionLedger
        </span>
        <div class="flex items-center border-l border-tv-border pl-8 gap-4">
          <a v-for="link in navLinks" :key="link.href" :href="link.href"
             class="px-4 py-2 text-lg"
             :class="link.href === '/positions' ? 'text-tv-text bg-tv-border rounded-sm' : 'text-tv-muted hover:text-tv-text'">
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

  <!-- Action Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-3 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <button @click="fetchPositions(true)"
              :disabled="isLoading"
              class="bg-tv-green/20 hover:bg-tv-green/30 text-tv-green border border-tv-green/30 px-4 py-2 text-base disabled:opacity-50">
        <i class="fas fa-sync-alt mr-2" :class="{'animate-spin': isLoading}"></i>
        <span>{{ isLoading ? 'Syncing...' : 'Sync' }}</span>
      </button>

      <!-- Symbol Filter -->
      <div class="relative">
        <input type="text"
               :value="selectedUnderlying"
               @input="onSymbolInput($event)"
               @focus="$event.target.select()"
               @keyup.enter="onSymbolEnterOrBlur()"
               @blur="onSymbolEnterOrBlur()"
               placeholder="Symbol"
               class="bg-tv-bg border border-tv-border text-tv-text text-base px-3 py-2 w-28 uppercase placeholder:normal-case placeholder:text-tv-muted"
               :class="selectedUnderlying ? 'pr-8' : ''">
        <button v-show="selectedUnderlying"
                @click="clearSymbolFilter()"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text"
                title="Clear symbol filter">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>

      <!-- Account Balances -->
      <template v-if="currentAccountBalance">
        <div class="flex items-center gap-6 ml-6 text-base">
          <div>
            <span class="text-tv-muted text-sm">Net Liq:</span>
            <span class="font-medium ml-1">{{ privacyMode !== 'off' ? '••••••' : '$' + formatNumber(currentAccountBalance.net_liquidating_value) }}</span>
          </div>
          <div class="flex-grow"></div>
          <div>
            <span class="text-tv-muted text-sm">Cash:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.cash_balance) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-sm">Option BP:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.derivative_buying_power) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-sm">Stock BP:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.equity_buying_power) }}</span>
          </div>
        </div>
      </template>

      <span class="text-sm text-tv-muted ml-4" v-show="lastQuoteUpdate">
        Quotes: {{ lastQuoteUpdate }}
        <span v-show="liveQuotesActive" class="text-tv-green ml-1">LIVE</span>
      </span>
    </div>
  </div>

  <!-- Loading State -->
  <div v-show="isLoading" class="text-center py-12">
    <i class="fas fa-spinner fa-spin text-4xl text-tv-blue mb-4"></i>
    <p class="text-tv-muted">Loading positions...</p>
  </div>

  <!-- Empty State -->
  <div v-show="!isLoading && !error && filteredItems.length === 0" class="text-center py-12">
    <i class="fas fa-layer-group text-4xl text-tv-muted mb-4"></i>
    <p class="text-tv-muted mb-4">No open positions found</p>
  </div>

  <!-- Reconciliation Banner -->
  <div v-show="reconciliation && !isLoading" class="mx-2 mt-2">
    <div class="px-4 py-2 rounded text-sm flex items-center justify-between"
         :class="reconciliation && (reconciliation.unlinked?.length || reconciliation.quantity_mismatch?.length || reconciliation.stale?.length)
                 ? 'bg-yellow-500/10 border border-yellow-500/30 text-yellow-400'
                 : 'bg-tv-green/10 border border-tv-green/30 text-tv-green'">
      <span>
        <i class="fas fa-check-circle mr-1" v-show="reconciliation && !reconciliation.unlinked?.length && !reconciliation.quantity_mismatch?.length && !reconciliation.stale?.length"></i>
        <i class="fas fa-exclamation-triangle mr-1" v-show="reconciliation && (reconciliation.unlinked?.length || reconciliation.quantity_mismatch?.length || reconciliation.stale?.length)"></i>
        <span>{{ reconciliation ? reconciliation.matched + '/' + reconciliation.total + ' options matched' : '' }}</span>
        <span v-show="reconciliation?.unlinked?.length" class="ml-2">{{ reconciliation?.unlinked?.length + ' unlinked' }}</span>
        <span v-show="reconciliation?.stale?.length" class="ml-2">{{ reconciliation?.stale?.length + ' stale' }}</span>
        <span v-show="reconciliation?.auto_closed?.length" class="ml-2 text-tv-green">{{ reconciliation?.auto_closed?.length + ' auto-closed' }}</span>
      </span>
      <button @click="reconciliation = null" class="text-tv-muted hover:text-tv-text text-xs ml-4">
        <i class="fas fa-times"></i>
      </button>
    </div>
  </div>

  <!-- Main Content -->
  <main v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0" class="p-2">
    <!-- Column Headers -->
    <div class="flex items-center px-4 py-2 text-sm text-tv-muted border-b border-tv-border bg-tv-panel/50 sticky top-16">
      <span class="w-8"></span>
      <span class="w-6 text-center" v-show="selectedAccount === ''"></span>
      <span class="w-14 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('underlying')">
        Symbol
        <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-8 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 mr-1" @click="sortPositions('ivr')">
        IVR
        <span v-show="sortColumn === 'ivr'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-40 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('price')">
        Price
        <span v-show="sortColumn === 'price'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-12"></span>
      <span class="w-36 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('strategy')">
        Strategy
        <span v-show="sortColumn === 'strategy'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-12 text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1" @click="sortPositions('dte')">
        DTE
        <span v-show="sortColumn === 'dte'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-12 text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1" @click="sortPositions('days')">
        Days
        <span v-show="sortColumn === 'days'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('cost_basis')">
        Cost Basis
        <span v-show="sortColumn === 'cost_basis'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('net_liq')">
        Net Liq
        <span v-show="sortColumn === 'net_liq'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('realized_pnl')">
        Realized
        <span v-show="sortColumn === 'realized_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('open_pnl')">
        Open
        <span v-show="sortColumn === 'open_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('total_pnl')">
        Total
        <span v-show="sortColumn === 'total_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
      <span class="w-14 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('pnl_percent')">
        % Rtn
        <span v-show="sortColumn === 'pnl_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
      </span>
    </div>

    <!-- Position Groups -->
    <div class="divide-y divide-tv-border">
      <div v-for="(group, index) in groupedPositions" :key="group.groupKey">

        <!-- Subtotal Row -->
        <div v-if="group._isSubtotal" class="flex items-center px-4 py-2 bg-blue-500/10 border-l-2 border-tv-blue">
          <div class="w-8"></div>
          <div class="w-6" v-show="selectedAccount === ''"></div>
          <div class="w-14">
            <div class="font-bold text-base text-tv-text">{{ group.displayKey }}</div>
          </div>
          <div class="w-8 mr-1"></div>
          <div class="w-40"></div>
          <div class="w-12"></div>
          <!-- Strategy -->
          <div class="w-36 text-xs text-tv-muted">{{ group._childCount }} positions</div>
          <!-- DTE -->
          <div class="w-12"></div>
          <!-- Days -->
          <div class="w-12"></div>
          <!-- Cost Basis -->
          <div class="w-24 text-right font-medium"
               :class="(group._subtotalCostBasis >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalCostBasis)">
            <span v-show="group._subtotalCostBasis < 0">-</span>${{ formatDollar(group._subtotalCostBasis) }}
          </div>
          <!-- Net Liq -->
          <div class="w-24 text-right font-medium"
               :class="(group._subtotalNetLiq >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalNetLiq)">
            <span v-show="group._subtotalNetLiq < 0">-</span>${{ formatDollar(group._subtotalNetLiq) }}
          </div>
          <!-- Realized -->
          <div class="w-24 text-right font-medium"
               :class="(group._subtotalRealizedPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalRealizedPnL)">
            <span v-show="group._subtotalRealizedPnL !== 0">
              <span v-show="group._subtotalRealizedPnL < 0">-</span>${{ formatDollar(group._subtotalRealizedPnL) }}
            </span>
          </div>
          <!-- Open P/L -->
          <div class="w-24 text-right font-medium"
               :class="(group._subtotalOpenPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalOpenPnL)">
            <span v-show="group._subtotalOpenPnL < 0">-</span>${{ formatDollar(group._subtotalOpenPnL) }}
          </div>
          <!-- Total P/L -->
          <div class="w-24 text-right font-bold"
               :class="(group._subtotalTotalPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalTotalPnL)">
            <span v-show="group._subtotalTotalPnL < 0">-</span>${{ formatDollar(group._subtotalTotalPnL) }}
          </div>
          <!-- % Rtn -->
          <div class="w-14"></div>
        </div>

        <!-- Regular Row (Chain or Share) -->
        <template v-else>
          <div>
            <!-- Group Row -->
            <div class="flex items-center px-4 py-2 hover:bg-tv-border/30 cursor-pointer transition-colors"
                 @click="toggleExpanded(group.groupKey)">
              <!-- Chevron -->
              <div class="w-8">
                <i class="fas fa-chevron-right text-tv-muted transition-transform duration-200"
                   :class="{ 'rotate-90': expandedRows.has(group.groupKey) }"></i>
              </div>

              <!-- Account Symbol (only when All Accounts selected) -->
              <div class="w-6 text-center text-tv-muted text-sm" v-show="selectedAccount === ''">
                {{ getAccountSymbol(group.accountNumber) }}
              </div>

              <!-- Symbol -->
              <div class="w-14">
                <div class="font-semibold text-base text-tv-text">
                  {{ group.displayKey || group.underlying }}
                  <span v-show="hasEquity(group) && (group.positions || []).length > 0" class="text-[10px] text-tv-muted ml-1 bg-tv-border/50 px-1 rounded">+stk</span>
                </div>
              </div>

              <!-- IVR -->
              <div class="w-8 text-right mr-1"
                   :class="getUnderlyingIVR(group.underlying) >= 50 ? 'font-bold text-yellow-400' : 'text-tv-muted'">
                {{ getUnderlyingIVR(group.underlying) !== null ? getUnderlyingIVR(group.underlying) : '' }}
              </div>

              <!-- Price -->
              <div class="w-40 flex items-center gap-2">
                <template v-if="getUnderlyingQuote(group.underlying)">
                  <div class="flex items-center gap-2">
                    <div class="w-20 px-2 py-1 rounded-sm text-base font-medium border text-right"
                         style="font-variant-numeric: tabular-nums"
                         :class="(getUnderlyingQuote(group.underlying).change || 0) >= 0 ? 'bg-green-900/60 text-green-400 border-green-700/50' : 'bg-tv-border text-tv-muted border-tv-border'">
                      {{ formatNumber(getUnderlyingQuote(group.underlying).price || 0) }}
                    </div>
                    <div class="w-16 text-right text-sm"
                         style="font-variant-numeric: tabular-nums"
                         :class="(getUnderlyingQuote(group.underlying).change || 0) >= 0 ? 'text-green-400' : 'text-tv-muted'">
                      {{ ((getUnderlyingQuote(group.underlying).change || 0) >= 0 ? '+' : '') + (getUnderlyingQuote(group.underlying).changePercent || 0).toFixed(2) + '%' }}
                    </div>
                  </div>
                </template>
                <template v-else>
                  <span class="text-tv-muted text-sm"><i class="fas fa-spinner fa-spin"></i></span>
                </template>
              </div>

              <!-- Ledger Link -->
              <div class="w-12">
                <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying)"
                   @click.stop
                   class="text-tv-blue hover:text-blue-400"
                   title="View in Ledger">
                  <i class="fas fa-book"></i>
                  <span v-show="group.roll_count > 0" class="text-xs text-tv-muted ml-0.5">R{{ group.roll_count }}</span>
                </a>
              </div>

              <!-- Strategy -->
              <div class="w-36 relative">
                <div class="text-sm text-tv-muted">{{ getGroupStrategyLabel(group) }}</div>
                <template v-if="group.rollAnalysis && group.rollAnalysis.badges.length > 0">
                  <div class="flex flex-wrap gap-1 mt-0.5">
                    <span v-for="badge in group.rollAnalysis.badges" :key="badge.label"
                          class="text-[10px] px-1.5 py-0 rounded-sm border leading-4"
                          :class="{
                            'bg-green-500/20 text-green-400 border-green-500/50': badge.color === 'green',
                            'bg-red-500/20 text-red-400 border-red-500/50': badge.color === 'red',
                            'bg-yellow-500/20 text-yellow-400 border-yellow-500/50': badge.color === 'yellow',
                            'bg-orange-500/20 text-orange-400 border-orange-500/50': badge.color === 'orange'
                          }">{{ badge.label }}</span>
                  </div>
                </template>
                <!-- Tag chips -->
                <div class="flex flex-wrap gap-1 mt-0.5 items-center" data-tag-popover @click.stop>
                  <span v-for="tag in (group.tags || [])" :key="tag.id"
                        class="text-[10px] px-1.5 py-0.5 rounded-full border inline-flex items-center gap-0.5 leading-3"
                        :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
                    <span>{{ tag.name }}</span>
                    <button @click="removeTagFromGroup(group, tag.id, $event)"
                            class="hover:opacity-70 ml-0.5 leading-none">&times;</button>
                  </span>
                  <button @click="openTagPopover(group.group_id, $event)"
                          class="text-[10px] w-4 h-4 rounded-full border border-tv-border/50 text-tv-muted hover:text-tv-blue hover:border-tv-blue/50 flex items-center justify-center leading-none"
                          title="Add tag">+</button>
                </div>
                <!-- Tag popover -->
                <div v-if="tagPopoverGroup === group.group_id"
                     class="absolute top-full left-0 mt-1 z-50 bg-[#1e222d] border border-tv-border rounded shadow-lg p-1.5 w-44"
                     data-tag-popover
                     @click.stop>
                  <input type="text"
                         :id="'tag-input-' + group.group_id"
                         v-model="tagSearch"
                         @keydown="handleTagInput($event, group)"
                         class="w-full bg-tv-bg border border-tv-border text-tv-text text-xs px-2 py-1 rounded outline-none focus:border-tv-blue/50"
                         placeholder="Type tag name...">
                  <div class="max-h-28 overflow-y-auto mt-1">
                    <button v-for="tag in filteredTagSuggestions" :key="tag.id"
                            @click="addTagToGroup(group, tag); closeTagPopover()"
                            class="flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs text-tv-text hover:bg-tv-panel rounded">
                      <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="`background: ${tag.color}`"></span>
                      <span>{{ tag.name }}</span>
                    </button>
                    <button v-if="tagSearch.trim() && !filteredTagSuggestions.find(t => t.name.toLowerCase() === tagSearch.trim().toLowerCase())"
                            @click="addTagToGroup(group, tagSearch.trim()); closeTagPopover()"
                            class="flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs text-tv-blue hover:bg-tv-panel rounded">
                      <i class="fas fa-plus text-[8px]"></i>
                      <span>Create "{{ tagSearch.trim() }}"</span>
                    </button>
                  </div>
                </div>
              </div>

              <!-- DTE -->
              <div class="w-12 text-center"
                   :class="getMinDTE(group) !== null && getMinDTE(group) <= 21 ? 'font-bold text-yellow-400' : 'text-tv-text'">
                {{ getMinDTE(group) !== null ? getMinDTE(group) : '' }}
              </div>

              <!-- Days -->
              <div class="w-12 text-center text-tv-text">{{ getGroupDaysOpen(group) || '' }}</div>

              <!-- Cost Basis -->
              <div class="w-24 text-right"
                   :class="(getGroupCostBasis(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupCostBasis(group))">
                <span v-show="getGroupCostBasis(group) < 0">-</span>${{ formatDollar(getGroupCostBasis(group)) }}
              </div>

              <!-- Net Liq -->
              <div class="w-24 text-right font-medium"
                   :class="(getGroupNetLiqWithLiveQuotes(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupNetLiqWithLiveQuotes(group))">
                <span v-show="getGroupNetLiqWithLiveQuotes(group) < 0">-</span>${{ formatDollar(getGroupNetLiqWithLiveQuotes(group)) }}
              </div>

              <!-- Realized P/L -->
              <div class="w-24 text-right"
                   :class="(getGroupRealizedPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupRealizedPnL(group))">
                <template v-if="getGroupRealizedPnL(group) !== 0">
                  <span v-show="getGroupRealizedPnL(group) < 0">-</span>${{ formatDollar(getGroupRealizedPnL(group)) }}
                </template>
              </div>

              <!-- Open P/L -->
              <div class="w-24 text-right font-medium"
                   :class="(getGroupOpenPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupOpenPnL(group))">
                <span v-show="getGroupOpenPnL(group) < 0">-</span>${{ formatDollar(getGroupOpenPnL(group)) }}
              </div>

              <!-- Total P/L -->
              <div class="w-24 text-right font-bold"
                   :class="(getGroupTotalPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupTotalPnL(group))">
                <span v-show="getGroupTotalPnL(group) < 0">-</span>${{ formatDollar(getGroupTotalPnL(group)) }}
              </div>

              <!-- % Rtn -->
              <div class="w-14 text-right"
                   :class="getGroupPnLPercent(group) !== null ? (parseFloat(getGroupPnLPercent(group)) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
                {{ getGroupPnLPercent(group) !== null ? getGroupPnLPercent(group) + '%' : '' }}
              </div>

              <!-- Note indicator -->
              <i class="fas fa-sticky-note text-yellow-400 text-sm pl-2"
                 v-show="getPositionComment(group)" title="Has notes"></i>
            </div>

            <!-- Expanded Detail Panel -->
            <div v-show="expandedRows.has(group.groupKey)" class="bg-tv-bg border-t border-tv-border">
              <div class="mx-4 my-3 p-3 bg-tv-panel rounded border border-tv-border font-mono">
                <div class="flex gap-4">
                  <div class="flex-shrink-0 space-y-1">
                    <!-- Option legs section -->
                    <template v-if="(group.positions || []).length > 0">
                      <div>
                        <!-- Header row -->
                        <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                          <span class="w-10 text-right">Qty</span>
                          <span class="w-16 text-center mx-2">Exp</span>
                          <span class="w-10">DTE</span>
                          <span class="w-16 text-center mx-2">Strike</span>
                          <span class="w-6">Type</span>
                          <span class="w-24 text-right ml-4">Cost Basis</span>
                          <span class="w-20 text-right">Net Liq</span>
                          <span class="w-20 text-right">Open P/L</span>
                        </div>

                        <!-- Option legs -->
                        <div v-for="leg in sortedLegs(group.positions)" :key="leg.lot_id || leg.symbol"
                             class="flex items-center text-sm py-0.5">
                          <span class="w-10 text-right font-medium"
                                :class="getSignedQuantity(leg) > 0 ? 'text-tv-green' : 'text-tv-red'">
                            {{ getSignedQuantity(leg) }}
                          </span>
                          <span class="w-16 text-center bg-tv-border/30 mx-2 py-0.5 rounded text-tv-text">
                            {{ getExpirationDate(leg) }}
                          </span>
                          <span class="w-10 text-tv-muted"
                                :class="getDTE(leg) <= 7 ? 'text-tv-red' : getDTE(leg) <= 30 ? 'text-yellow-400' : ''">
                            {{ getDTE(leg) !== null ? getDTE(leg) + 'd' : '' }}
                          </span>
                          <span class="w-16 text-center bg-tv-border/30 mx-2 py-0.5 rounded text-tv-text">
                            {{ getStrikePrice(leg) }}
                          </span>
                          <span class="w-6 text-tv-muted">{{ getOptionType(leg) }}</span>
                          <span class="w-24 text-right ml-4"
                                :class="(leg.cost_basis || 0) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(leg.cost_basis || 0) }}
                          </span>
                          <span class="w-20 text-right text-tv-muted">
                            ${{ formatNumber(calculateLegMarketValue(leg)) }}
                          </span>
                          <span class="w-20 text-right font-medium"
                                :class="calculateLegPnL(leg) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(calculateLegPnL(leg)) }}
                          </span>
                        </div>
                      </div>
                    </template>

                    <!-- Equity section -->
                    <template v-if="(group.equityLegs || []).length > 0">
                      <div :class="(group.positions || []).length > 0 ? 'mt-2 pt-2 border-t border-tv-border/30' : ''">
                        <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                          <span class="w-16">Shares</span>
                          <span class="w-20 text-right">Avg Price</span>
                          <span class="w-24 text-right ml-4">Cost Basis</span>
                          <span class="w-20 text-right">Mkt Value</span>
                          <span class="w-20 text-right">Open P/L</span>
                        </div>
                        <div class="flex items-center text-sm py-0.5">
                          <span class="w-16 font-medium text-tv-text">{{ group.equitySummary?.quantity || 0 }}</span>
                          <span class="w-20 text-right text-tv-muted">${{ formatNumber(group.equitySummary?.average_price || 0) }}</span>
                          <span class="w-24 text-right ml-4 text-tv-muted">
                            ${{ formatNumber(group.equitySummary?.cost_basis || 0) }}
                          </span>
                          <span class="w-20 text-right text-tv-muted">
                            ${{ formatNumber(calculateEquityMarketValue(group)) }}
                          </span>
                          <span class="w-20 text-right font-medium"
                                :class="(calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) }}
                          </span>
                        </div>
                      </div>
                    </template>

                    <!-- No legs message for assigned chains -->
                    <template v-if="(group.positions || []).length === 0 && (group.equityLegs || []).length === 0">
                      <div class="text-xs text-tv-muted py-1">
                        <span v-show="group.has_assignment">All positions assigned/exercised</span>
                        <span v-show="!group.has_assignment">No open legs</span>
                      </div>
                    </template>

                    <!-- Chain summary -->
                    <div class="flex items-center text-xs text-tv-muted mt-2 pt-1 border-t border-tv-border/30 gap-4">
                      <span>Opened: {{ group.opening_date || 'N/A' }}</span>
                      <span>Orders: {{ group.order_count || 1 }}</span>
                      <span v-show="group.roll_count > 0" class="text-tv-blue">Rolls: {{ group.roll_count }}</span>
                      <span v-show="group.realized_pnl !== 0"
                            :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                        Realized: ${{ formatNumber(group.realized_pnl) }}
                      </span>
                    </div>
                  </div>

                  <!-- Comments -->
                  <div class="flex-1 min-w-0">
                    <div class="text-xs text-tv-muted pb-1 border-b border-tv-border/30 mb-1">Notes</div>
                    <textarea :value="getPositionComment(group)"
                              @input="updatePositionComment(group, $event.target.value)"
                              @click.stop
                              rows="3"
                              class="w-full bg-transparent text-tv-text text-sm font-sans border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                              placeholder="Add notes..."></textarea>
                  </div>
                </div>
              </div>

              <!-- Roll Analysis Panel -->
              <template v-if="group.rollAnalysis">
                <div class="mx-4 mb-3 p-3 bg-tv-panel rounded border-l-2"
                     :class="{
                       'border-green-500 border border-l-2 border-green-500/30': group.rollAnalysis.borderColor === 'green',
                       'border-red-500 border border-l-2 border-red-500/30': group.rollAnalysis.borderColor === 'red',
                       'border-yellow-500 border border-l-2 border-yellow-500/30': group.rollAnalysis.borderColor === 'yellow',
                       'border-tv-blue border border-l-2 border-tv-blue/30': group.rollAnalysis.borderColor === 'blue'
                     }">
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-tv-text">Roll Analysis</span>
                    <span class="text-[10px] px-1.5 py-0 rounded-sm border leading-4"
                          :class="{
                            'bg-green-500/20 text-green-400 border-green-500/50': group.rollAnalysis.convexity === 'High' || group.rollAnalysis.convexity === 'Low Risk',
                            'bg-yellow-500/20 text-yellow-400 border-yellow-500/50': group.rollAnalysis.convexity === 'Diminishing' || group.rollAnalysis.convexity === 'Elevated Risk',
                            'bg-red-500/20 text-red-400 border-red-500/50': group.rollAnalysis.convexity === 'Low' || group.rollAnalysis.convexity === 'High Risk'
                          }">
                      {{ group.rollAnalysis.isCredit ? group.rollAnalysis.convexity : (group.rollAnalysis.convexity + ' Convexity') }}
                    </span>
                  </div>
                  <!-- Compact 3-column layout -->
                  <div class="flex gap-6 text-xs mb-2">
                    <!-- P&L Status -->
                    <div class="space-y-1">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">P&L Status</div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">{{ group.rollAnalysis.pnlLabel }}</span>
                        <span class="font-medium" :class="group.rollAnalysis.pnlPositive ? 'text-tv-green' : 'text-tv-red'">
                          {{ group.rollAnalysis.pnlValue }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Reward:Risk</span>
                        <span class="font-medium" :class="group.rollAnalysis.rewardToRiskRaw < (group.rollAnalysis.isCredit ? 0.3 : 0.6) ? 'text-orange-400' : 'text-tv-text'">
                          {{ group.rollAnalysis.rewardToRisk }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Max P / L</span>
                        <span class="font-medium text-tv-text">
                          ${{ group.rollAnalysis.maxProfit }} / ${{ group.rollAnalysis.maxLoss }}
                        </span>
                      </div>
                    </div>
                    <!-- Greeks -->
                    <div class="space-y-1 border-l border-tv-border/20 pl-6">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">Greeks</div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Net Delta</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.netDelta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netDelta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          {{ group.rollAnalysis.netDelta.toFixed(2) }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Theta/Day</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.netTheta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netTheta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          ${{ group.rollAnalysis.netTheta.toFixed(2) }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Gamma</span>
                        <span class="font-medium text-tv-text">{{ group.rollAnalysis.netGamma.toFixed(2) }}</span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Vega</span>
                        <span class="font-medium text-tv-text">{{ group.rollAnalysis.netVega.toFixed(2) }}</span>
                      </div>
                    </div>
                    <!-- Context -->
                    <div class="space-y-1 border-l border-tv-border/20 pl-6">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">Context</div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Near Short</span>
                        <span class="font-medium" :class="parseFloat(group.rollAnalysis.proximityToShort) < 3 ? 'text-yellow-400' : 'text-tv-text'">
                          {{ group.rollAnalysis.proximityToShort }}%
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Delta Sat.</span>
                        <span class="font-medium" :class="parseFloat(group.rollAnalysis.deltaSaturation) >= 65 ? (group.rollAnalysis.isCredit ? 'text-tv-red' : 'text-orange-400') : 'text-tv-text'">
                          {{ group.rollAnalysis.deltaSaturation }}%
                        </span>
                      </div>
                    </div>
                  </div>
                  <!-- Footer: Suggestion + AI Insight placeholder -->
                  <div class="flex items-start justify-between gap-2">
                    <template v-if="group.rollAnalysis.suggestion">
                      <div class="flex-1 pl-3 py-2 border-l-2 text-xs text-tv-text bg-tv-bg/50 rounded-r"
                           :class="{
                             'border-red-500': group.rollAnalysis.urgency === 'high',
                             'border-yellow-500': group.rollAnalysis.urgency === 'medium',
                             'border-tv-blue': group.rollAnalysis.urgency === 'low'
                           }">
                        {{ group.rollAnalysis.suggestion }}
                      </div>
                    </template>
                    <button disabled
                            class="ml-auto text-xs px-2 py-1 rounded border border-tv-border/50 text-tv-muted cursor-not-allowed shrink-0"
                            title="Coming soon">
                      <i class="fas fa-wand-magic-sparkles mr-1"></i>AI Insight
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </template>

      </div>
    </div>
  </main>
</template>
