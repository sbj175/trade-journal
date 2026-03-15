<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatPercent } from '@/lib/formatters'
import DateFilter from '@/components/DateFilter.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useReportsFilters } from './useReportsFilters'
import { useReportsData } from './useReportsData'

const Auth = useAuth()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()

// ==================== COMPOSABLES ====================
// Filters must be initialized first so getActiveStrategies is available for data composable.
// onFilterChange is wired after useReportsData via lateBindFilterChange.
let lateBindFilterChange = () => {}
const {
  filterDirection, filterType, filterShares, filterStrategies,
  strategyDropdownOpen,
  allStrategyNames, activeStrategyCount, totalStrategyCount,
  getActiveStrategies,
  toggleFilter, toggleShares, toggleStrategyPick, clearStrategyPicks,
  saveFilters, loadSavedFilters,
} = useReportsFilters({ onFilterChange: () => lateBindFilterChange() })

const {
  accounts, selectedAccount, loading,
  exitFrom, exitTo,
  sortColumn, sortDirection,
  summary, strategyBreakdown,
  columns,
  getAccountSymbol,
  loadAccounts, fetchReport,
  sortBreakdown,
  onAccountChange, onDateFilterUpdate,
  loadSavedState,
} = useReportsData(Auth, { getActiveStrategies })

lateBindFilterChange = fetchReport

// ==================== DROPDOWN CLOSE ====================
function onDocumentClick(e) {
  if (strategyDropdownOpen.value && !e.target.closest('.strategy-dropdown-wrapper')) {
    strategyDropdownOpen.value = false
  }
}

// Watch account store for changes from GlobalToolbar
watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

// Watch sync store — refetch when sync completes
watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) await fetchReport()
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  document.addEventListener('click', onDocumentClick)
  await loadAccounts()
  selectedAccount.value = accountsStore.selectedAccount
  loadSavedState()
  loadSavedFilters()
  await fetchReport()
})
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <!-- Page-specific filters teleported to GlobalToolbar -->
  <Teleport to="#page-filters">
  <div class="bg-tv-panel border-b border-tv-border">
    <!-- Row 1: Date Controls -->
    <div class="px-4 py-2.5 flex items-center gap-5 border-b border-tv-border/50">
      <DateFilter storage-key="reports_dateFilter" default-preset="This Month" @update="onDateFilterUpdate" />
    </div>

    <!-- Row 2: Strategy Filters -->
    <div class="px-4 py-2.5 flex items-center gap-6">
      <!-- Direction Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted text-sm">Direction:</span>
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

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Type Filter -->
      <div class="flex items-center gap-2">
        <span class="text-tv-muted text-sm">Type:</span>
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

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Shares Filter -->
      <button @click="toggleShares()"
              class="px-3 py-1.5 text-sm border rounded transition-colors"
              :class="filterShares ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
        Shares
      </button>

      <div class="w-px h-6 bg-tv-border"></div>

      <!-- Strategy Picker Dropdown -->
      <div class="relative strategy-dropdown-wrapper">
        <button @click="strategyDropdownOpen = !strategyDropdownOpen"
                class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                :class="filterStrategies.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
          Strategy
          <span v-if="filterStrategies.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ filterStrategies.length }}</span>
          <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
        </button>
        <div v-if="strategyDropdownOpen"
             class="absolute top-full left-0 mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-50 py-1 min-w-[200px] max-h-64 overflow-y-auto">
          <button v-if="filterStrategies.length"
                  @click="filterStrategies = []; saveFilters(); fetchReport()"
                  class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
            Clear all
          </button>
          <button v-for="s in allStrategyNames" :key="s"
                  @click="toggleStrategyPick(s)"
                  class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
            <i class="fas text-[10px]" :class="filterStrategies.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
            <span :class="filterStrategies.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
          </button>
        </div>
      </div>

      <!-- Active filter summary (pushed right) -->
      <div v-if="activeStrategyCount < totalStrategyCount" class="flex-1 text-right text-sm text-tv-muted">
        {{ activeStrategyCount }} of {{ totalStrategyCount }} strategies
      </div>
    </div>
  </div>
  </Teleport>

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
          <span v-if="summary.totalPnl < 0">-</span>${{ formatNumber(Math.abs(summary.totalPnl), 0) }}
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
          <span v-if="summary.avgPnl < 0">-</span>${{ formatNumber(Math.abs(summary.avgPnl), 0) }}
        </div>
        <div class="text-xs text-tv-muted mt-1">
          W: ${{ formatNumber(summary.avgWin, 0) }} |
          L: ${{ formatNumber(Math.abs(summary.avgLoss), 0) }}
        </div>
      </div>

      <!-- Largest Win -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-green">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Largest Win</div>
        <div class="text-2xl font-bold text-tv-green">${{ formatNumber(summary.largestWin, 0) }}</div>
      </div>

      <!-- Largest Loss -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-red">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Largest Loss</div>
        <div class="text-2xl font-bold text-tv-red">-${{ formatNumber(Math.abs(summary.largestLoss), 0) }}</div>
      </div>

      <!-- Risk/Reward -->
      <div class="metric-card bg-tv-panel border border-tv-border p-4 border-l-2 border-l-tv-amber">
        <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Avg Risk / Reward</div>
        <div class="text-lg font-bold">
          <span class="text-tv-amber">${{ formatNumber(summary.avgMaxRisk, 0) }}</span>
          <span class="text-tv-muted mx-1">/</span>
          <span class="text-tv-cyan">${{ formatNumber(summary.avgMaxReward, 0) }}</span>
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
            <span v-if="row.totalPnl < 0">-</span>${{ formatNumber(Math.abs(row.totalPnl), 0) }}
          </span>
          <span class="w-28 text-right" :class="row.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="row.avgPnl < 0">-</span>${{ formatNumber(Math.abs(row.avgPnl), 0) }}
          </span>
          <span class="w-28 text-right text-tv-green">${{ formatNumber(row.avgWin, 0) }}</span>
          <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.avgLoss), 0) }}</span>
          <span class="w-28 text-right text-tv-green">${{ formatNumber(row.largestWin, 0) }}</span>
          <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.largestLoss), 0) }}</span>
          <span class="w-28 text-right text-tv-amber">
            <template v-if="row.avgMaxRisk > 0">${{ formatNumber(row.avgMaxRisk, 0) }}</template>
            <span v-else class="text-tv-muted">-</span>
          </span>
          <span class="w-28 text-right text-tv-cyan">
            <template v-if="row.avgMaxReward > 0">${{ formatNumber(row.avgMaxReward, 0) }}</template>
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
