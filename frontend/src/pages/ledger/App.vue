<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { STRATEGY_CATEGORIES } from '@/lib/constants'
import { formatNumber, formatDate, formatOrderDate, formatExpirationShort, calculateDTE } from '@/lib/formatters'

const Auth = useAuth()

// ==================== STATE ====================
const groups = ref([])
const accounts = ref([])
const filteredGroups = ref([])
const selectedAccount = ref('')
const filterUnderlying = ref('')
const timePeriod = ref('all')
const showOpen = ref(true)
const showClosed = ref(true)
const viewMode = ref('positions')
const sortColumn = ref('opening_date')
const sortDirection = ref('desc')
const loading = ref(true)
const selectedLots = ref([])
const stats = ref({ totalPnl: 0, openCount: 0, closedCount: 0 })
const filterDirection = ref([])
const filterType = ref([])
const groupNotes = ref({})
const orderComments = ref({})
const availableTags = ref([])
const tagPopoverGroup = ref(null)
const tagSearch = ref('')

// Nav auth
const authEnabled = ref(false)
const userEmail = ref('')

// Internal (non-reactive)
const noteSaveTimers = {}

// ==================== COMPUTED ====================
const filteredTagSuggestions = computed(() => {
  const search = (tagSearch.value || '').toLowerCase()
  const group = groups.value.find(g => g.group_id === tagPopoverGroup.value)
  const appliedIds = (group?.tags || []).map(t => t.id)
  return availableTags.value
    .filter(t => !appliedIds.includes(t.id))
    .filter(t => !search || t.name.toLowerCase().includes(search))
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  await Auth.requireAuth()
  await Auth.requireTastytrade()

  authEnabled.value = Auth.isAuthEnabled?.() || false
  if (authEnabled.value) {
    const user = Auth.getUser?.()
    userEmail.value = user?.email || ''
  }

  await loadAccounts()

  // Restore state from localStorage
  const saved = localStorage.getItem('ledger_state')
  if (saved) {
    try {
      const state = JSON.parse(saved)
      timePeriod.value = state.timePeriod || 'all'
      showOpen.value = state.showOpen !== undefined ? state.showOpen : true
      showClosed.value = state.showClosed !== undefined ? state.showClosed : true
      sortColumn.value = state.sortColumn || 'opening_date'
      sortDirection.value = state.sortDirection || 'desc'
      viewMode.value = state.viewMode || 'positions'
      filterDirection.value = state.filterDirection || []
      filterType.value = state.filterType || []
    } catch (e) {}
  }

  const savedAccount = localStorage.getItem('trade_journal_selected_account')
  if (savedAccount) selectedAccount.value = savedAccount

  // URL params override saved state
  const urlParams = new URLSearchParams(window.location.search)
  const underlyingParam = urlParams.get('underlying')
  if (underlyingParam) {
    filterUnderlying.value = underlyingParam.toUpperCase()
    timePeriod.value = 'all'
    showOpen.value = true
    showClosed.value = true
  } else {
    const savedUnderlying = localStorage.getItem('trade_journal_selected_underlying')
    if (savedUnderlying) filterUnderlying.value = savedUnderlying
  }

  await fetchLedger()
  await loadNotes()
  await loadAvailableTags()
})

// ==================== DATA FETCHING ====================
async function loadAccounts() {
  try {
    const response = await Auth.authFetch('/api/accounts')
    const data = await response.json()
    const list = data.accounts || []
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
  } catch (error) {
    console.error('Error loading accounts:', error)
  }
}

async function fetchLedger() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (selectedAccount.value) params.set('account_number', selectedAccount.value)
    const url = '/api/ledger' + (params.toString() ? '?' + params.toString() : '')
    const response = await Auth.authFetch(url)
    const data = await response.json()
    groups.value = data.map(g => ({ ...g, expanded: false, _viewMode: null, _movingLots: false, _editingStrategy: false }))
    applyFilters()
  } catch (error) {
    console.error('Error fetching ledger:', error)
  } finally {
    loading.value = false
  }
}

// ==================== FILTERING & SORTING ====================
function sortGroups(column) {
  if (sortColumn.value === column) {
    sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = column
    if (column === 'opening_date' || column === 'closing_date' || column === 'total_pnl') {
      sortDirection.value = 'desc'
    } else {
      sortDirection.value = 'asc'
    }
  }
  applyFilters()
  saveState()
}

function applyFilters() {
  let filtered = [...groups.value]

  if (filterUnderlying.value) {
    const sym = filterUnderlying.value.toUpperCase()
    filtered = filtered.filter(g => (g.underlying || '').toUpperCase() === sym)
  }

  filtered = filtered.filter(g => groupMatchesCategoryFilters(g))

  if (!showOpen.value) filtered = filtered.filter(g => g.status !== 'OPEN')
  if (!showClosed.value) filtered = filtered.filter(g => g.status !== 'CLOSED')

  if (timePeriod.value !== 'all') {
    let cutoffStart
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    if (timePeriod.value === 'today') {
      cutoffStart = today
    } else if (timePeriod.value === 'yesterday') {
      cutoffStart = new Date(today)
      cutoffStart.setDate(cutoffStart.getDate() - 1)
    } else {
      const days = parseInt(timePeriod.value)
      if (!isNaN(days)) {
        cutoffStart = new Date(today)
        cutoffStart.setDate(cutoffStart.getDate() - days)
      }
    }

    if (cutoffStart) {
      filtered = filtered.filter(g => {
        const opened = g.opening_date ? new Date(g.opening_date) : null
        const closed = g.closing_date ? new Date(g.closing_date) : null
        const inRange = (d) => d && d >= cutoffStart
        return inRange(opened) || inRange(closed)
      })
    }
  }

  // Sort
  filtered.sort((a, b) => {
    let va, vb
    const col = sortColumn.value
    if (col === 'opening_date' || col === 'closing_date') {
      va = a[col] || ''
      vb = b[col] || ''
    } else if (col === 'underlying') {
      va = a.underlying || ''
      vb = b.underlying || ''
    } else if (col === 'strategy_label') {
      va = a.strategy_label || ''
      vb = b.strategy_label || ''
    } else if (col === 'status') {
      va = a.status || ''
      vb = b.status || ''
    } else if (col === 'lot_count') {
      va = a.lot_count || 0
      vb = b.lot_count || 0
    } else if (col === 'total_pnl') {
      va = a.realized_pnl || 0
      vb = b.realized_pnl || 0
    } else {
      va = a[col] || ''
      vb = b[col] || ''
    }

    let cmp = 0
    if (typeof va === 'number' && typeof vb === 'number') {
      cmp = va - vb
    } else {
      cmp = String(va).localeCompare(String(vb))
    }
    return sortDirection.value === 'desc' ? -cmp : cmp
  })

  filteredGroups.value = filtered
  computeStats()
}

function computeStats() {
  let totalPnl = 0, openCount = 0, closedCount = 0
  for (const g of filteredGroups.value) {
    totalPnl += g.realized_pnl || 0
    if (g.status === 'OPEN') openCount++
    else closedCount++
  }
  stats.value = { totalPnl, openCount, closedCount }
}

