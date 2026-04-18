/**
 * Group filtering, sorting, CRUD operations, notes, and tags.
 */
import { ref, computed, nextTick } from 'vue'
import { STRATEGY_CATEGORIES, accountSortOrder } from '@/lib/constants'
import { groupInitialPremium, groupedOptionLegs, openEquityLots, equityAggregate } from '@/composables/useLedgerLots'
import { gcd } from '@/lib/math'

export function useLedgerGroups(Auth, state) {
  const {
    groups, filteredGroups, accounts, selectedAccount, loading,
    filterUnderlying, filterDirection, filterType, filterStrategy, filterTagIds,
    filterRollsOnly, showOpen, showClosed, sortColumn, sortDirection,
    dateFrom, dateTo, stats,
  } = state

  // ==================== NOTES STATE ====================
  const groupNotes = ref({})
  const noteSaveTimers = {}

  // ==================== TAGS STATE ====================
  const availableTags = ref([])
  const tagPopoverGroup = ref(null)
  const tagSearch = ref('')

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

  // ==================== DATA FETCHING ====================
  async function loadAccounts() {
    try {
      const response = await Auth.authFetch('/api/accounts')
      const data = await response.json()
      const list = data.accounts || []
      list.sort((a, b) =>
        accountSortOrder(a.account_name) - accountSortOrder(b.account_name)
      )
      accounts.value = list
    } catch (error) {
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
        return (g.lots || []).some(lot => {
          if (inRange(lot.entry_date ? new Date(lot.entry_date) : null)) return true
          return (lot.closings || []).some(c => inRange(c.closing_date ? new Date(c.closing_date) : null))
        })
      })
    }

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
      } else if (col === 'return_percent') {
        const basisA = Math.abs(groupInitialPremium(a) || 0)
        const basisB = Math.abs(groupInitialPremium(b) || 0)
        va = basisA ? (a.realized_pnl || 0) / basisA : -Infinity
        vb = basisB ? (b.realized_pnl || 0) / basisB : -Infinity
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

    for (const group of filteredGroups.value) {
      group.initialPremium = groupInitialPremium(group)
      const basis = Math.abs(group.initialPremium || 0)
      group.returnPercent = basis > 0 ? ((group.realized_pnl || 0) / basis) * 100 : null
      group.optionLegs = groupedOptionLegs(group)
      group.equityAgg = equityAggregate(group)
      group.hasEquityLots = openEquityLots(group).length > 0

      const strikeLegs = group.optionLegs.filter(l => l.strike != null && l.instrument_type !== 'EQUITY')
      if (strikeLegs.length > 0) {
        const unique = [...new Set(strikeLegs.map(l => Number(l.strike)).filter(n => Number.isFinite(n)))]
        unique.sort((a, b) => a - b)
        group.strikes = unique.map(n => String(n)).join('/')
      } else {
        group.strikes = null
      }

      const optLegs = group.optionLegs.filter(l => l.instrument_type !== 'EQUITY')
      if (optLegs.length > 0) {
        const openOpts = optLegs.filter(l => l.status === 'OPEN')
        const src = openOpts.length > 0 ? openOpts : optLegs
        const quantities = src.map(l => Math.abs(l.totalQuantity)).filter(q => q > 0)
        group.contractCount = quantities.length > 0 ? quantities.reduce((a, b) => gcd(a, b)) : null
      } else {
        group.contractCount = null
      }
    }

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
      }).catch(() => {})
      delete noteSaveTimers[key]
    }, 500)
  }

  // ==================== TAGS ====================
  async function loadAvailableTags() {
    try {
      const resp = await Auth.authFetch('/api/tags')
      availableTags.value = await resp.json()
    } catch (e) { }
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
    } catch (e) { }
  }

  async function removeTagFromGroup(group, tagId, event) {
    if (event) event.stopPropagation()
    try {
      await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags/${tagId}`, { method: 'DELETE' })
      group.tags = (group.tags || []).filter(t => t.id !== tagId)
    } catch (e) { }
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

  return {
    // Notes state
    groupNotes,
    // Tags state
    availableTags, tagPopoverGroup, tagSearch, filteredTagSuggestions,
    // Computed
    uniqueStrategies,
    // Data fetching
    loadAccounts, fetchLedger,
    // Filtering & sorting
    sortGroups, applyFilters, toggleFilter, toggleStrategyFilter, toggleTagFilter,
    onAccountChange, onSymbolFilterApply, clearSymbolFilter, onDateFilterUpdate,
    saveState,
    // Group management
    updateGroupStrategy, onGroupHeaderClick, getSortLabel,
    // Display helpers
    getAccountSymbol, getAccountBadgeClass,
    // Notes
    loadNotes, getGroupNote, updateGroupNote,
    // Tags
    loadAvailableTags, openTagPopover, closeTagPopover,
    addTagToGroup, removeTagFromGroup, handleTagInput,
  }
}
