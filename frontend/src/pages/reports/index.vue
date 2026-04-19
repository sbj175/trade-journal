<script setup>
import { onMounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import ReportsFilters from '@/components/ReportsFilters.vue'
import ReportsSummaryCards from '@/components/ReportsSummaryCards.vue'
import ReportsBreakdownTable from '@/components/ReportsBreakdownTable.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useReportsFilters } from '@/composables/useReportsFilters'
import { useReportsData } from '@/composables/useReportsData'

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

const filterState = { filterDirection, filterType, filterShares, filterStrategies, strategyDropdownOpen }
const filterHandlers = { toggleFilter, toggleShares, toggleStrategyPick, saveFilters, fetchReport, onDateFilterUpdate }

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
  await loadAccounts()
  selectedAccount.value = accountsStore.selectedAccount
  loadSavedState()
  loadSavedFilters()
  await fetchReport()
})
</script>

<template>
  <!-- Page-specific filters teleported to GlobalToolbar -->
  <Teleport to="#page-filters">
    <ReportsFilters
      :filter-state="filterState"
      :handlers="filterHandlers"
      :all-strategy-names="allStrategyNames"
      :active-strategy-count="activeStrategyCount"
      :total-strategy-count="totalStrategyCount"
    />
  </Teleport>

  <!-- Loading State -->
  <div v-if="loading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading report data...</p>
  </div>

  <main v-else class="p-4">
    <ReportsSummaryCards :summary="summary" />
    <ReportsBreakdownTable
      :strategy-breakdown="strategyBreakdown"
      :columns="columns"
      :sort-column="sortColumn"
      :sort-direction="sortDirection"
      @sort="sortBreakdown"
    />
  </main>
</template>
