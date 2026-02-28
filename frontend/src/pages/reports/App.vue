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

// Nav auth
const authEnabled = ref(false)
const userEmail = ref('')

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
  await Auth.requireAuth()
  await Auth.requireTastytrade()

  authEnabled.value = Auth.isAuthEnabled()
  if (authEnabled.value) {
    const user = await Auth.getUser()
    if (user) userEmail.value = user.email || ''
  }

  await loadAccounts()
  loadSavedFilters()
  await fetchReport()
})

// Nav links
const navLinks = [
  { href: '/positions', label: 'Positions' },
  { href: '/ledger', label: 'Ledger' },
  { href: '/reports', label: 'Reports' },
  { href: '/risk', label: 'Risk' },
]

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
             :class="link.href === '/reports' ? 'text-tv-text bg-tv-border rounded-sm' : 'text-tv-muted hover:text-tv-text'">
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
              :class="filterType.includes('credit') ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Credit
      </button>
      <button @click="toggleFilter('type', 'debit')"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterType.includes('debit') ? 'bg-amber-500/20 text-amber-400 border-amber-500/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Debit
      </button>
    </div>

    <!-- Shares Filter -->
    <div class="flex items-center gap-2 text-base">
      <button @click="toggleShares()"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterShares ? 'bg-purple-500/20 text-purple-400 border-purple-500/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Shares
      </button>
    </div>

    <!-- Active filter summary -->
    <div v-if="activeStrategyCount < totalStrategyCount" class="flex-1 text-right text-sm text-tv-muted">
      {{ activeStrategyCount }} strategies selected
    </div>
  </div>

  <!-- Loading State -->
  <div v-if="loading" class="text-center py-12">
    <div class="spinner mx-auto mb-4" style="width: 40px; height: 40px; border-width: 4px;"></div>
    <p class="text-tv-muted">Loading report data...</p>
  </div>

  <!-- Main Content -->
  <main v-else class="p-4">
    <!-- Summary Stats Row -->
    <div class="grid grid-cols-6 gap-3 mb-4">
      <!-- Total P&L -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Total Realized P&L</div>
        <div class="text-2xl font-bold" :class="summary.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="summary.totalPnl < 0">-</span>${{ formatNumber(Math.abs(summary.totalPnl)) }}
        </div>
        <div class="text-tv-muted text-sm mt-1">{{ summary.totalTrades }} closed trades</div>
      </div>

      <!-- Win Rate -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Win Rate</div>
        <div class="text-2xl font-bold text-tv-blue">{{ formatPercent(summary.winRate) }}%</div>
        <div class="text-tv-muted text-sm mt-1">
          <span class="text-tv-green">{{ summary.wins }}</span> W /
          <span class="text-tv-red">{{ summary.losses }}</span> L
        </div>
      </div>

      <!-- Avg P&L -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Avg P&L / Trade</div>
        <div class="text-2xl font-bold" :class="summary.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="summary.avgPnl < 0">-</span>${{ formatNumber(Math.abs(summary.avgPnl)) }}
        </div>
        <div class="text-tv-muted text-sm mt-1">
          W: ${{ formatNumber(summary.avgWin) }} |
          L: ${{ formatNumber(Math.abs(summary.avgLoss)) }}
        </div>
      </div>

      <!-- Largest Win -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Largest Win</div>
        <div class="text-2xl font-bold text-tv-green">${{ formatNumber(summary.largestWin) }}</div>
      </div>

      <!-- Largest Loss -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Largest Loss</div>
        <div class="text-2xl font-bold text-tv-red">-${{ formatNumber(Math.abs(summary.largestLoss)) }}</div>
      </div>

      <!-- Risk/Reward -->
      <div class="bg-tv-panel border border-tv-border p-4">
        <div class="text-tv-muted text-sm mb-1">Avg Risk / Reward</div>
        <div class="text-lg font-bold">
          <span class="text-amber-400">${{ formatNumber(summary.avgMaxRisk) }}</span>
          <span class="text-tv-muted mx-1">/</span>
          <span class="text-cyan-400">${{ formatNumber(summary.avgMaxReward) }}</span>
        </div>
      </div>
    </div>

    <!-- Strategy Breakdown Table -->
    <div class="bg-tv-panel border border-tv-border">
      <!-- Table Header -->
      <div class="flex items-center px-4 py-3 text-sm text-tv-muted border-b border-tv-border bg-tv-panel/50">
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
             class="flex items-center px-4 py-3 text-base hover:bg-tv-border/30 transition-colors">
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
          <span class="w-28 text-right text-amber-400">
            <template v-if="row.avgMaxRisk > 0">${{ formatNumber(row.avgMaxRisk) }}</template>
            <span v-else class="text-tv-muted">-</span>
          </span>
          <span class="w-28 text-right text-cyan-400">
            <template v-if="row.avgMaxReward > 0">${{ formatNumber(row.avgMaxReward) }}</template>
            <span v-else class="text-tv-muted">-</span>
          </span>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="strategyBreakdown.length === 0" class="px-4 py-12 text-center text-tv-muted">
        <i class="fas fa-chart-bar text-4xl mb-4"></i>
        <p>No closed trades found for the selected filters.</p>
      </div>
    </div>
  </main>
</template>

<style scoped>
.spinner {
  border: 2px solid #2a2e39;
  border-top: 2px solid #2962ff;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  animation: spin 1s linear infinite;
  display: inline-block;
}
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>