function toggleFilter(category, value) {
  if (category === 'direction') {
    const idx = filterDirection.value.indexOf(value)
    if (idx >= 0) {
      filterDirection.value.splice(idx, 1)
    } else {
      filterDirection.value.push(value)
    }
  } else if (category === 'type') {
    const idx = filterType.value.indexOf(value)
    if (idx >= 0) {
      filterType.value.splice(idx, 1)
    } else {
      filterType.value = [value]
    }
  }
  saveState()
  applyFilters()
}

function groupMatchesCategoryFilters(group) {
  const strategy = group.strategy_label || ''
  const noDirectionFilter = filterDirection.value.length === 0
  const noTypeFilter = filterType.value.length === 0
  if (noDirectionFilter && noTypeFilter) return true
  const cat = STRATEGY_CATEGORIES[strategy]
  if (!cat) return noDirectionFilter && noTypeFilter
  if (cat.isShares) return noDirectionFilter && noTypeFilter
  const directionMatch = noDirectionFilter || filterDirection.value.includes(cat.direction)
  const typeMatch = noTypeFilter || filterType.value.includes(cat.type)
  return directionMatch && typeMatch
}

function cleanUrlParams() {
  const url = new URL(window.location)
  if (url.searchParams.has('underlying')) {
    url.searchParams.delete('underlying')
    window.history.replaceState({}, '', url.pathname + (url.search || ''))
  }
}

function onAccountChange() {
  localStorage.setItem('trade_journal_selected_account', selectedAccount.value)
  fetchLedger()
}

function onSymbolFilterApply() {
  applyFilters()
  localStorage.setItem('trade_journal_selected_underlying', filterUnderlying.value || '')
  cleanUrlParams()
}

function clearSymbolFilter() {
  filterUnderlying.value = ''
  applyFilters()
  localStorage.setItem('trade_journal_selected_underlying', '')
  cleanUrlParams()
}

function saveState() {
  localStorage.setItem('ledger_state', JSON.stringify({
    timePeriod: timePeriod.value,
    showOpen: showOpen.value,
    showClosed: showClosed.value,
    sortColumn: sortColumn.value,
    sortDirection: sortDirection.value,
    viewMode: viewMode.value,
    filterDirection: filterDirection.value,
    filterType: filterType.value,
  }))
}

// ==================== GROUP MANAGEMENT ====================
function toggleGroupMoveMode(group) {
  const wasMoving = group._movingLots
  clearAllMoveMode()
  if (!wasMoving) {
    group._movingLots = true
    group.expanded = true
  }
}

function clearAllMoveMode() {
  for (const g of groups.value) {
    g._movingLots = false
  }
  selectedLots.value = []
}

function cancelMoveMode() {
  clearAllMoveMode()
}

function groupViewMode(group) {
  return group._viewMode || viewMode.value
}

function sortedLots(group) {
  return (group.lots || []).slice().sort((a, b) => {
    const aOpen = a.status !== 'CLOSED' ? 0 : 1
    const bOpen = b.status !== 'CLOSED' ? 0 : 1
    if (aOpen !== bOpen) return aOpen - bOpen
    const aDate = a.entry_date || ''
    const bDate = b.entry_date || ''
    if (aDate !== bDate) return bDate.localeCompare(aDate)
    const aExp = a.expiration || ''
    const bExp = b.expiration || ''
    if (aExp !== bExp) return bExp.localeCompare(aExp)
    return (b.strike || 0) - (a.strike || 0)
  })
}

function sortedOptionLots(group) {
  return sortedLots(group).filter(l => l.instrument_type !== 'EQUITY' || l.status === 'CLOSED')
}

function openEquityLots(group) {
  return (group.lots || []).filter(l => l.instrument_type === 'EQUITY' && l.status !== 'CLOSED')
    .sort((a, b) => (b.entry_date || '').localeCompare(a.entry_date || ''))
}

function equityAggregate(group) {
  const lots = openEquityLots(group)
  if (lots.length === 0) return null
  const totalQty = lots.reduce((s, l) => s + (l.remaining_quantity ?? l.quantity), 0)
  const totalCost = lots.reduce((s, l) => s + (l.cost_basis || 0), 0)
  return {
    quantity: totalQty,
    avgPrice: totalQty !== 0 ? Math.abs(totalCost) / Math.abs(totalQty) : 0,
    costBasis: totalCost,
    lotCount: lots.length,
  }
}

function toggleAllEquityLots(group) {
  const ids = openEquityLots(group).map(l => l.transaction_id)
  const allSelected = ids.every(id => selectedLots.value.includes(id))
  if (allSelected) {
    selectedLots.value = selectedLots.value.filter(id => !ids.includes(id))
  } else {
    for (const id of ids) {
      if (!selectedLots.value.includes(id)) selectedLots.value.push(id)
    }
  }
}

function toggleLotSelection(transactionId) {
  const idx = selectedLots.value.indexOf(transactionId)
  if (idx >= 0) {
    selectedLots.value.splice(idx, 1)
  } else {
    selectedLots.value.push(transactionId)
  }
}

function toggleLotExpand(lot) {
  lot._expanded = !lot._expanded
}

function _getSourceInfo() {
  let underlying = null, account = null
  const sourceIds = new Set()
  for (const g of groups.value) {
    for (const lot of (g.lots || [])) {
      if (selectedLots.value.includes(lot.transaction_id)) {
        underlying = g.underlying
        account = g.account_number
        sourceIds.add(g.group_id)
        break
      }
    }
  }
  return { underlying, account, sourceIds }
}

function _inferStrategyLabel() {
  const lots = []
  for (const g of groups.value) {
    for (const lot of (g.lots || [])) {
      if (selectedLots.value.includes(lot.transaction_id)) lots.push(lot)
    }
  }
  const optionLots = lots.filter(l => l.option_type)
  if (optionLots.length === 0) return null
  const firstType = optionLots[0].option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put'
  const firstDir = optionLots[0].quantity < 0 ? 'Short' : 'Long'
  const allSame = optionLots.every(l => {
    const t = l.option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put'
    const d = l.quantity < 0 ? 'Short' : 'Long'
    return t === firstType && d === firstDir
  })
  return allSame ? `${firstDir} ${firstType}` : null
}

function isEligibleTarget(group) {
  if (selectedLots.value.length === 0) return false
  const { underlying, account, sourceIds } = _getSourceInfo()
  return group.underlying === underlying &&
         group.account_number === account &&
         !sourceIds.has(group.group_id)
}

function isSourceGroup(group) {
  if (selectedLots.value.length === 0) return false
  const { sourceIds } = _getSourceInfo()
  return sourceIds.has(group.group_id)
}

async function moveLots(targetGroupId) {
  if (!targetGroupId || selectedLots.value.length === 0) return

  if (targetGroupId === '__new__') {
    const { underlying, account } = _getSourceInfo()
    const strategyLabel = _inferStrategyLabel()
    try {
      const resp = await Auth.authFetch('/api/ledger/groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_number: account, underlying, strategy_label: strategyLabel }),
      })
      const result = await resp.json()
      targetGroupId = result.group_id
    } catch (error) {
      console.error('Error creating group:', error)
      return
    }
  }

  try {
    await Auth.authFetch('/api/ledger/move-lots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_ids: selectedLots.value, target_group_id: targetGroupId }),
    })
    clearAllMoveMode()
    await fetchLedger()
  } catch (error) {
    console.error('Error moving lots:', error)
  }
}

