/**
 * Position loading, filtering, sorting, sync, and account helpers.
 * Composable that takes Auth and quote accessors for computed values.
 */
import { ref, computed } from 'vue'

export function useEquityPositions(Auth, quoteAccessors) {
  const { getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent, quoteUpdateCounter } = quoteAccessors

  // --- State ---
  const allItems = ref([])
  const accounts = ref([])
  const selectedAccount = ref('')
  const selectedUnderlying = ref('')
  const isLoading = ref(false)
  const error = ref(null)
  const syncSummary = ref(null)
  const sortColumn = ref('underlying')
  const sortDirection = ref('asc')
  const expandedRows = ref({})

  // --- Computed ---

  const filteredItems = computed(() => {
    let items = allItems.value
    if (selectedAccount.value) {
      items = items.filter(i => i.accountNumber === selectedAccount.value)
    }
    if (selectedUnderlying.value) {
      items = items.filter(i => i.underlying === selectedUnderlying.value)
    }
    return items
  })

  const groupedPositions = computed(() => {
    // eslint-disable-next-line no-unused-vars
    const _ = quoteUpdateCounter.value

    const sorted = [...filteredItems.value]
    sorted.sort((a, b) => {
      let aVal, bVal
      switch (sortColumn.value) {
        case 'quantity':
          aVal = a.quantity || 0
          bVal = b.quantity || 0
          break
        case 'avg_price':
          aVal = a.avgPrice || 0
          bVal = b.avgPrice || 0
          break
        case 'cost_basis':
          aVal = a.costBasis || 0
          bVal = b.costBasis || 0
          break
        case 'market_value':
          aVal = getMarketValue(a)
          bVal = getMarketValue(b)
          break
        case 'pnl':
          aVal = getUnrealizedPnL(a)
          bVal = getUnrealizedPnL(b)
          break
        case 'pnl_percent':
          aVal = getPnLPercent(a)
          bVal = getPnLPercent(b)
          break
        case 'price':
          aVal = getQuotePrice(a.underlying) || 0
          bVal = getQuotePrice(b.underlying) || 0
          break
        default:
          aVal = (a.underlying || '').toLowerCase()
          bVal = (b.underlying || '').toLowerCase()
      }
      if (aVal < bVal) return sortDirection.value === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection.value === 'asc' ? 1 : -1
      return 0
    })
    return sorted
  })

  const totalCostBasis = computed(() => {
    const _ = quoteUpdateCounter.value
    return filteredItems.value.reduce((s, i) => s + (i.costBasis || 0), 0)
  })

  const totalMarketValue = computed(() => {
    const _ = quoteUpdateCounter.value
    return filteredItems.value.reduce((s, i) => s + getMarketValue(i), 0)
  })

  const totalPnL = computed(() => {
    const _ = quoteUpdateCounter.value
    return filteredItems.value.reduce((s, i) => s + getUnrealizedPnL(i), 0)
  })

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
    } catch (err) { }
  }

  async function syncAndLoad() {
    isLoading.value = true
    error.value = null
    syncSummary.value = null
    try {
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
    } catch (err) {
    }
    await loadPositions()
  }

  async function loadPositions() {
    isLoading.value = true
    error.value = null
    try {
      const response = await Auth.authFetch('/api/open-chains')
      const data = await response.json()

      const items = []
      if (typeof data === 'object' && !Array.isArray(data)) {
        Object.entries(data).forEach(([accountNumber, accountData]) => {
          const chains = accountData.chains || []
          chains.forEach(chain => {
            const eqLegs = chain.equity_legs || []
            if (eqLegs.length === 0) return
            const eqSummary = chain.equity_summary || {}
            items.push({
              underlying: chain.underlying,
              accountNumber,
              groupId: chain.group_id,
              strategyType: chain.strategy_type || 'Shares',
              quantity: eqSummary.quantity || 0,
              avgPrice: eqSummary.average_price || 0,
              costBasis: eqSummary.cost_basis || 0,
              openingDate: chain.opening_date,
              hasOptions: (chain.open_legs || []).length > 0,
              optionStrategy: (chain.open_legs || []).length > 0 ? chain.strategy_type : null,
              equityLegs: eqLegs,
            })
          })
        })
      }
      allItems.value = items
    } catch (err) {
      error.value = 'Failed to load positions'
    } finally {
      isLoading.value = false
    }
  }

  // --- Account helpers ---

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

  // --- UI interactions ---

  function toggleExpanded(groupId) {
    expandedRows.value = { ...expandedRows.value, [groupId]: !expandedRows.value[groupId] }
  }

  function sort(column) {
    if (sortColumn.value === column) {
      sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortColumn.value = column
      if (['pnl', 'pnl_percent', 'market_value', 'cost_basis', 'price'].includes(column)) {
        sortDirection.value = 'desc'
      } else {
        sortDirection.value = 'asc'
      }
    }
  }

  function sortIcon(column) {
    if (sortColumn.value !== column) return ''
    return sortDirection.value === 'asc' ? '\u25B2' : '\u25BC'
  }

  function onAccountChange() {
    localStorage.setItem('trade_journal_selected_account', selectedAccount.value)
  }

  return {
    // State
    allItems, accounts, selectedAccount, selectedUnderlying,
    isLoading, error, syncSummary, sortColumn, sortDirection, expandedRows,
    // Computed
    filteredItems, groupedPositions, totalCostBasis, totalMarketValue, totalPnL,
    // Data fetching
    fetchAccounts, syncAndLoad, loadPositions,
    // Account helpers
    getAccountSymbol, getAccountBadgeClass,
    // UI interactions
    toggleExpanded, sort, sortIcon, onAccountChange,
  }
}
