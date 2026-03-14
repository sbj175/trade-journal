<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { STRATEGY_CATEGORIES } from '@/lib/constants'
import { formatNumber, formatDate, formatExpirationShort } from '@/lib/formatters'
import DateFilter from '@/components/DateFilter.vue'
import RollChainModal from '@/components/RollChainModal.vue'

const Auth = useAuth()
const route = useRoute()

// ==================== STATE ====================
const groups = ref([])
const accounts = ref([])
const filteredGroups = ref([])
const selectedAccount = ref('')
const filterUnderlying = ref('')
const dateFrom = ref(null)  // ISO date string or null
const dateTo = ref(null)    // ISO date string or null
const showOpen = ref(true)
const showClosed = ref(true)
const filterRollsOnly = ref(false)
const rollChainModal = ref(null)  // group_id of active modal, or null
const sortColumn = ref('opening_date')
const sortDirection = ref('desc')
const loading = ref(true)
const stats = ref({ openCount: 0, closedCount: 0 })
const filterDirection = ref([])
const filterType = ref([])
const groupNotes = ref({})
const availableTags = ref([])
const tagPopoverGroup = ref(null)
const tagSearch = ref('')
const dateFilterRef = ref(null)
const filterStrategy = ref([])
const filterTagIds = ref([])
const strategyDropdownOpen = ref(false)
const tagDropdownOpen = ref(false)

// Internal (non-reactive)
const noteSaveTimers = {}

