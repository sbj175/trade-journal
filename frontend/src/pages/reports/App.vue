<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { STRATEGY_CATEGORIES } from '@/lib/constants'
import { formatNumber, formatPercent } from '@/lib/formatters'

const Auth = useAuth()

// --- State ---
const accounts = ref([])
const selectedAccount = ref('')
const timePeriod = ref('90')
const loading = ref(true)

// Category-based filtering
const filterDirection = ref([])   // 'bullish', 'bearish', 'neutral'
const filterType = ref([])        // 'credit', 'debit'
const filterShares = ref(false)

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


// --- Computed ---
const activeStrategyCount = computed(() => getActiveStrategies().length)
const totalStrategyCount = computed(() => Object.keys(STRATEGY_CATEGORIES).length)

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

function loadSavedFilters() {
  const savedAccount = localStorage.getItem('trade_journal_selected_account')
  if (savedAccount !== null) selectedAccount.value = savedAccount

  const savedTimePeriod = localStorage.getItem('reports_time_period')
  if (savedTimePeriod) timePeriod.value = savedTimePeriod

  const savedFilters = localStorage.getItem('reports_category_filters')
  if (savedFilters) {
    try {
      const parsed = JSON.parse(savedFilters)
      filterDirection.value = parsed.direction || []
      filterType.value = parsed.type || []
      filterShares.value = parsed.shares || false
    } catch (e) { /* default: no filters */ }
  }

  const savedSort = localStorage.getItem('reports_sort')
  if (savedSort) {
    try {
      const parsed = JSON.parse(savedSort)
      sortColumn.value = parsed.column || 'totalPnl'
      sortDirection.value = parsed.direction || 'desc'
    } catch (e) { /* default sort */ }
  }
}

function saveFilters() {
  localStorage.setItem('reports_category_filters', JSON.stringify({
    direction: filterDirection.value,
    type: filterType.value,
    shares: filterShares.value,
  }))
}

function onAccountChange() {
  localStorage.setItem('trade_journal_selected_account', selectedAccount.value)
  fetchReport()
}

function onTimePeriodChange() {
  localStorage.setItem('reports_time_period', timePeriod.value)
  fetchReport()
}

function toggleFilter(category, value) {
  if (category === 'direction') {
    const idx = filterDirection.value.indexOf(value)
    if (idx >= 0) filterDirection.value.splice(idx, 1)
    else filterDirection.value.push(value)
  } else if (category === 'type') {
    const idx = filterType.value.indexOf(value)
    if (idx >= 0) filterType.value.splice(idx, 1)
    else filterType.value = [value]
  }
  saveFilters()
  fetchReport()
}

function toggleShares() {
  filterShares.value = !filterShares.value
  saveFilters()
  fetchReport()
}