async function updateGroupStrategy(group, value) {
  if (value === group.strategy_label) return
  try {
    await Auth.authFetch(`/api/ledger/groups/${group.group_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy_label: value }),
    })
    group.strategy_label = value
  } catch (error) {
    console.error('Error updating strategy:', error)
  }
}

// ==================== DISPLAY HELPERS ====================
function getAccountSymbol(accountNumber) {
  const account = accounts.value.find(a => a.account_number === accountNumber)
  if (!account) return '?'
  const name = (account.account_name || '').toUpperCase()
  if (name.includes('ROTH')) return 'R'
  if (name.includes('INDIVIDUAL')) return 'I'
  if (name.includes('TRADITIONAL')) return 'T'
  return name.charAt(0) || '?'
}

function getAccountBadgeClass(accountNumber) {
  const symbol = getAccountSymbol(accountNumber)
  if (symbol === 'R') return 'bg-purple-900/60 text-purple-400'
  if (symbol === 'I') return 'bg-blue-900/60 text-blue-400'
  if (symbol === 'T') return 'bg-green-900/60 text-green-400'
  return 'bg-tv-border text-tv-muted'
}

function formatAction(action) {
  if (!action) return ''
  const cleanAction = action.replace(/^(ORDERACTION\.|OrderAction\.)/, '')
  const actionMap = {
    'SELL_TO_OPEN': 'STO', 'BUY_TO_CLOSE': 'BTC',
    'BUY_TO_OPEN': 'BTO', 'SELL_TO_CLOSE': 'STC',
    'EXPIRED': 'EXPIRED', 'ASSIGNED': 'ASSIGNED',
    'EXERCISED': 'EXERCISED', 'CASH_SETTLED': 'CASH_SETTLED',
  }
  return actionMap[cleanAction] || cleanAction
}

function getDisplayQuantity(position) {
  if (!position || typeof position.quantity === 'undefined') return 0
  const currentAction = (position.closing_action || position.opening_action || '').toUpperCase()
  const isSellAction = currentAction.includes('SELL') || currentAction.includes('STC') || currentAction.includes('STO')
  return isSellAction ? -Math.abs(position.quantity) : Math.abs(position.quantity)
}

// ==================== CREDIT/DEBIT HELPERS ====================
function getCreditDebitDivisor(order) {
  if (!order || !order.positions || order.positions.length === 0) return 0
  const normalizeAction = (action) => action ? action.replace('OrderAction.', '').toUpperCase() : ''
  const closingPositions = order.positions.filter(pos =>
    pos.closing_action && (pos.closing_action === 'BTC' || pos.closing_action === 'STC')
  )
  if (closingPositions.length > 0) {
    const qty = Math.abs(closingPositions[0].quantity || 0)
    if (qty > 0) return qty
  }
  const closingByAction = order.positions.filter(pos => {
    const n = normalizeAction(pos.opening_action)
    return (n === 'BTC' || n === 'BUY_TO_CLOSE' || n === 'STC' || n === 'SELL_TO_CLOSE') && pos.status === 'CLOSED'
  })
  if (closingByAction.length > 0) {
    const qty = Math.abs(closingByAction[0].quantity || 0)
    if (qty > 0) return qty
  }
  const openingPositions = order.positions.filter(pos => {
    const n = normalizeAction(pos.opening_action)
    return (n === 'BTO' || n === 'BUY_TO_OPEN' || n === 'STO' || n === 'SELL_TO_OPEN') && pos.status !== 'CLOSED'
  })
  if (openingPositions.length > 0) {
    const qty = Math.abs(openingPositions[0].quantity || 0)
    if (qty > 0) return qty
  }
  return Math.abs(order.positions[0].quantity || 0)
}

function calculateCreditDebit(order, orderType) {
  if (!order || order.order_type !== orderType || !order.positions || order.positions.length === 0) return null
  let divisor
  if (orderType === 'ROLLING') {
    const normalizeAction = (action) => action ? action.replace('OrderAction.', '').toUpperCase() : ''
    const openingPositions = order.positions.filter(pos => {
      const a = normalizeAction(pos.opening_action)
      return a === 'BTO' || a === 'BUY_TO_OPEN' || a === 'STO' || a === 'SELL_TO_OPEN'
    })
    divisor = openingPositions.length > 0
      ? Math.abs(openingPositions[0].quantity || 0)
      : getCreditDebitDivisor(order)
  } else {
    divisor = getCreditDebitDivisor(order)
  }
  if (divisor === 0) return null
  const perRatioAmount = Math.abs(order.total_pnl || 0) / divisor / 100
  return { amount: perRatioAmount, type: (order.total_pnl || 0) > 0 ? 'credit' : 'debit' }
}

function formatCreditDebit(order, orderType) {
  const d = calculateCreditDebit(order, orderType)
  return d ? `${d.amount.toFixed(2)} ${d.type}` : ''
}

// ==================== NOTES ====================
async function loadNotes() {
  try {
    const [notesResp, commentsResp] = await Promise.all([
      Auth.authFetch('/api/position-notes'),
      Auth.authFetch('/api/order-comments'),
    ])
    if (notesResp.ok) {
      const data = await notesResp.json()
      groupNotes.value = data.notes || {}
    }
    if (commentsResp.ok) {
      const data = await commentsResp.json()
      orderComments.value = data.comments || {}
    }
  } catch (error) {
    console.error('Error loading notes:', error)
  }
}

function getGroupNote(group) {
  return groupNotes.value['group_' + group.group_id] || ''
}

function updateGroupNote(group, value) {
  const key = 'group_' + group.group_id
  groupNotes.value[key] = value
  if (noteSaveTimers[key]) clearTimeout(noteSaveTimers[key])
  noteSaveTimers[key] = setTimeout(() => {
    Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: value }),
    }).then(res => {
      if (!res.ok) console.error(`Failed to save group note (HTTP ${res.status})`)
    }).catch(err => console.error('Error saving group note:', err))
    delete noteSaveTimers[key]
  }, 500)
}

function getOrderComment(orderId) {
  return orderComments.value[orderId] || ''
}

function updateOrderComment(orderId, value) {
  orderComments.value[orderId] = value
  const timerKey = 'order_' + orderId
  if (noteSaveTimers[timerKey]) clearTimeout(noteSaveTimers[timerKey])
  noteSaveTimers[timerKey] = setTimeout(() => {
    Auth.authFetch(`/api/order-comments/${encodeURIComponent(orderId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment: value }),
    }).then(res => {
      if (!res.ok) console.error(`Failed to save order comment (HTTP ${res.status})`)
    }).catch(err => console.error('Error saving order comment:', err))
    delete noteSaveTimers[timerKey]
  }, 500)
}