// Close filter dropdowns on outside click
function onDocumentClick(e) {
  if (strategyDropdownOpen.value && !e.target.closest('.strategy-dropdown-wrapper')) {
    strategyDropdownOpen.value = false
  }
  if (tagDropdownOpen.value && !e.target.closest('.tag-dropdown-wrapper')) {
    tagDropdownOpen.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

// ==================== COMPUTED ====================
const filteredTagSuggestions = computed(() => {
  const search = (tagSearch.value || '').toLowerCase()
  const group = groups.value.find(g => g.group_id === tagPopoverGroup.value)
  const appliedIds = (group?.tags || []).map(t => t.id)
  return availableTags.value
    .filter(t => !appliedIds.includes(t.id))
    .filter(t => !search || t.name.toLowerCase().includes(search))
})


const uniqueStrategies = computed(() => {
  const set = new Set()
  for (const g of groups.value) {
    if (g.strategy_label) set.add(g.strategy_label)
  }
  return [...set].sort()
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  await loadAccounts()

  // Restore state from localStorage
  const saved = localStorage.getItem('ledger_state')
  if (saved) {
    try {
      const state = JSON.parse(saved)
      showOpen.value = state.showOpen !== undefined ? state.showOpen : true
      showClosed.value = state.showClosed !== undefined ? state.showClosed : true
      sortColumn.value = state.sortColumn || 'opening_date'
      sortDirection.value = state.sortDirection || 'desc'
      filterDirection.value = state.filterDirection || []
      filterType.value = state.filterType || []
      filterStrategy.value = state.filterStrategy || []
      filterTagIds.value = state.filterTagIds || []
    } catch (e) {}
  }

  const savedAccount = localStorage.getItem('trade_journal_selected_account')
  if (savedAccount) selectedAccount.value = savedAccount

  // URL params override saved state (via vue-router query)
  const underlyingParam = route.query.underlying
  const groupParam = route.query.group
  if (underlyingParam) {
    filterUnderlying.value = underlyingParam.toUpperCase()
    showOpen.value = true
    showClosed.value = groupParam ? false : true
  } else {
    const savedUnderlying = localStorage.getItem('trade_journal_selected_underlying')
    if (savedUnderlying) filterUnderlying.value = savedUnderlying
  }

  await fetchLedger()
  await loadNotes()
  await loadAvailableTags()

  // Auto-expand and scroll to a specific group if linked from Positions page
  if (groupParam) {
    let target = filteredGroups.value.find(g => g.group_id === groupParam)
    // If target not visible, the date filter may be hiding it — clear and retry
    if (!target && (dateFrom.value || dateTo.value)) {
      if (dateFilterRef.value) dateFilterRef.value.clear()
      applyFilters()
      target = filteredGroups.value.find(g => g.group_id === groupParam)
    }
    if (target) {
      target.expanded = true
      await nextTick()
      const el = document.getElementById('group-' + groupParam)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
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
    groups.value = data.map(g => ({ ...g, expanded: false, _editingStrategy: false }))
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
    if (column === 'opening_date' || column === 'closing_date' || column === 'realized_pnl' || column === 'total_pnl') {
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

  if (filterStrategy.value.length > 0) {
    filtered = filtered.filter(g => filterStrategy.value.includes(g.strategy_label))
  }

  if (filterTagIds.value.length > 0) {
    filtered = filtered.filter(g =>
      (g.tags || []).some(t => filterTagIds.value.includes(t.id))
    )
  }

  if (filterRollsOnly.value) {
    filtered = filtered.filter(g => g.has_roll_chain)
  }

  if (!showOpen.value) filtered = filtered.filter(g => g.status !== 'OPEN')
  if (!showClosed.value) filtered = filtered.filter(g => g.status !== 'CLOSED')

  if (dateFrom.value || dateTo.value) {
    const from = dateFrom.value ? new Date(dateFrom.value + 'T00:00:00') : null
    const to = dateTo.value ? new Date(dateTo.value + 'T23:59:59') : null
    filtered = filtered.filter(g => {
      const opened = g.opening_date ? new Date(g.opening_date) : null
      const closed = g.closing_date ? new Date(g.closing_date) : null
      const inRange = (d) => {
        if (!d) return false
        if (from && d < from) return false
        if (to && d > to) return false
        return true
      }
      const lastActivity = g.last_activity_date ? new Date(g.last_activity_date) : null
      if (inRange(opened) || inRange(closed) || inRange(lastActivity)) return true
      // Check if any lot has activity (entry or closing) within the range
      return (g.lots || []).some(lot => {
        if (inRange(lot.entry_date ? new Date(lot.entry_date) : null)) return true
        return (lot.closings || []).some(c => inRange(c.closing_date ? new Date(c.closing_date) : null))
      })
    })
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
    } else if (col === 'initial_premium') {
      va = groupInitialPremium(a)
      vb = groupInitialPremium(b)
    } else if (col === 'realized_pnl') {
      va = a.realized_pnl || 0
      vb = b.realized_pnl || 0
    } else if (col === 'total_pnl') {
      va = a.total_pnl || 0
      vb = b.total_pnl || 0
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
  let openCount = 0, closedCount = 0
  for (const g of filteredGroups.value) {
    if (g.status === 'OPEN') openCount++
    else closedCount++
  }
  stats.value = { openCount, closedCount }
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

function toggleStrategyFilter(strategy) {
  const idx = filterStrategy.value.indexOf(strategy)
  if (idx >= 0) filterStrategy.value.splice(idx, 1)
  else filterStrategy.value.push(strategy)
  saveState()
  applyFilters()
}

function toggleTagFilter(tagId) {
  const idx = filterTagIds.value.indexOf(tagId)
  if (idx >= 0) filterTagIds.value.splice(idx, 1)
  else filterTagIds.value.push(tagId)
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

function onDateFilterUpdate({ from, to }) {
  dateFrom.value = from
  dateTo.value = to
  applyFilters()
}

function saveState() {
  localStorage.setItem('ledger_state', JSON.stringify({
    showOpen: showOpen.value,
    showClosed: showClosed.value,
    sortColumn: sortColumn.value,
    sortDirection: sortDirection.value,
    filterDirection: filterDirection.value,
    filterType: filterType.value,
    filterStrategy: filterStrategy.value,
    filterTagIds: filterTagIds.value,
  }))
}

// ==================== GROUP MANAGEMENT ====================
function sortedLots(group) {
  return (group.lots || []).slice().sort((a, b) => {
    const aOpen = a.status !== 'CLOSED' ? 0 : 1
    const bOpen = b.status !== 'CLOSED' ? 0 : 1
    if (aOpen !== bOpen) return aOpen - bOpen

    if (aOpen === 0) {
      // Open/partial: expiration asc, strike desc, entry date desc
      const aExp = a.expiration || ''
      const bExp = b.expiration || ''
      if (aExp !== bExp) return aExp.localeCompare(bExp)
      if ((a.strike || 0) !== (b.strike || 0)) return (b.strike || 0) - (a.strike || 0)
      return (b.entry_date || '').localeCompare(a.entry_date || '')
    }

    // Closed: expiration desc, strike desc, entry date desc
    const aExp = a.expiration || ''
    const bExp = b.expiration || ''
    if (aExp !== bExp) return bExp.localeCompare(aExp)
    if ((a.strike || 0) !== (b.strike || 0)) return (b.strike || 0) - (a.strike || 0)
    return (b.entry_date || '').localeCompare(a.entry_date || '')
  })
}

function sortedOptionLots(group) {
  return sortedLots(group).filter(l => l.instrument_type !== 'EQUITY' || l.status === 'CLOSED')
}

function groupedOptionLegs(group) {
  const lots = sortedOptionLots(group)
  const map = new Map()
  for (const lot of lots) {
    const key = `${lot.expiration || '_'}|${lot.strike || '_'}|${lot.option_type || '_'}|${lot.instrument_type || '_'}`
    if (!map.has(key)) {
      map.set(key, {
        key,
        expiration: lot.expiration,
        strike: lot.strike,
        option_type: lot.option_type,
        instrument_type: lot.instrument_type,
        status: 'CLOSED',
        totalQuantity: 0,
        totalCostBasis: 0,
        totalProceeds: 0,
        totalRealized: 0,
        entryDate: null,
        closeDate: null,
        lotCount: 0,
        lots: [],
      })
    }
    const agg = map.get(key)
    const qty = lot.status !== 'CLOSED' ? (lot.remaining_quantity ?? lot.quantity) : lot.quantity
    agg.totalQuantity += qty
    agg.totalCostBasis += lot.cost_basis || 0
    const closeSummary = lotCloseSummary(lot)
    if (closeSummary) agg.totalProceeds += closeSummary.proceeds
    agg.totalRealized += lot.realized_pnl || 0
    if (!agg.entryDate || (lot.entry_date && lot.entry_date < agg.entryDate)) {
      agg.entryDate = lot.entry_date
    }
    const cd = lotCloseDate(lot)
    if (cd && (!agg.closeDate || cd > agg.closeDate)) {
      agg.closeDate = cd
    }
    if (lot.status !== 'CLOSED') agg.status = 'OPEN'
    const closings = lot.closings || []
    if (closings.length > 0 && closings.every(c => c.closing_type === 'EXPIRATION')) {
      agg._hasExpiration = true
    } else if (closings.length > 0) {
      agg._hasNonExpiration = true
    }
    agg.lotCount++
    agg.lots.push(lot)
  }

  const result = [...map.values()]
  // Compute derived fields
  for (const leg of result) {
    const multiplier = leg.option_type ? 100 : 1
    const originalQty = Math.abs(leg.lots.reduce((s, l) => s + l.quantity, 0))
    leg.avgEntryPrice = originalQty > 0 ? Math.abs(leg.totalCostBasis) / originalQty / multiplier : 0
    leg.expired = leg._hasExpiration && !leg._hasNonExpiration
    // Weighted avg close price
    if (leg.totalProceeds && leg.status === 'CLOSED') {
      const closedQty = Math.abs(leg.lots.reduce((s, l) => s + l.quantity, 0))
      leg.avgClosePrice = closedQty > 0 ? Math.abs(leg.totalProceeds) / closedQty / multiplier : 0
    } else {
      leg.avgClosePrice = null
    }
  }

  // Sort: open before closed, then highest strike first within same expiration
  result.sort((a, b) => {
    const aOpen = a.status !== 'CLOSED' ? 0 : 1
    const bOpen = b.status !== 'CLOSED' ? 0 : 1
    if (aOpen !== bOpen) return aOpen - bOpen
    const aExp = a.expiration || ''
    const bExp = b.expiration || ''
    if (aOpen === 0) {
      if (aExp !== bExp) return aExp.localeCompare(bExp)
      return (b.strike || 0) - (a.strike || 0)
    }
    if (aExp !== bExp) return bExp.localeCompare(aExp)
    return (b.strike || 0) - (a.strike || 0)
  })

  return result
}

function groupInitialPremium(group) {
  return (group.lots || []).reduce((s, l) => s + (l.cost_basis || 0), 0)
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

function lotCloseDate(lot) {
  const closings = lot.closings || []
  if (closings.length === 0) return null
  return closings.reduce((latest, c) =>
    !latest || (c.closing_date > latest) ? c.closing_date : latest, null)
}

function lotCloseSummary(lot) {
  const closings = lot.closings || []
  if (closings.length === 0) return null
  const multiplier = lot.option_type ? 100 : 1
  let totalQty = 0, totalValue = 0
  for (const c of closings) {
    totalQty += c.quantity_closed
    totalValue += c.quantity_closed * (c.closing_price || 0) * multiplier
  }
  return {
    avgPrice: totalQty > 0 ? totalValue / totalQty / multiplier : 0,
    proceeds: totalValue,
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
  if (symbol === 'R') return 'bg-tv-purple/20 text-tv-purple'
  if (symbol === 'I') return 'bg-tv-blue/20 text-tv-blue'
  if (symbol === 'T') return 'bg-tv-green/20 text-tv-green'
  return 'bg-tv-border text-tv-muted'
}

// ==================== NOTES ====================
async function loadNotes() {
  try {
    const resp = await Auth.authFetch('/api/position-notes')
    if (resp.ok) {
      const data = await resp.json()
      groupNotes.value = data.notes || {}
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

// ==================== ROLL CHAIN ====================
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
  group.expanded = !group.expanded
}

function getSortLabel() {
  const map = {
    opening_date: 'Date', underlying: 'Symbol', strategy_label: 'Strategy',
    status: 'Status', closing_date: 'Closed', total_pnl: 'P&L',
  }
  return map[sortColumn.value] || sortColumn.value
}


</script>

<template>
  <Teleport to="#nav-right">
    <select v-model="selectedAccount" @change="onAccountChange()"
            class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded">
      <option value="">All Accounts</option>
      <option v-for="account in accounts" :key="account.account_number"
              :value="account.account_number">
        ({{ getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
      </option>
    </select>
  </Teleport>

  <!-- Sticky header block (filters + stats + column headers) -->
  <div class="sticky top-14 z-30">

  <!-- Filter Bar -->
  <div class="bg-tv-panel border-b border-tv-border">
    <!-- Row 1: Symbol + Date -->
    <div class="px-4 py-2.5 flex items-center gap-5 border-b border-tv-border/50">
      <!-- Symbol Filter -->
      <div class="relative">
        <input type="text"
               v-model="filterUnderlying"
               @focus="$event.target.select()"
               @keyup.enter="onSymbolFilterApply()"
               @blur="onSymbolFilterApply()"
               @input="filterUnderlying = filterUnderlying.toUpperCase(); onSymbolFilterApply()"
               placeholder="Symbol"
               class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 w-28 uppercase placeholder:normal-case placeholder:text-tv-muted"
               :class="filterUnderlying ? 'pr-8' : ''">
        <button v-show="filterUnderlying"
                @click="clearSymbolFilter()"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>

      <!-- Date Filter -->
      <DateFilter ref="dateFilterRef" storage-key="ledger_dateFilter" default-preset="Last 30 Days" @update="onDateFilterUpdate" />
    </div>

    <!-- Row 2: Direction, Type, Status, Sort -->
    <div class="px-4 py-2.5 flex items-center gap-6">
      <!-- Direction Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted text-sm">Direction:</span>
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

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Type Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted text-sm">Type:</span>
        <button @click="toggleFilter('type', 'credit')"
                :class="filterType.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Credit
        </button>
        <button @click="toggleFilter('type', 'debit')"
                :class="filterType.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Debit
        </button>
      </div>

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Status Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted text-sm">Status:</span>
        <button @click="showOpen = !showOpen; applyFilters(); saveState()"
                :class="showOpen ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Open
        </button>
        <button @click="showClosed = !showClosed; applyFilters(); saveState()"
                :class="showClosed ? 'bg-tv-muted/20 text-tv-text border-tv-muted/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors">
          Closed
        </button>
      </div>

      <!-- Rolls Filter -->
      <button @click="filterRollsOnly = !filterRollsOnly; applyFilters()"
              :class="filterRollsOnly ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
              class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5">
        <i class="fas fa-link text-xs"></i>
        Rolls
      </button>

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Strategy Filter Dropdown -->
      <div class="relative strategy-dropdown-wrapper">
        <button @click="strategyDropdownOpen = !strategyDropdownOpen; tagDropdownOpen = false"
                class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                :class="filterStrategy.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
          Strategy
          <span v-if="filterStrategy.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ filterStrategy.length }}</span>
          <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
        </button>
        <div v-if="strategyDropdownOpen"
             class="absolute top-full left-0 mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-50 py-1 min-w-[200px] max-h-64 overflow-y-auto">
          <button v-if="filterStrategy.length"
                  @click="filterStrategy = []; saveState(); applyFilters()"
                  class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
            Clear all
          </button>
          <button v-for="s in uniqueStrategies" :key="s"
                  @click="toggleStrategyFilter(s)"
                  class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
            <i class="fas text-[10px]" :class="filterStrategy.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
            <span :class="filterStrategy.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
          </button>
          <div v-if="uniqueStrategies.length === 0" class="px-3 py-2 text-sm text-tv-muted">No strategies</div>
        </div>
      </div>

      <!-- Tag Filter Dropdown -->
      <div v-if="availableTags.length" class="relative tag-dropdown-wrapper">
        <button @click="tagDropdownOpen = !tagDropdownOpen; strategyDropdownOpen = false"
                class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                :class="filterTagIds.length ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
          Tags
          <span v-if="filterTagIds.length" class="bg-tv-purple text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ filterTagIds.length }}</span>
          <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
        </button>
        <div v-if="tagDropdownOpen"
             class="absolute top-full left-0 mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-50 py-1 min-w-[180px] max-h-64 overflow-y-auto">
          <button v-if="filterTagIds.length"
                  @click="filterTagIds = []; saveState(); applyFilters()"
                  class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
            Clear all
          </button>
          <button v-for="tag in availableTags" :key="tag.id"
                  @click="toggleTagFilter(tag.id)"
                  class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
            <i class="fas text-[10px]" :class="filterTagIds.includes(tag.id) ? 'fa-check-square text-tv-purple' : 'fa-square text-tv-muted'"></i>
            <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: tag.color || '#6b7280' }"></span>
            <span :class="filterTagIds.includes(tag.id) ? 'text-tv-text' : 'text-tv-muted'">{{ tag.name }}</span>
          </button>
        </div>
      </div>

    </div>
  </div>

  <!-- Stats Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center gap-8 text-base">
    <span class="text-tv-muted">
      Groups: <span class="text-tv-text">{{ filteredGroups.length }}</span>
    </span>
    <span class="text-tv-muted">
      Open: <span class="text-tv-green">{{ stats.openCount }}</span>
    </span>
    <span class="text-tv-muted">
      Closed: <span class="text-tv-text">{{ stats.closedCount }}</span>
    </span>
  </div>

  <!-- Column Headers -->
  <div v-if="!loading && filteredGroups.length > 0"
       class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <span class="w-6"></span>
    <span class="w-8 mr-4"></span>
    <span class="w-24 mr-4 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('underlying')">
      Symbol <span v-if="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-48 mr-4 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('strategy_label')">
      Strategy <span v-if="sortColumn === 'strategy_label'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-20 mr-6 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('status')">
      Status <span v-if="sortColumn === 'status'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-32 mr-2 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('opening_date')">
      Opened <span v-if="sortColumn === 'opening_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-32 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortGroups('closing_date')">
      Closed <span v-if="sortColumn === 'closing_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-10 text-center">Rolls</span>
    <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-auto whitespace-nowrap" @click="sortGroups('initial_premium')">
      Initial Premium <span v-if="sortColumn === 'initial_premium'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
    <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sortGroups('realized_pnl')">
      Realized P&amp;L <span v-if="sortColumn === 'realized_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
  </div>

  </div><!-- /sticky header block -->

  <!-- Loading State -->
  <div v-if="loading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading ledger data...</p>
  </div>

  <!-- Empty State -->
  <div v-else-if="filteredGroups.length === 0" class="text-center py-16">
    <i class="fas fa-book-open text-3xl text-tv-muted mb-3"></i>
    <p class="text-tv-muted">No position groups found.</p>
    <p class="text-tv-muted mt-2">Sync your data from the <router-link to="/positions" class="text-tv-blue hover:underline">Positions</router-link> page first.</p>
  </div>

  <!-- Group List -->
  <div v-else class="bg-tv-panel border-x border-b border-tv-border">
    <div class="divide-y divide-tv-border">
      <div v-for="group in filteredGroups" :key="group.group_id" :id="'group-' + group.group_id">
        <!-- Group Header Row -->
        <div @click="onGroupHeaderClick(group)"
             class="flex items-center px-4 h-12 cursor-pointer transition-colors hover:bg-tv-border/20">
          <!-- Expand icon -->
          <i class="fas fa-chevron-right w-6 text-tv-muted transition-transform duration-200"
             :class="group.expanded ? 'rotate-90' : ''"></i>

          <!-- Account badge -->
          <span class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mr-4"
                :class="getAccountBadgeClass(group.account_number)">
            {{ getAccountSymbol(group.account_number) }}
          </span>

          <!-- Underlying -->
          <span class="w-24 mr-4 text-lg font-semibold text-tv-text">{{ group.underlying }}</span>

          <!-- Strategy Label (inline edit) -->
          <span class="w-48 mr-4 relative" @click.stop>
            <template v-if="!group._editingStrategy">
              <span class="flex items-center group/strat">
                <span class="text-tv-muted text-base truncate flex-1 min-w-0">{{ group.strategy_label || '\u2014' }}</span>
                <span class="flex items-center gap-1.5 ml-1.5 flex-shrink-0">
                  <i class="fas fa-pencil-alt text-xs text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                     @click="group._editingStrategy = true"
                     title="Edit strategy label"></i>
                </span>
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
                 class="absolute top-full left-0 mt-1 z-50 bg-tv-panel border border-tv-border rounded shadow-lg p-1.5 w-44"
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
          <span class="w-32 mr-2 text-tv-muted text-base">{{ formatDate(group.opening_date) }}</span>

          <!-- Closing date -->
          <span class="w-32 text-tv-muted text-base">{{ group.closing_date ? formatDate(group.closing_date) : '\u2014' }}</span>

          <!-- Roll chain toggle -->
          <span class="w-10 flex items-center justify-center">
            <label v-if="group.has_roll_chain" class="relative inline-flex items-center cursor-pointer" @click.stop="rollChainModal = group.group_id" title="Roll chain">
              <span class="w-8 h-4 rounded-full transition-colors"
                    :class="rollChainModal === group.group_id ? 'bg-tv-blue' : 'bg-tv-border'">
                <span class="absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform"
                      :class="rollChainModal === group.group_id ? 'translate-x-4' : ''"></span>
              </span>
            </label>
            <i v-else-if="getGroupNote(group)" class="fas fa-sticky-note text-tv-amber text-sm" title="Has notes"></i>
          </span>

          <!-- Initial Premium -->
          <span class="w-28 text-right ml-auto text-base"
                :class="groupInitialPremium(group) > 0 ? 'text-tv-green' : groupInitialPremium(group) < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ groupInitialPremium(group) ? '$' + formatNumber(groupInitialPremium(group)) : '' }}
          </span>

          <!-- Realized P&L -->
          <span class="w-28 text-right ml-2 text-base font-medium"
                :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            {{ group.realized_pnl ? '$' + formatNumber(group.realized_pnl) : '' }}
          </span>
        </div>

        <!-- Expanded Detail -->
        <div v-show="group.expanded"
             class="bg-tv-bg border-t border-tv-border/50 px-4 py-3">

          <!-- Group Notes -->
          <div class="px-4 pb-2">
            <textarea :value="getGroupNote(group)"
                      @input="updateGroupNote(group, $event.target.value)"
                      @click.stop rows="1"
                      class="w-full bg-transparent text-tv-text text-sm border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                      placeholder="Add notes..."></textarea>
          </div>

          <!-- Position View -->
            <div>
              <!-- Lots Table Header -->
              <div class="flex items-center text-sm text-tv-muted px-4 py-2 border-b border-tv-border/30 font-mono">
                <span class="w-10 text-right">Qty</span>
                <span class="w-16 text-center mx-2">Exp</span>
                <span class="w-16 text-center mx-2">Strike</span>
                <span class="w-10">Type</span>
                <span class="w-20 text-center ml-3">Status</span>
                <span class="w-24 text-right">Entry Price</span>
                <span class="w-24 text-right ml-2">Close Price</span>
              </div>

              <!-- Section A: Equity Aggregate -->
              <template v-if="openEquityLots(group).length > 0">
                <div>
                  <!-- Aggregate summary row -->
                  <div class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono">
                    <span class="w-10 text-right font-medium"
                          :class="equityAggregate(group).quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
                      {{ equityAggregate(group).quantity }}
                    </span>
                    <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">Shares</span>
                    <span class="w-16 text-center mx-2 py-0.5 rounded text-tv-muted">&mdash;</span>
                    <span class="w-10 text-tv-muted">Stk</span>
                    <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3 bg-tv-green/20 text-tv-green border-tv-green/50">OPEN</span>
                    <span class="w-24 text-right text-tv-muted">${{ formatNumber(equityAggregate(group).avgPrice) }}</span>
                    <span class="w-24 text-right ml-2"></span>
                  </div>
                </div>
              </template>

              <!-- Separator between equity aggregate and option/closed lots -->
              <div v-if="openEquityLots(group).length > 0 && groupedOptionLegs(group).length > 0"
                   class="border-t border-tv-muted/20 my-2 mx-4"></div>

              <!-- Section B: Option legs (consolidated by strike) + closed equity lots -->
              <template v-for="(leg, legIdx) in groupedOptionLegs(group)" :key="leg.key">
                <div>
                  <!-- Separator between open and closed -->
                  <div v-if="legIdx > 0 && leg.status === 'CLOSED' && groupedOptionLegs(group)[legIdx - 1].status !== 'CLOSED'"
                       class="border-t border-tv-muted/40 my-3 mx-4"></div>
                  <div class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono">
                    <span class="w-10 text-right font-medium"
                          :class="leg.totalQuantity > 0 ? 'text-tv-green' : leg.totalQuantity < 0 ? 'text-tv-red' : 'text-tv-muted'">
                      {{ leg.totalQuantity }}
                    </span>
                    <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">
                      {{ leg.expiration ? formatExpirationShort(leg.expiration) : (leg.instrument_type === 'EQUITY' ? 'Shares' : '\u2014') }}
                    </span>
                    <span class="w-16 text-center mx-2 py-0.5 rounded"
                          :class="leg.strike ? 'bg-tv-panel text-tv-text' : 'text-tv-muted'">
                      {{ leg.strike || '\u2014' }}
                    </span>
                    <span class="w-10 text-tv-muted">
                      {{ leg.option_type ? (leg.option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put') : (leg.instrument_type === 'EQUITY' ? 'Stk' : '\u2014') }}
                    </span>
                    <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3"
                          :class="leg.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : leg.expired ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50' : 'bg-tv-muted/20 text-tv-muted border-tv-red/50'">
                      {{ leg.expired ? 'EXPIRED' : leg.status }}
                    </span>
                    <span class="w-24 text-right text-tv-muted">${{ formatNumber(leg.avgEntryPrice) }}</span>
                    <span class="w-24 text-right text-tv-muted ml-2">{{ leg.expired ? '\u2014' : (leg.avgClosePrice != null ? '$' + formatNumber(leg.avgClosePrice) : '') }}</span>
                  </div>
                </div>
              </template>
            </div>

        </div>
      </div>
    </div>
  </div>

  <!-- Bottom spacer — lets the last row scroll comfortably above the fold -->
  <div class="h-96"></div>

  <!-- Roll Chain Modal -->
  <RollChainModal
    :group-id="rollChainModal"
    :underlying="groups.find(g => g.group_id === rollChainModal)?.underlying || ''"
    @close="rollChainModal = null"
  />

</template>