function getActiveStrategies() {
  const strategies = []
  const noDir = filterDirection.value.length === 0
  const noType = filterType.value.length === 0

  for (const [strategy, cat] of Object.entries(STRATEGY_CATEGORIES)) {
    if (cat.isShares) {
      if (filterShares.value) strategies.push(strategy)
      continue
    }
    const dirMatch = noDir || filterDirection.value.includes(cat.direction)
    const typeMatch = noType || filterType.value.includes(cat.type)
    if (dirMatch && typeMatch) strategies.push(strategy)
  }
  return strategies
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
    params.append('days', timePeriod.value)
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

// --- Lifecycle ---
onMounted(async () => {
  await loadAccounts()
  loadSavedFilters()
  await fetchReport()
})

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

  <!-- Filters Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-3 flex items-center gap-8">
    <!-- Time Filter -->
    <div class="flex items-center gap-3 text-base">
      <span class="text-tv-muted">Time:</span>
      <select v-model="timePeriod" @change="onTimePeriodChange()"
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
    <div class="flex items-center gap-2 text-base">
      <span class="text-tv-muted">Direction:</span>
      <button v-for="dir in [
        { value: 'bullish', active: 'bg-tv-green/20 text-tv-green border-tv-green/50' },
        { value: 'bearish', active: 'bg-tv-red/20 text-tv-red border-tv-red/50' },
        { value: 'neutral', active: 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' },
      ]" :key="dir.value"
        @click="toggleFilter('direction', dir.value)"
        class="px-3 py-1.5 text-sm border rounded transition-colors capitalize"
        :class="filterDirection.includes(dir.value) ? dir.active : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        {{ dir.value }}
      </button>
    </div>

    <!-- Type Filter -->
    <div class="flex items-center gap-2 text-base">
      <span class="text-tv-muted">Type:</span>
      <button @click="toggleFilter('type', 'credit')"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterType.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Credit
      </button>
      <button @click="toggleFilter('type', 'debit')"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterType.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Debit
      </button>
    </div>

    <!-- Shares Filter -->
    <div class="flex items-center gap-2 text-base">
      <button @click="toggleShares()"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterShares ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Shares
      </button>
    </div>

    <!-- Active filter summary -->
    <div v-if="activeStrategyCount < totalStrategyCount" class="flex-1 text-right text-sm text-tv-muted">
      {{ activeStrategyCount }} strategies selected
    </div>
  </div>

  <!-- Loading State -->
  <div v-if="loading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading report data...</p>
  </div>

  <!-- Main Content -->
  <main v-else class="p-4">
    <!-- Summary Stats Row -->
    <div class="grid grid-cols-6 gap-3 mb-4">
      <!-- Total P&L -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="summary.totalPnl >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Total Realized P&L</div>
        <div class="text-2xl font-bold" :class="summary.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="summary.totalPnl < 0">-</span>${{ formatNumber(Math.abs(summary.totalPnl)) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">{{ summary.totalTrades }} closed trades</div>
      </div>

      <!-- Win Rate -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-blue">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Win Rate</div>
        <div class="text-2xl font-bold text-tv-blue">{{ formatPercent(summary.winRate) }}%</div>
        <div class="text-xs text-tv-muted mt-1">
          <span class="text-tv-green">{{ summary.wins }}</span> W /
          <span class="text-tv-red">{{ summary.losses }}</span> L
        </div>
      </div>

      <!-- Avg P&L -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2"
           :class="summary.avgPnl >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Avg P&L / Trade</div>
        <div class="text-2xl font-bold" :class="summary.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="summary.avgPnl < 0">-</span>${{ formatNumber(Math.abs(summary.avgPnl)) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          W: ${{ formatNumber(summary.avgWin) }} |
          L: ${{ formatNumber(Math.abs(summary.avgLoss)) }}
        </div>
      </div>

      <!-- Largest Win -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-green">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Largest Win</div>
        <div class="text-2xl font-bold text-tv-green">${{ formatNumber(summary.largestWin) }}</div>
      </div>

      <!-- Largest Loss -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-red">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Largest Loss</div>
        <div class="text-2xl font-bold text-tv-red">-${{ formatNumber(Math.abs(summary.largestLoss)) }}</div>
      </div>

      <!-- Risk/Reward -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-amber">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Avg Risk / Reward</div>
        <div class="text-lg font-bold">
          <span class="text-tv-amber">${{ formatNumber(summary.avgMaxRisk) }}</span>
          <span class="text-tv-muted mx-1">/</span>
          <span class="text-tv-cyan">${{ formatNumber(summary.avgMaxReward) }}</span>
        </div>
      </div>
    </div>

    <!-- Strategy Breakdown Table -->
    <div class="bg-tv-panel border border-tv-border rounded">
      <!-- Table Header -->
      <div class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel/50 sticky top-14 z-10">
        <span v-for="col in columns" :key="col.key"
              class="cursor-pointer hover:text-tv-text flex items-center gap-1"
              :class="[col.width, col.align]"
              @click="sortBreakdown(col.key)">
          {{ col.label }}
          <span v-if="sortColumn === col.key" class="text-tv-blue">
            {{ sortDirection === 'asc' ? '\u25B2' : '\u25BC' }}
          </span>
        </span>
        <span class="w-28 text-right">Avg Risk</span>
        <span class="w-28 text-right">Avg Reward</span>
      </div>

      <!-- Table Body -->
      <div class="divide-y divide-tv-border">
        <div v-for="row in strategyBreakdown" :key="row.strategy"
             class="flex items-center px-4 h-12 hover:bg-tv-border/20 transition-colors">
          <span class="w-48 font-medium text-tv-text">{{ row.strategy }}</span>
          <span class="w-28 text-center">
            {{ row.totalTrades }}
            <span class="text-tv-muted text-sm">
              (<span class="text-tv-green">{{ row.wins }}</span>/<span class="text-tv-red">{{ row.losses }}</span>)
            </span>
          </span>
          <span class="w-24 text-right" :class="row.winRate >= 50 ? 'text-tv-green' : 'text-tv-red'">
            {{ formatPercent(row.winRate) }}%
          </span>
          <span class="w-32 text-right font-medium" :class="row.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="row.totalPnl < 0">-</span>${{ formatNumber(Math.abs(row.totalPnl)) }}
          </span>
          <span class="w-28 text-right" :class="row.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="row.avgPnl < 0">-</span>${{ formatNumber(Math.abs(row.avgPnl)) }}
          </span>
          <span class="w-28 text-right text-tv-green">${{ formatNumber(row.avgWin) }}</span>
          <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.avgLoss)) }}</span>
          <span class="w-28 text-right text-tv-green">${{ formatNumber(row.largestWin) }}</span>
          <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.largestLoss)) }}</span>
          <span class="w-28 text-right text-tv-amber">
            <template v-if="row.avgMaxRisk > 0">${{ formatNumber(row.avgMaxRisk) }}</template>
            <span v-else class="text-tv-muted">-</span>
          </span>
          <span class="w-28 text-right text-tv-cyan">
            <template v-if="row.avgMaxReward > 0">${{ formatNumber(row.avgMaxReward) }}</template>
            <span v-else class="text-tv-muted">-</span>
          </span>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="strategyBreakdown.length === 0" class="px-4 py-16 text-center text-tv-muted">
        <i class="fas fa-chart-bar text-3xl mb-3"></i>
        <p>No closed trades found for the selected filters.</p>
      </div>
    </div>
  </main>
</template>
