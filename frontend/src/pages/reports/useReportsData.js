/**
 * Report data fetching, account management, sorting, and date filtering.
 */
import { ref } from 'vue'

export function useReportsData(Auth, { getActiveStrategies }) {
  // --- State ---
  const accounts = ref([])
  const selectedAccount = ref('')
  const loading = ref(true)

  // Date range filters
  const exitFrom = ref('')
  const exitTo = ref('')

  // Sorting
  const sortColumn = ref('totalPnl')
  const sortDirection = ref('desc')

  // Report data
  const summary = ref({
    totalPnl: 0, totalTrades: 0, wins: 0, losses: 0,
    winRate: 0, avgPnl: 0, avgWin: 0, avgLoss: 0,
    largestWin: 0, largestLoss: 0, avgMaxRisk: 0, avgMaxReward: 0,
  })
  const strategyBreakdown = ref([])

  // Sortable columns config
  const columns = [
    { key: 'strategy', label: 'Strategy', width: 'w-48', align: '' },
    { key: 'totalTrades', label: 'Trades', width: 'w-28', align: 'text-center justify-center' },
    { key: 'winRate', label: 'Win Rate', width: 'w-24', align: 'text-right justify-end' },
    { key: 'totalPnl', label: 'Total P&L', width: 'w-32', align: 'text-right justify-end' },
    { key: 'avgPnl', label: 'Avg P&L', width: 'w-28', align: 'text-right justify-end' },
    { key: 'avgWin', label: 'Avg Win', width: 'w-28', align: 'text-right justify-end' },
    { key: 'avgLoss', label: 'Avg Loss', width: 'w-28', align: 'text-right justify-end' },
    { key: 'largestWin', label: 'Best', width: 'w-28', align: 'text-right justify-end' },
    { key: 'largestLoss', label: 'Worst', width: 'w-28', align: 'text-right justify-end' },
  ]

  // --- Methods ---
  function getAccountSymbol(accountNumber) {
    const account = accounts.value.find(a => a.account_number === accountNumber)
    if (!account) return '?'
    const name = (account.account_name || '').toUpperCase()
    if (name.includes('ROTH')) return 'R'
    if (name.includes('INDIVIDUAL')) return 'I'
    if (name.includes('TRADITIONAL')) return 'T'
    return name.charAt(0) || '?'
  }

  async function loadAccounts() {
    try {
      const response = await Auth.authFetch('/api/accounts')
      const data = await response.json()
      accounts.value = (data.accounts || []).sort((a, b) => {
        const order = (name) => {
          const u = (name || '').toUpperCase()
          if (u.includes('ROTH')) return 1
          if (u.includes('INDIVIDUAL')) return 2
          if (u.includes('TRADITIONAL')) return 3
          return 4
        }
        return order(a.account_name) - order(b.account_name)
      })
    } catch (error) {
      console.error('Error loading accounts:', error)
    }
  }

  async function fetchReport() {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (selectedAccount.value) params.append('account_number', selectedAccount.value)
      if (exitFrom.value) params.append('exit_from', exitFrom.value)
      if (exitTo.value) params.append('exit_to', exitTo.value)
      params.append('strategies', getActiveStrategies().join(','))

      const response = await Auth.authFetch(`/api/reports/performance?${params}`)
      const data = await response.json()

      if (data.error) { console.error('Report error:', data.error); return }

      summary.value = data.summary || summary.value
      strategyBreakdown.value = data.breakdown || []
      applySortToBreakdown()
    } catch (error) {
      console.error('Error fetching report:', error)
    } finally {
      loading.value = false
    }
  }

  function sortBreakdown(column) {
    if (sortColumn.value === column) {
      sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortColumn.value = column
      sortDirection.value = column === 'strategy' ? 'asc' : 'desc'
    }
    applySortToBreakdown()
    localStorage.setItem('reports_sort', JSON.stringify({
      column: sortColumn.value,
      direction: sortDirection.value,
    }))
  }

  function applySortToBreakdown() {
    strategyBreakdown.value.sort((a, b) => {
      let aVal = a[sortColumn.value]
      let bVal = b[sortColumn.value]
      if (sortColumn.value === 'strategy') {
        aVal = (aVal || '').toLowerCase()
        bVal = (bVal || '').toLowerCase()
      } else {
        aVal = aVal || 0
        bVal = bVal || 0
      }
      if (aVal < bVal) return sortDirection.value === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection.value === 'asc' ? 1 : -1
      return 0
    })
  }

  function onAccountChange() {
    localStorage.setItem('trade_journal_selected_account', selectedAccount.value)
    fetchReport()
  }

  function onDateFilterUpdate({ from, to }) {
    exitFrom.value = from || ''
    exitTo.value = to || ''
    fetchReport()
  }

  function loadSavedState() {
    const savedAccount = localStorage.getItem('trade_journal_selected_account')
    if (savedAccount !== null) selectedAccount.value = savedAccount

    const savedSort = localStorage.getItem('reports_sort')
    if (savedSort) {
      try {
        const parsed = JSON.parse(savedSort)
        sortColumn.value = parsed.column || 'totalPnl'
        sortDirection.value = parsed.direction || 'desc'
      } catch (e) { /* default sort */ }
    }
  }

  return {
    // State
    accounts, selectedAccount, loading,
    exitFrom, exitTo,
    sortColumn, sortDirection,
    summary, strategyBreakdown,
    columns,
    // Methods
    getAccountSymbol,
    loadAccounts, fetchReport,
    sortBreakdown,
    onAccountChange, onDateFilterUpdate,
    loadSavedState,
  }
}