// ==================== TAGS ====================
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
    nextTick(() => {
      const input = document.getElementById('ledger-tag-input-' + groupId)
      if (input) input.focus()
    })
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
    if (!group.tags.find(t => t.id === tag.id)) group.tags.push(tag)
    await loadAvailableTags()
    tagSearch.value = ''
  } catch (e) { console.error('Error adding tag:', e) }
}

async function removeTagFromGroup(group, tagId, event) {
  if (event) event.stopPropagation()
  try {
    await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags/${tagId}`, { method: 'DELETE' })
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

function onGroupHeaderClick(group) {
  if (selectedLots.value.length > 0 && isEligibleTarget(group)) {
    moveLots(group.group_id)
  } else {
    group.expanded = !group.expanded
  }
}

function getSortLabel() {
  const map = {
    opening_date: 'Date', underlying: 'Symbol', strategy_label: 'Strategy',
    status: 'Status', closing_date: 'Closed', total_pnl: 'P&L',
  }
  return map[sortColumn.value] || sortColumn.value
}

function getClosingTypeBadgeClass(closingType, lotQuantity) {
  if ((closingType === 'MANUAL' || closingType === 'EXPIRATION') && lotQuantity < 0) {
    return 'bg-tv-green/20 text-tv-green border-tv-green/50'
  }
  if ((closingType === 'MANUAL' || closingType === 'EXPIRATION') && lotQuantity >= 0) {
    return 'bg-tv-red/20 text-tv-red border-tv-red/50'
  }
  if (closingType === 'ASSIGNMENT') return 'bg-orange-500/20 text-orange-400 border-orange-500/50'
  if (closingType === 'EXERCISE') return 'bg-purple-500/20 text-purple-400 border-purple-500/50'
  return 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
}

function getClosingTypeLabel(closingType, lotQuantity) {
  if (closingType === 'MANUAL') return lotQuantity < 0 ? 'BTC' : 'STC'
  if (closingType === 'EXPIRATION') return 'EXPIRED'
  return closingType
}

function sortPositions(positions) {
  return (positions || []).slice().sort((a, b) =>
    new Date(a.expiration || 0) - new Date(b.expiration || 0) || (a.strike || 0) - (b.strike || 0)
  )
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
             :class="link.href === '/ledger' ? 'text-tv-text bg-tv-border rounded-sm' : 'text-tv-muted hover:text-tv-text'">
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
    <div class="flex items-center gap-4"></div>

    <!-- Filters -->
    <div class="flex items-center gap-6 text-base">
      <!-- Symbol Filter -->
      <div class="relative">
        <input type="text"
               v-model="filterUnderlying"
               @focus="$event.target.select()"
               @keyup.enter="onSymbolFilterApply()"
               @blur="onSymbolFilterApply()"
               @input="filterUnderlying = filterUnderlying.toUpperCase()"
               placeholder="Symbol"
               class="bg-tv-bg border border-tv-border text-tv-text text-base px-3 py-2 w-28 uppercase placeholder:normal-case placeholder:text-tv-muted"
               :class="filterUnderlying ? 'pr-8' : ''">
        <button v-show="filterUnderlying"
                @click="clearSymbolFilter()"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>

      <!-- Time Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted">Time:</span>
        <select v-model="timePeriod" @change="applyFilters(); saveState()"
                class="bg-tv-bg border border-tv-border text-tv-text text-base px-3 py-2">
          <option value="today">Today</option>
          <option value="yesterday">Yesterday</option>
          <option value="7">7D</option>
          <option value="30">30D</option>
          <option value="60">60D</option>
          <option value="90">90D</option>
          <option value="all">All</option>
        </select>
      </div>

      <!-- Direction Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted">Direction:</span>
        <button @click="toggleFilter('direction', 'bullish')"
                :class="filterDirection.includes('bullish') ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Bullish
        </button>
        <button @click="toggleFilter('direction', 'bearish')"
                :class="filterDirection.includes('bearish') ? 'bg-tv-red/20 text-tv-red border-tv-red/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Bearish
        </button>
        <button @click="toggleFilter('direction', 'neutral')"
                :class="filterDirection.includes('neutral') ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Neutral
        </button>
      </div>

      <!-- Type Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted">Type:</span>
        <button @click="toggleFilter('type', 'credit')"
                :class="filterType.includes('credit') ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Credit
        </button>
        <button @click="toggleFilter('type', 'debit')"
                :class="filterType.includes('debit') ? 'bg-amber-500/20 text-amber-400 border-amber-500/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Debit
        </button>
      </div>

      <!-- Status Filter -->
      <div class="flex items-center gap-2">
        <label class="flex items-center gap-2 text-tv-muted">
          <input type="checkbox" v-model="showOpen" @change="applyFilters(); saveState()" class="w-4 h-4">
          <span class="text-tv-green text-sm">Open</span>
        </label>
        <label class="flex items-center gap-2 text-tv-muted">
          <input type="checkbox" v-model="showClosed" @change="applyFilters(); saveState()" class="w-4 h-4">
          <span class="text-tv-muted text-sm">Closed</span>
        </label>
      </div>

      <!-- Sort direction indicator -->
      <div class="flex items-center gap-1 text-tv-muted text-sm">
        <i class="fas fa-sort"></i>
        <span>{{ getSortLabel() }}</span>
        <span class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </div>
    </div>
  </div>

  <!-- Stats Bar -->
  <div class="bg-tv-panel/50 border-b border-tv-border px-4 py-2 flex items-center gap-8 text-base">
    <span class="text-tv-muted">
      Groups: <span class="text-tv-text">{{ filteredGroups.length }}</span>
    </span>
    <span class="text-tv-muted">
      Open: <span class="text-tv-green">{{ stats.openCount }}</span>
    </span>
    <span class="text-tv-muted">
      Closed: <span class="text-tv-text">{{ stats.closedCount }}</span>
    </span>
    <span class="text-tv-muted">
      Realized P&amp;L:
      <span :class="stats.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
        ${{ formatNumber(stats.totalPnl) }}
      </span>
    </span>
  </div>

  <!-- Loading State -->
  <div v-if="loading" class="flex items-center justify-center py-20">
    <div class="spinner mr-3"></div>
    <span class="text-tv-muted text-lg">Loading ledger data...</span>
  </div>

  <!-- Empty State -->
  <div v-else-if="filteredGroups.length === 0" class="text-center py-20">
    <i class="fas fa-book-open text-4xl text-tv-muted mb-4"></i>
    <p class="text-tv-muted text-lg">No position groups found.</p>
    <p class="text-tv-muted mt-2">Sync your data from the <a href="/positions" class="text-tv-blue hover:underline">Positions</a> page first.</p>
  </div>

  <!-- Group List -->
  <div v-else class="py-2">
    <!-- Column Headers -->
    <div class="flex items-center px-8 py-2 text-sm text-tv-muted border-b border-tv-border bg-tv-panel/50 sticky top-16 z-10">
      <span class="w-6"></span>
      <span class="w-8 mr-3"></span>
      <span class="w-20 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('underlying')">
        Symbol <span v-if="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
      <span class="w-40 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('strategy_label')">
        Strategy <span v-if="sortColumn === 'strategy_label'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
      <span class="w-20 mr-6 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('status')">
        Status <span v-if="sortColumn === 'status'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
      <span class="w-28 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('opening_date')">
        Opened <span v-if="sortColumn === 'opening_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
      <span class="w-28 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('closing_date')">
        Closed <span v-if="sortColumn === 'closing_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
      <span class="ml-auto cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortGroups('total_pnl')">
        Realized P&amp;L <span v-if="sortColumn === 'total_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}</span>
      </span>
    </div>

    <div class="px-4 pt-2">
      <div v-for="group in filteredGroups" :key="group.group_id" class="mb-2">
        <!-- Group Header Row -->
        <div @click="onGroupHeaderClick(group)"
             class="flex items-center px-4 py-3 bg-tv-panel cursor-pointer border border-tv-border rounded-sm transition-colors"
             :class="{
               'border-b-0 rounded-b-none': group.expanded,
               'hover:bg-tv-border/50': selectedLots.length === 0,
               'border-l-4 !border-l-tv-blue bg-tv-blue/10 hover:bg-tv-blue/20': selectedLots.length > 0 && isEligibleTarget(group),
               'opacity-40': selectedLots.length > 0 && isSourceGroup(group),
               'opacity-60': selectedLots.length > 0 && !isEligibleTarget(group) && !isSourceGroup(group)
             }">
          <!-- Expand icon -->
          <i class="fas fa-chevron-right w-6 text-tv-muted transition-transform duration-200"
             :class="group.expanded ? 'rotate-90' : ''"></i>

          <!-- Account badge -->
          <span class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mr-3"
                :class="getAccountBadgeClass(group.account_number)">
            {{ getAccountSymbol(group.account_number) }}
          </span>

          <!-- Underlying -->
          <span class="w-20 text-lg font-semibold text-tv-text">{{ group.underlying }}</span>

          <!-- Strategy Label (inline edit) -->
          <span class="w-40 relative" @click.stop>
            <template v-if="!group._editingStrategy">
              <span class="flex items-center gap-1.5 group/strat">
                <span class="text-tv-muted text-base truncate">{{ group.strategy_label || '\u2014' }}</span>
                <i class="fas fa-pencil-alt text-xs text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                   @click="group._editingStrategy = true"
                   title="Edit strategy label"></i>
                <i v-show="groupViewMode(group) === 'positions'"
                   class="fas fa-right-left text-xs text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                   :class="group._movingLots ? '!text-tv-blue' : ''"
                   @click="toggleGroupMoveMode(group)"
                   title="Move lots between groups"></i>
              </span>
            </template>
            <template v-else>
              <input type="text"
                     :value="group.strategy_label || ''"
                     @keyup.enter="updateGroupStrategy(group, $event.target.value); group._editingStrategy = false"
                     @blur="updateGroupStrategy(group, $event.target.value); group._editingStrategy = false"
                     @keyup.escape="group._editingStrategy = false"
                     @vue:mounted="({ el }) => { el.focus(); el.select() }"
                     class="w-36 bg-tv-bg border border-tv-border text-tv-text text-base px-2 py-1 rounded"
                     placeholder="Strategy label">
            </template>
            <!-- Tag chips -->
            <div class="flex flex-wrap gap-1 mt-0.5 items-center">
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
                 @click.stop>
              <input type="text"
                     :id="'ledger-tag-input-' + group.group_id"
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
          </span>

          <!-- Status -->
          <span class="w-20 mr-6 text-sm px-2 py-0.5 rounded text-center"
                :class="group.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-muted/20 text-tv-muted'">
            {{ group.status }}
          </span>

          <!-- Opening date -->
          <span class="w-28 text-tv-muted text-base">{{ formatDate(group.opening_date) }}</span>

          <!-- Closing date -->
          <span class="w-28 text-tv-muted text-base">{{ group.closing_date ? formatDate(group.closing_date) : '\u2014' }}</span>

          <!-- Note indicator -->
          <i v-show="getGroupNote(group)" class="fas fa-sticky-note text-yellow-400 text-sm" title="Has notes"></i>

          <!-- P&L -->
          <span class="ml-auto text-base font-medium"
                :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'"
                v-show="group.realized_pnl">
            ${{ formatNumber(group.realized_pnl) }}
          </span>
        </div>

        <!-- Expanded Detail -->
        <div v-show="group.expanded"
             class="bg-tv-bg border border-tv-border border-t-0 rounded-b-sm px-2 py-2">

          <!-- Per-group view toggle -->
          <div class="flex justify-start px-4 pt-1 pb-1">
            <div class="flex items-center border border-tv-border rounded overflow-hidden text-xs">
              <button @click.stop="group._viewMode = 'positions'"
                      :class="groupViewMode(group) === 'positions' ? 'bg-tv-blue text-white' : 'bg-tv-bg text-tv-muted hover:text-tv-text'"
                      class="px-2 py-1 transition-colors">
                <i class="fas fa-layer-group mr-1"></i>Positions
              </button>
              <button @click.stop="group._viewMode = 'actions'; if (group._movingLots) { clearAllMoveMode() }"
                      :class="groupViewMode(group) === 'actions' ? 'bg-tv-blue text-white' : 'bg-tv-bg text-tv-muted hover:text-tv-text'"
                      class="px-2 py-1 transition-colors">
                <i class="fas fa-list-ol mr-1"></i>Orders
              </button>
            </div>
          </div>

          <!-- Group Notes -->
          <div class="px-4 pb-2">
            <textarea :value="getGroupNote(group)"
                      @input="updateGroupNote(group, $event.target.value)"
                      @click.stop rows="1"
                      class="w-full bg-transparent text-tv-text text-sm border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                      placeholder="Add notes..."></textarea>
          </div>

          <!-- Position View -->
          <template v-if="groupViewMode(group) === 'positions'">
            <div>
              <!-- Lots Table Header -->
              <div class="flex items-center text-sm text-tv-muted px-4 py-2 border-b border-tv-border/30 font-mono">
                <span class="w-5"></span>
                <span v-show="group._movingLots" class="w-8"></span>
                <span class="w-32">Entry Date</span>
                <span class="w-10 text-right">Qty</span>
                <span class="w-16 text-center mx-2">Exp</span>
                <span class="w-10">DTE</span>
                <span class="w-16 text-center mx-2">Strike</span>
                <span class="w-10">Type</span>
                <span class="w-20 text-center ml-3">Status</span>
                <span class="w-20 text-right">Entry $</span>
                <span class="w-24 text-right ml-2">Cost Basis</span>
                <span class="w-24 text-right ml-4">Realized</span>
              </div>

              <!-- Section A: Equity Aggregate -->
              <template v-if="openEquityLots(group).length > 0">
                <div>
                  <!-- Aggregate summary row -->
                  <div @click="group._eqExpanded = !group._eqExpanded"
                       class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono cursor-pointer"
                       :class="group._eqExpanded ? 'bg-tv-panel/30' : ''">
                    <i class="fas fa-chevron-right w-5 text-tv-muted text-xs transition-transform duration-200"
                       :class="group._eqExpanded ? 'rotate-90' : ''"></i>
                    <span v-if="group._movingLots" class="w-8">
                      <input type="checkbox"
                             :checked="openEquityLots(group).every(l => selectedLots.includes(l.transaction_id))"
                             @click.stop="toggleAllEquityLots(group); if (!group._eqExpanded) group._eqExpanded = true"
                             class="w-4 h-4">
                    </span>
                    <span class="w-32 text-tv-muted">{{ equityAggregate(group).lotCount }} lots</span>
                    <span class="w-10 text-right font-medium"
                          :class="equityAggregate(group).quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
                      {{ equityAggregate(group).quantity }}
                    </span>
                    <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">Shares</span>
                    <span class="w-10 text-tv-muted">&mdash;</span>
                    <span class="w-16 text-center mx-2 py-0.5 rounded text-tv-muted">&mdash;</span>
                    <span class="w-10 text-tv-muted">Stk</span>
                    <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3 bg-tv-green/20 text-tv-green border-tv-green/50">OPEN</span>
                    <span class="w-20 text-right text-tv-muted">${{ formatNumber(equityAggregate(group).avgPrice) }}</span>
                    <span class="w-24 text-right text-tv-muted ml-2">${{ formatNumber(equityAggregate(group).costBasis) }}</span>
                    <span class="w-24 text-right ml-4"></span>
                  </div>

                  <!-- Expanded individual equity lots -->
                  <div v-show="group._eqExpanded">
                    <div v-for="lot in openEquityLots(group)" :key="lot.lot_id">
                      <div @click="toggleLotExpand(lot)"
                           class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono cursor-pointer border-l-2 border-tv-blue/30"
                           :class="lot._expanded ? 'bg-tv-panel/30' : ''">
                        <i class="fas fa-chevron-right w-5 text-tv-muted text-xs transition-transform duration-200"
                           :class="lot._expanded ? 'rotate-90' : ''"></i>
                        <span v-if="group._movingLots" class="w-8">
                          <input type="checkbox"
                                 :checked="selectedLots.includes(lot.transaction_id)"
                                 @click.stop="toggleLotSelection(lot.transaction_id)"
                                 class="w-4 h-4">
                        </span>
                        <span class="w-32 text-tv-muted">
                          <span v-if="lot.derivation_type" class="text-tv-muted mr-1">&#8627;</span>
                          {{ formatOrderDate(lot.entry_date) }}
                        </span>
                        <span class="w-10 text-right font-medium"
                              :class="(lot.remaining_quantity ?? lot.quantity) > 0 ? 'text-tv-green' : 'text-tv-red'">
                          {{ lot.remaining_quantity ?? lot.quantity }}
                        </span>
                        <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">Shares</span>
                        <span class="w-10 text-tv-muted">&mdash;</span>
                        <span class="w-16 text-center mx-2 py-0.5 rounded text-tv-muted">&mdash;</span>
                        <span class="w-10 text-tv-muted">Stk</span>
                        <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3 bg-tv-green/20 text-tv-green border-tv-green/50">{{ lot.status }}</span>
                        <span class="w-20 text-right text-tv-muted">{{ lot.entry_price ? '$' + formatNumber(lot.entry_price) : '' }}</span>
                        <span class="w-24 text-right text-tv-muted ml-2">{{ lot.cost_basis ? '$' + formatNumber(lot.cost_basis) : '' }}</span>
                        <span class="w-24 text-right ml-4"
                              :class="lot.realized_pnl > 0 ? 'text-tv-green' : lot.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'">
                          {{ lot.realized_pnl ? '$' + formatNumber(lot.realized_pnl) : '' }}
                        </span>
                      </div>

                      <!-- Expanded Events (opening + closings) -->
                      <div v-show="lot._expanded" class="border-l-2 border-tv-blue/30">
                        <div class="flex items-center text-sm px-4 py-1 text-tv-muted font-mono border-l-2 border-tv-border/30">
                          <span class="w-5"></span>
                          <span v-show="group._movingLots" class="w-8"></span>
                          <span class="w-8"></span>
                          <span class="w-24">{{ formatOrderDate(lot.entry_date) }}</span>
                          <span class="w-10 text-right" :class="lot.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
                            {{ (lot.quantity > 0 ? '+' : '') + lot.quantity }}
                          </span>
                          <span class="w-16 text-center mx-2"></span>
                          <span class="w-10"></span>
                          <span class="w-16 text-center mx-2"></span>
                          <span class="w-10"></span>
                          <span class="w-20 text-center text-xs px-1 py-0.5 rounded border ml-3"
                                :class="lot.quantity > 0 ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-red/20 text-tv-red border-tv-red/50'">
                            {{ lot.quantity > 0 ? 'BTO' : 'STO' }}
                          </span>
                          <span class="w-20 text-right">{{ lot.entry_price ? '$' + formatNumber(lot.entry_price) : '' }}</span>
                          <span class="w-24 text-right ml-2 whitespace-nowrap"
                                :class="lot.quantity < 0 ? 'text-tv-green' : 'text-tv-red'">
                            {{ lot.cost_basis ? ('$' + formatNumber(lot.cost_basis) + (lot.quantity < 0 ? ' cr' : ' db')) : '' }}
                          </span>
                          <span class="w-24 ml-4"></span>
                        </div>
                        <div v-for="closing in (lot.closings || [])" :key="closing.closing_id"
                             class="flex items-center text-sm px-4 py-1 text-tv-muted font-mono border-l-2 border-tv-border/30">
                          <span class="w-5"></span>
                          <span v-show="group._movingLots" class="w-8"></span>
                          <span class="w-8"></span>
                          <span class="w-24">{{ formatOrderDate(closing.closing_date) }}</span>
                          <span class="w-10 text-right" :class="lot.quantity < 0 ? 'text-tv-green' : 'text-tv-red'">
                            {{ (lot.quantity < 0 ? '+' : '-') + closing.quantity_closed }}
                          </span>
                          <span class="w-16 text-center mx-2"></span>
                          <span class="w-10"></span>
                          <span class="w-16 text-center mx-2"></span>
                          <span class="w-10"></span>
                          <span class="w-20 text-center text-xs px-1 py-0.5 rounded border ml-3"
                                :class="getClosingTypeBadgeClass(closing.closing_type, lot.quantity)">
                            {{ getClosingTypeLabel(closing.closing_type, lot.quantity) }}
                          </span>
                          <span class="w-20 text-right">{{ closing.closing_price ? '$' + formatNumber(closing.closing_price) : '' }}</span>
                          <span class="w-24 text-right ml-2 whitespace-nowrap"
                                :class="lot.quantity < 0 ? 'text-tv-red' : 'text-tv-green'">
                            {{ closing.closing_price ? ('$' + formatNumber(closing.quantity_closed * closing.closing_price * (lot.option_type ? 100 : 1)) + (lot.quantity < 0 ? ' db' : ' cr')) : '' }}
                          </span>
                          <span class="w-24 ml-4"></span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>

              <!-- Separator between equity aggregate and option/closed lots -->
              <div v-if="openEquityLots(group).length > 0 && sortedOptionLots(group).length > 0"
                   class="border-t border-tv-muted/20 my-2 mx-4"></div>

              <!-- Section B: Option lots + closed equity lots -->
              <template v-for="(lot, lotIdx) in sortedOptionLots(group)" :key="lot.lot_id">
                <div>
                  <!-- Separator between open and closed -->
                  <div v-if="lotIdx > 0 && lot.status === 'CLOSED' && sortedOptionLots(group)[lotIdx - 1].status !== 'CLOSED'"
                       class="border-t border-tv-muted/40 my-3 mx-4"></div>
                  <div @click="toggleLotExpand(lot)"
                       class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono cursor-pointer"
                       :class="lot._expanded ? 'bg-tv-panel/30' : ''">
                    <i class="fas fa-chevron-right w-5 text-tv-muted text-xs transition-transform duration-200"
                       :class="lot._expanded ? 'rotate-90' : ''"></i>
                    <span v-if="group._movingLots" class="w-8">
                      <input type="checkbox"
                             :checked="selectedLots.includes(lot.transaction_id)"
                             @click.stop="toggleLotSelection(lot.transaction_id)"
                             class="w-4 h-4">
                    </span>
                    <span class="w-32 text-tv-muted">
                      <span v-if="lot.derivation_type" class="text-tv-muted mr-1">&#8627;</span>
                      {{ formatOrderDate(lot.entry_date) }}
                    </span>
                    <span class="w-10 text-right font-medium"
                          :class="(lot.remaining_quantity ?? lot.quantity) > 0 ? 'text-tv-green' : (lot.remaining_quantity ?? lot.quantity) < 0 ? 'text-tv-red' : 'text-tv-muted'">
                      {{ lot.remaining_quantity ?? lot.quantity }}
                    </span>
                    <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">
                      {{ lot.expiration ? formatExpirationShort(lot.expiration) : (lot.instrument_type === 'EQUITY' ? 'Shares' : '\u2014') }}
                    </span>
                    <span class="w-10 text-tv-muted"
                          :class="lot.expiration && calculateDTE(lot.expiration) <= 21 ? 'text-amber-400 font-bold' : ''">
                      {{ lot.expiration ? calculateDTE(lot.expiration) + 'd' : '\u2014' }}
                    </span>
                    <span class="w-16 text-center mx-2 py-0.5 rounded"
                          :class="lot.strike ? 'bg-tv-panel text-tv-text' : 'text-tv-muted'">
                      {{ lot.strike || '\u2014' }}
                    </span>
                    <span class="w-10 text-tv-muted">
                      {{ lot.option_type ? (lot.option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put') : (lot.instrument_type === 'EQUITY' ? 'Stk' : '\u2014') }}
                    </span>
                    <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3"
                          :class="lot.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : lot.status === 'PARTIAL' ? 'bg-amber-500/20 text-amber-400 border-amber-500/50' : 'bg-tv-muted/20 text-tv-muted border-tv-red/50'">
                      {{ lot.status }}
                    </span>
                    <span class="w-20 text-right text-tv-muted">{{ lot.entry_price ? '$' + formatNumber(lot.entry_price) : '' }}</span>
                    <span class="w-24 text-right text-tv-muted ml-2">{{ lot.status === 'CLOSED' ? '' : (lot.cost_basis ? '$' + formatNumber(lot.cost_basis) : '') }}</span>
                    <span class="w-24 text-right ml-4"
                          :class="lot.realized_pnl > 0 ? 'text-tv-green' : lot.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'">
                      {{ lot.realized_pnl ? '$' + formatNumber(lot.realized_pnl) : '' }}
                    </span>
                  </div>

                  <!-- Expanded Events -->
                  <div v-show="lot._expanded">
                    <div class="flex items-center text-sm px-4 py-1 text-tv-muted font-mono border-l-2 border-tv-border/30">
                      <span class="w-5"></span>
                      <span v-show="group._movingLots" class="w-8"></span>
                      <span class="w-8"></span>
                      <span class="w-24">{{ formatOrderDate(lot.entry_date) }}</span>
                      <span class="w-10 text-right" :class="lot.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
                        {{ (lot.quantity > 0 ? '+' : '') + lot.quantity }}
                      </span>
                      <span class="w-16 text-center mx-2"></span>
                      <span class="w-10"></span>
                      <span class="w-16 text-center mx-2"></span>
                      <span class="w-10"></span>
                      <span class="w-20 text-center text-xs px-1 py-0.5 rounded border ml-3"
                            :class="lot.quantity > 0 ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-red/20 text-tv-red border-tv-red/50'">
                        {{ lot.quantity > 0 ? 'BTO' : 'STO' }}
                      </span>
                      <span class="w-20 text-right">{{ lot.entry_price ? '$' + formatNumber(lot.entry_price) : '' }}</span>
                      <span class="w-24 text-right ml-2 whitespace-nowrap"
                            :class="lot.quantity < 0 ? 'text-tv-green' : 'text-tv-red'">
                        {{ lot.cost_basis ? ('$' + formatNumber(lot.cost_basis) + (lot.quantity < 0 ? ' cr' : ' db')) : '' }}
                      </span>
                      <span class="w-24 ml-4"></span>
                    </div>
                    <div v-for="closing in (lot.closings || [])" :key="closing.closing_id"
                         class="flex items-center text-sm px-4 py-1 text-tv-muted font-mono border-l-2 border-tv-border/30">
                      <span class="w-5"></span>
                      <span v-show="group._movingLots" class="w-8"></span>
                      <span class="w-8"></span>
                      <span class="w-24">{{ formatOrderDate(closing.closing_date) }}</span>
                      <span class="w-10 text-right" :class="lot.quantity < 0 ? 'text-tv-green' : 'text-tv-red'">
                        {{ (lot.quantity < 0 ? '+' : '-') + closing.quantity_closed }}
                      </span>
                      <span class="w-16 text-center mx-2"></span>
                      <span class="w-10"></span>
                      <span class="w-16 text-center mx-2"></span>
                      <span class="w-10"></span>
                      <span class="w-20 text-center text-xs px-1 py-0.5 rounded border ml-3"
                            :class="getClosingTypeBadgeClass(closing.closing_type, lot.quantity)">
                        {{ getClosingTypeLabel(closing.closing_type, lot.quantity) }}
                      </span>
                      <span class="w-20 text-right">{{ closing.closing_price ? '$' + formatNumber(closing.closing_price) : '' }}</span>
                      <span class="w-24 text-right ml-2 whitespace-nowrap"
                            :class="lot.quantity < 0 ? 'text-tv-red' : 'text-tv-green'">
                        {{ closing.closing_price ? ('$' + formatNumber(closing.quantity_closed * closing.closing_price * (lot.option_type ? 100 : 1)) + (lot.quantity < 0 ? ' db' : ' cr')) : '' }}
                      </span>
                      <span class="w-24 ml-4"></span>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </template>

          <!-- Action View -->
          <template v-if="groupViewMode(group) === 'actions'">
            <div>
              <div v-for="(order, index) in (group.orders || []).filter(o => o != null)" :key="`${group.group_id}_order_${index}`"
                   class="mx-2 my-3 p-3 bg-tv-panel rounded border border-tv-border">
                <!-- Order Header -->
                <div class="flex items-center text-base">
                  <span class="w-8 text-tv-muted">{{ (group.orders || []).length - index }}</span>
                  <span class="w-32 text-tv-muted">{{ formatOrderDate(order.order_date) }}</span>
                  <span class="w-28 text-amber-400">{{ order.display_type || order.order_type }}</span>
                  <!-- Credit/Debit badges -->
                  <span v-if="order.order_type === 'ROLLING' && formatCreditDebit(order, 'ROLLING')"
                        class="text-base px-3 py-1 rounded-sm"
                        :class="calculateCreditDebit(order, 'ROLLING')?.type === 'credit' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-red/20 text-tv-red'">
                    {{ formatCreditDebit(order, 'ROLLING') }}
                  </span>
                  <span v-else-if="order.order_type === 'OPENING' && formatCreditDebit(order, 'OPENING')"
                        class="text-base px-3 py-1 rounded-sm"
                        :class="calculateCreditDebit(order, 'OPENING')?.type === 'credit' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-red/20 text-tv-red'">
                    {{ formatCreditDebit(order, 'OPENING') }}
                  </span>
                  <span v-else-if="order.order_type === 'CLOSING' && formatCreditDebit(order, 'CLOSING')"
                        class="text-base px-3 py-1 rounded-sm"
                        :class="calculateCreditDebit(order, 'CLOSING')?.type === 'credit' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-red/20 text-tv-red'">
                    {{ formatCreditDebit(order, 'CLOSING') }}
                  </span>
                  <!-- Order ID -->
                  <span v-if="order.order_id && !order.order_id.startsWith('SYSTEM_')"
                        class="ml-4 text-sm font-mono text-tv-muted">
                    Order# <span class="text-tv-text">{{ order.order_id }}</span>
                  </span>
                  <span v-if="order.order_id && order.order_id.startsWith('SYSTEM_Expiration')"
                        class="ml-4 text-sm font-mono text-amber-400">
                    EXPIRATION
                  </span>
                  <!-- P&L -->
                  <span class="ml-auto font-medium"
                        :class="order.total_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                    ${{ formatNumber(order.total_pnl) }}
                  </span>
                </div>

                <!-- Order comment -->
                <div class="px-8 pt-1">
                  <input type="text"
                         :value="getOrderComment(order.order_id)"
                         @input="updateOrderComment(order.order_id, $event.target.value)"
                         @click.stop
                         class="w-full bg-transparent text-tv-muted text-xs border-b border-transparent hover:border-tv-border/30 focus:border-tv-blue/50 outline-none px-0 py-0.5"
                         placeholder="Add notes...">
                </div>

                <!-- Positions table -->
                <div v-if="order.positions && order.positions.length > 0" class="pt-3 space-y-1 font-mono">
                  <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                    <span class="w-10 text-right">Qty</span>
                    <span class="w-16 text-center mx-2">Exp</span>
                    <span class="w-10">DTE</span>
                    <span class="w-16 text-center mx-2">Strike</span>
                    <span class="w-6">Type</span>
                    <span class="w-12 ml-4">Action</span>
                    <span class="w-20 text-right ml-auto">Price</span>
                    <span class="w-24 text-right">Realized</span>
                  </div>
                  <div v-for="position in sortPositions(order.positions)" :key="`pos_${position.position_id || Math.random()}`">
                    <div class="flex items-center text-sm">
                      <span class="w-10 text-right font-medium"
                            :class="getDisplayQuantity(position) > 0 ? 'text-tv-green' : 'text-tv-red'">
                        {{ getDisplayQuantity(position) }}
                      </span>
                      <span class="w-16 text-center bg-tv-bg mx-2 py-0.5 rounded text-tv-text">
                        {{ formatExpirationShort(position.expiration) }}
                      </span>
                      <span class="w-10 text-tv-muted">{{ calculateDTE(position.expiration) }}d</span>
                      <span class="w-16 text-center bg-tv-bg mx-2 py-0.5 rounded text-tv-text">{{ position.strike }}</span>
                      <span class="w-6 text-tv-muted">{{ (position.option_type || '').toUpperCase().startsWith('C') ? 'C' : 'P' }}</span>
                      <span class="w-12 ml-4"
                            :class="order.order_id?.startsWith('SYSTEM_Expiration') ? 'text-amber-400' : position.opening_action?.includes('BUY') ? 'text-tv-green' : 'text-tv-red'">
                        {{ order.order_id?.startsWith('SYSTEM_Expiration') ? 'EXPIRED' : formatAction(position.opening_action) }}
                      </span>
                      <span class="w-20 text-right text-tv-muted ml-auto">${{ formatNumber(position.opening_price) }}</span>
                      <span class="w-24 text-right"
                            :class="position.pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                        ${{ formatNumber(position.pnl) }}
                      </span>
                      <span v-if="position.closing_action?.includes('EXPIRED')" class="text-amber-400 ml-2">EXP</span>
                      <span v-if="position.closing_action?.includes('ASSIGNED')" class="text-orange-400 ml-2">ASN</span>
                    </div>
                    <!-- Derived positions -->
                    <template v-if="position.derived_positions && position.derived_positions.length > 0">
                      <div v-for="derived in position.derived_positions" :key="`derived_${derived.lot_id}`"
                           class="flex items-center text-sm ml-6 mt-1">
                        <span class="text-tv-muted mr-2">&#8627;</span>
                        <span class="w-10 text-right font-medium"
                              :class="derived.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
                          {{ derived.quantity }}
                        </span>
                        <span class="w-20 text-center text-tv-text mx-2">{{ derived.symbol }}</span>
                        <span class="w-20 text-orange-400">{{ derived.derivation_type }}</span>
                        <span class="w-20 text-right text-tv-muted ml-auto">${{ formatNumber(derived.entry_price) }}</span>
                        <span class="w-24 text-right text-tv-muted">{{ derived.status }}</span>
                      </div>
                    </template>
                  </div>
                </div>
              </div>

              <!-- No orders message -->
              <div v-if="!group.orders || group.orders.length === 0"
                   class="text-center py-4 text-tv-muted text-sm">
                No orders found for this group
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>

  <!-- Floating Action Bar (Move Mode) -->
  <div v-show="selectedLots.length > 0"
       class="fixed bottom-0 left-0 right-0 bg-tv-panel border-t border-tv-border px-6 py-4 flex items-center justify-between z-50 shadow-lg">
    <span class="text-tv-text text-base">
      <span class="font-medium">{{ selectedLots.length }}</span> lot(s) selected
      <span class="text-tv-muted ml-2">&mdash; click a target group below</span>
    </span>
    <div class="flex items-center gap-3">
      <button @click="moveLots('__new__')"
              class="bg-tv-blue text-white px-5 py-2 text-base hover:bg-tv-blue/80 transition-colors">
        + New Group
      </button>
      <button @click="cancelMoveMode()"
              class="text-tv-muted hover:text-tv-text px-4 py-2 text-base border border-tv-border">
        Cancel
      </button>
    </div>
  </div>
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
</style>
