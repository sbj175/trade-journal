<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber, formatDate, formatExpirationShort } from '@/lib/formatters'
import DateFilter from '@/components/DateFilter.vue'
import RollChainModal from '@/components/RollChainModal.vue'
import InfoPopover from '@/components/InfoPopover.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { groupedOptionLegs, openEquityLots, equityAggregate, groupInitialPremium } from './useLedgerLots'
import { useLedgerGroups } from './useLedgerGroups'

const Auth = useAuth()
const route = useRoute()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()

// ==================== STATE ====================
const groups = ref([])
const accounts = ref([])
const filteredGroups = ref([])
const selectedAccount = ref('')
const filterUnderlying = ref('')
const dateFrom = ref(null)
const dateTo = ref(null)
const showOpen = ref(true)
const showClosed = ref(true)
const filterRollsOnly = ref(false)
const rollChainModal = ref(null)
const sortColumn = ref('opening_date')
const sortDirection = ref('desc')
const loading = ref(true)
const stats = ref({ openCount: 0, closedCount: 0 })
const filterDirection = ref([])
const filterType = ref([])
const dateFilterRef = ref(null)
const filterStrategy = ref([])
const filterTagIds = ref([])
const strategyDropdownOpen = ref(false)
const tagDropdownOpen = ref(false)

// ==================== COMPOSABLES ====================
const {
  groupNotes, availableTags, tagPopoverGroup, tagSearch,
  filteredTagSuggestions, uniqueStrategies,
  loadAccounts, fetchLedger,
  sortGroups, applyFilters, toggleFilter, toggleStrategyFilter, toggleTagFilter,
  onAccountChange, onSymbolFilterApply, clearSymbolFilter, onDateFilterUpdate,
  saveState,
  updateGroupStrategy, onGroupHeaderClick, getSortLabel,
  getAccountSymbol, getAccountBadgeClass,
  loadNotes, getGroupNote, updateGroupNote,
  loadAvailableTags, openTagPopover, closeTagPopover,
  addTagToGroup, removeTagFromGroup, handleTagInput,
} = useLedgerGroups(Auth, {
  groups, filteredGroups, accounts, selectedAccount, loading,
  filterUnderlying, filterDirection, filterType, filterStrategy, filterTagIds,
  filterRollsOnly, showOpen, showClosed, sortColumn, sortDirection,
  dateFrom, dateTo, stats,
})

// ==================== DROPDOWN CLOSE ====================
function onDocumentClick(e) {
  if (strategyDropdownOpen.value && !e.target.closest('.strategy-dropdown-wrapper')) {
    strategyDropdownOpen.value = false
  }
  if (tagDropdownOpen.value && !e.target.closest('.tag-dropdown-wrapper')) {
    tagDropdownOpen.value = false
  }
  if (showSortMenu.value && !e.target.closest('.ledger-sort-wrapper')) {
    showSortMenu.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

// ==================== MOBILE SORT MENU ====================
const showSortMenu = ref(false)
const sortOptions = [
  { key: 'underlying', label: 'Symbol' },
  { key: 'strategy_label', label: 'Strategy' },
  { key: 'status', label: 'Status' },
  { key: 'opening_date', label: 'Opened' },
  { key: 'closing_date', label: 'Closed' },
  { key: 'initial_premium', label: 'Initial Premium' },
  { key: 'realized_pnl', label: 'Realized P&L' },
  { key: 'return_percent', label: '% Return' },
]
function toggleSortMenu(e) {
  e?.stopPropagation()
  showSortMenu.value = !showSortMenu.value
}
function selectSort(key) {
  sortGroups(key)
  showSortMenu.value = false
}
function closeSortMenu() { showSortMenu.value = false }

useBackDismiss(showSortMenu, closeSortMenu)

// Back-gesture dismiss for the roll chain modal
const rollChainOpen = computed(() => !!rollChainModal.value)
useBackDismiss(rollChainOpen, () => { rollChainModal.value = null })

// Contract count per group: GCD of (preferably open) option leg quantities
function gcd(a, b) { a = Math.abs(a); b = Math.abs(b); while (b) { [a, b] = [b, a % b] }; return a }
// Aggregate header stats (recompute live as filters change)
const closedFilteredGroups = computed(() => filteredGroups.value.filter(g => g.status !== 'OPEN'))
const totalRealized = computed(() => filteredGroups.value.reduce((sum, g) => sum + (g.realized_pnl || 0), 0))
const winCount = computed(() => closedFilteredGroups.value.filter(g => (g.realized_pnl || 0) > 0).length)
const winRatePct = computed(() => {
  const n = closedFilteredGroups.value.length
  return n > 0 ? (winCount.value / n) * 100 : null
})
const weightedReturnPct = computed(() => {
  const closed = closedFilteredGroups.value
  let num = 0, den = 0
  for (const g of closed) {
    num += g.realized_pnl || 0
    den += Math.abs(groupInitialPremium(g) || 0)
  }
  return den > 0 ? (num / den) * 100 : null
})

function groupReturnPercent(group) {
  const basis = Math.abs(groupInitialPremium(group) || 0)
  if (!basis) return null
  return (group.realized_pnl / basis) * 100
}
function groupContractCount(group) {
  const legs = groupedOptionLegs(group).filter(l => l.instrument_type !== 'EQUITY')
  if (legs.length === 0) return null
  const openLegs = legs.filter(l => l.status === 'OPEN')
  const source = openLegs.length > 0 ? openLegs : legs
  const quantities = source.map(l => Math.abs(l.totalQuantity)).filter(q => q > 0)
  if (quantities.length === 0) return null
  return quantities.reduce((a, b) => gcd(a, b))
}

// Watch account store for changes from GlobalToolbar
watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

// Watch sync store — refetch when sync completes
watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) await fetchLedger()
})

// ==================== LIFECYCLE ====================
onMounted(async () => {
  await loadAccounts()

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

  selectedAccount.value = accountsStore.selectedAccount

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

  if (groupParam) {
    let target = filteredGroups.value.find(g => g.group_id === groupParam)
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
</script>

<template>
  <!-- Page-specific filters teleported to GlobalToolbar -->
  <Teleport to="#page-filters">
  <div class="bg-tv-panel border-b border-tv-border">
    <!-- Mobile Filters -->
    <div class="md:hidden">
      <!-- Row 1: Symbol + Date -->
      <div class="px-4 py-3 space-y-3 border-b border-tv-border/50">
        <!-- Symbol Filter -->
        <div class="relative w-full">
          <input type="text"
                 v-model="filterUnderlying"
                 @focus="$event.target.select()"
                 @keyup.enter="onSymbolFilterApply()"
                 @blur="onSymbolFilterApply()"
                 @input="filterUnderlying = filterUnderlying.toUpperCase(); onSymbolFilterApply()"
                 placeholder="Symbol"
                 class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted w-full"
                 :class="filterUnderlying ? 'pr-8' : ''">
          <button v-show="filterUnderlying"
                  @click="clearSymbolFilter()"
                  class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
            <i class="fas fa-times-circle"></i>
          </button>
        </div>

        <!-- Date Filter -->
        <div class="w-full">
          <DateFilter ref="dateFilterRef" storage-key="ledger_dateFilter" default-preset="Last 30 Days" @update="onDateFilterUpdate" />
        </div>
      </div>

      <!-- Row 2: Status + Rolls -->
      <div class="px-4 py-3 space-y-3 border-b border-tv-border/50">
        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Status</div>
          <div class="flex flex-wrap gap-2">
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
            <button @click="filterRollsOnly = !filterRollsOnly; applyFilters()"
                    :class="filterRollsOnly ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5">
              <i class="fas fa-link text-xs"></i>
              Rolls
            </button>
          </div>
        </div>

        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Direction</div>
          <div class="flex flex-wrap gap-2">
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
        </div>

        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Type</div>
          <div class="flex flex-wrap gap-2">
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
        </div>
      </div>

      <!-- Row 3: Strategy + Tags -->
      <div class="px-4 py-3">
        <div class="flex flex-col gap-2">
          <!-- Strategy Filter Dropdown -->
          <div class="relative strategy-dropdown-wrapper">
            <button @click="strategyDropdownOpen = !strategyDropdownOpen; tagDropdownOpen = false"
                    class="w-full px-3 py-2 text-sm border rounded transition-colors flex items-center justify-between"
                    :class="filterStrategy.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              <span class="flex items-center gap-1.5">
                <span>Strategy</span>
                <span v-if="filterStrategy.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ filterStrategy.length }}</span>
              </span>
              <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
            </button>
            <div v-if="strategyDropdownOpen"
                 class="mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 w-full max-h-64 overflow-y-auto">
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
                    class="w-full px-3 py-2 text-sm border rounded transition-colors flex items-center justify-between"
                    :class="filterTagIds.length ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              <span class="flex items-center gap-1.5">
                <span>Tags</span>
                <span v-if="filterTagIds.length" class="bg-tv-purple text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ filterTagIds.length }}</span>
              </span>
              <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
            </button>
            <div v-if="tagDropdownOpen"
                 class="mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 w-full max-h-64 overflow-y-auto">
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
    </div>

    <!-- Desktop Filters -->
    <div class="hidden md:block">
      <!-- Row 1: Symbol + Date -->
      <div class="px-4 py-2.5 flex flex-col md:flex-row items-center gap-5 border-b border-tv-border/50">
        <!-- Symbol Filter -->
        <div class="relative w-full md:w-[initial]">
          <input type="text"
                 v-model="filterUnderlying"
                 @focus="$event.target.select()"
                 @keyup.enter="onSymbolFilterApply()"
                 @blur="onSymbolFilterApply()"
                 @input="filterUnderlying = filterUnderlying.toUpperCase(); onSymbolFilterApply()"
                 placeholder="Symbol"
                 class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted w-full md:max-w-[300px]"
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
               class="fixed mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 min-w-[200px] max-h-64 overflow-y-auto">
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
               class="fixed mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 min-w-[180px] max-h-64 overflow-y-auto">
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
  </div>
  </Teleport>

  <!-- In-page content wrapper: clip horizontal overflow on mobile so no rogue child can spread the viewport -->
  <div class="overflow-x-clip md:overflow-visible">
  <!-- Stats Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center flex-wrap gap-x-4 gap-y-1 md:gap-x-6 text-xs md:text-base">
    <span class="text-tv-muted whitespace-nowrap">
      Groups: <span class="text-tv-text">{{ filteredGroups.length }}</span>
    </span>
    <span class="text-tv-muted whitespace-nowrap">
      Open: <span class="text-tv-green">{{ stats.openCount }}</span>
    </span>
    <span class="text-tv-muted whitespace-nowrap">
      Closed: <span class="text-tv-text">{{ stats.closedCount }}</span>
    </span>
    <!-- Force wrap to a 2nd row on mobile -->
    <span class="basis-full h-0 md:hidden"></span>
    <span class="text-tv-muted whitespace-nowrap">
      Realized:
      <span :class="totalRealized > 0 ? 'text-tv-green' : totalRealized < 0 ? 'text-tv-red' : 'text-tv-text'">
        ${{ formatNumber(totalRealized) }}
      </span>
      <InfoPopover>
        Sum of realized P&amp;L across every group in the current filter — including partial closes and rolls on still-open groups.
      </InfoPopover>
    </span>
    <span class="text-tv-muted whitespace-nowrap">
      Win:
      <span class="text-tv-text">{{ winRatePct != null ? formatNumber(winRatePct) + '%' : '\u2014' }}</span>
      <span v-if="winRatePct != null" class="text-tv-muted">({{ closedFilteredGroups.length }})</span>
      <InfoPopover>
        Percent of <strong>closed</strong> groups in the current filter with realized P&amp;L &gt; 0. The number in parentheses is how many closed groups went into the calculation.
      </InfoPopover>
    </span>
    <span class="text-tv-muted whitespace-nowrap">
      Wtd %:
      <span :class="weightedReturnPct > 0 ? 'text-tv-green' : weightedReturnPct < 0 ? 'text-tv-red' : 'text-tv-text'">
        {{ weightedReturnPct != null ? formatNumber(weightedReturnPct) + '%' : '\u2014' }}
      </span>
      <span v-if="weightedReturnPct != null" class="text-tv-muted">({{ closedFilteredGroups.length }})</span>
      <InfoPopover>
        <div class="mb-1"><strong>Weighted % return</strong> across closed groups in the current filter.</div>
        <div class="text-tv-muted">Formula: sum(realized P&amp;L) &divide; sum(|initial premium|) &times; 100. This is your actual return on capital deployed — unlike a simple average, it accounts for the size of each position.</div>
      </InfoPopover>
    </span>
  </div>

  <!-- Column Headers (desktop only) -->
  <div v-if="!loading && filteredGroups.length > 0"
       class="hidden md:flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
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
    <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sortGroups('return_percent')">
      % Return <span v-if="sortColumn === 'return_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '&#x25B2;' : '&#x25BC;' }}</span>
    </span>
  </div>

  <!-- /header block -->

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

  <!-- Desktop Group List -->
  <div v-else class="hidden md:block bg-tv-row border-x border-b border-tv-border">
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
          <span class="w-48 mr-4 relative">
            <template v-if="!group._editingStrategy">
              <span class="flex items-center group/strat">
                <span class="text-tv-muted text-base truncate flex-1 min-w-0">{{ group.strategy_label || '\u2014' }}<span v-if="groupContractCount(group)" class="text-tv-text ml-1">({{ groupContractCount(group) }})</span><span v-if="group.partially_rolled" class="text-tv-cyan cursor-help ml-0.5" title="Partially rolled — some legs have been rolled to different strikes or expirations">&#9432;</span></span>
                <span class="flex items-center gap-1.5 ml-1.5 flex-shrink-0">
                  <i class="fas fa-pencil-alt text-xs text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                     @click.stop="group._editingStrategy = true"
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
                     @click.stop
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
          </span>

          <!-- Notes indicator -->
          <span class="w-6 ml-3 flex items-center justify-center">
            <i v-if="getGroupNote(group)" class="fas fa-sticky-note text-tv-amber text-sm" title="Has notes"></i>
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

          <!-- % Return -->
          <span class="w-20 text-right ml-2 text-base"
                :class="groupReturnPercent(group) > 0 ? 'text-tv-green' : groupReturnPercent(group) < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ groupReturnPercent(group) != null ? formatNumber(groupReturnPercent(group)) + '%' : '' }}
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
                <span class="w-24 text-right ml-2">Exit Price</span>
                <span class="w-48 ml-3">Exit Type</span>
                <span class="w-20 text-right ml-2">Fees</span>
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
                    <span class="w-48 ml-3"></span>
                    <span class="w-20 text-right ml-2"></span>
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
                          :class="leg.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50'
                            : leg.expired ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                            : leg.exercised ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                            : leg.assigned ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50'
                            : 'bg-tv-muted/20 text-tv-muted border-tv-red/50'">
                      {{ leg.expired ? 'EXPIRED' : leg.exercised ? 'EXERCISED' : leg.assigned ? 'ASSIGNED' : leg.status }}
                    </span>
                    <span class="w-24 text-right text-tv-muted">${{ formatNumber(leg.avgEntryPrice) }}</span>
                    <span class="w-24 text-right text-tv-muted ml-2">{{ (leg.expired || leg.exercised || leg.assigned) ? '\u2014' : (leg.avgClosePrice != null ? '$' + formatNumber(leg.avgClosePrice) : '') }}</span>
                    <span class="w-48 ml-3 text-tv-muted text-xs truncate">{{ leg.closeStatus || '' }}</span>
                    <span class="w-20 text-right ml-2 text-tv-muted"
                          :class="leg.totalFees < 0 ? 'text-tv-red' : ''">
                      {{ leg.totalFees ? '$' + formatNumber(Math.abs(leg.totalFees)) : '' }}
                    </span>
                  </div>
                </div>
              </template>
            </div>

        </div>
      </div>
    </div>
  </div>

  <!-- Mobile sort button + dropdown teleported next to the filter button -->
  <Teleport to="#page-sort">
    <div class="ledger-sort-wrapper contents">
      <button @click="toggleSortMenu($event)"
              class="text-xs px-3 py-2 rounded border font-medium transition-colors min-h-[44px] min-w-[44px] md:hidden"
              :class="showSortMenu ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border active:bg-tv-border/30'"
              title="Sort groups">
        <i class="fas fa-arrow-down-wide-short text-[11px]"></i>
      </button>
      <div v-if="showSortMenu"
           @click.stop
           class="absolute right-0 top-full mt-2 z-50 bg-tv-panel border border-tv-border rounded-lg shadow-2xl py-1 w-52 md:hidden">
        <div class="text-[10px] uppercase tracking-wider text-tv-muted px-3 py-1.5 font-semibold border-b border-tv-border/50">Sort by</div>
        <button v-for="opt in sortOptions" :key="opt.key"
                @click="selectSort(opt.key)"
                class="w-full flex items-center justify-between px-3 py-2.5 text-sm text-tv-text active:bg-tv-border/30"
                :class="sortColumn === opt.key ? 'text-tv-blue' : ''">
          <span>{{ opt.label }}</span>
          <i v-if="sortColumn === opt.key"
             class="fas text-[10px]"
             :class="sortDirection === 'asc' ? 'fa-arrow-up' : 'fa-arrow-down'"></i>
        </button>
      </div>
    </div>
  </Teleport>

  <!-- Mobile Card List -->
  <div v-if="!loading && filteredGroups.length > 0" class="md:hidden px-2 py-2 space-y-2 overflow-x-hidden">
    <div v-for="group in filteredGroups" :key="'m-' + group.group_id" :id="'m-group-' + group.group_id"
         class="bg-tv-row border border-tv-border rounded-lg overflow-hidden min-w-0 max-w-full">
      <!-- Summary header (tap to expand) -->
      <div @click="onGroupHeaderClick(group)"
           class="px-3 py-3 cursor-pointer active:bg-tv-border/20 transition-colors min-w-0">
        <!-- Top row: account, symbol, status, indicators, chevron -->
        <div class="flex items-center gap-2 mb-1.5 min-w-0">
          <span class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                :class="getAccountBadgeClass(group.account_number)">
            {{ getAccountSymbol(group.account_number) }}
          </span>
          <span class="text-lg font-semibold text-tv-text truncate min-w-0">{{ group.underlying }}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0"
                :class="group.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-muted/20 text-tv-muted'">
            {{ group.status }}
          </span>
          <i v-if="group.has_roll_chain"
             @click.stop="rollChainModal = group.group_id"
             class="fas fa-link text-tv-blue text-[11px] cursor-pointer shrink-0"
             title="Roll chain"></i>
          <i v-if="getGroupNote(group)" class="fas fa-sticky-note text-tv-amber text-[11px] shrink-0" title="Has notes"></i>
          <i class="fas fa-chevron-right text-tv-muted text-[11px] ml-auto shrink-0 transition-transform duration-150"
             :class="{ 'rotate-90': group.expanded }"></i>
        </div>

        <!-- Strategy + tags -->
        <div class="flex flex-wrap items-center gap-1.5 mb-2 text-xs min-w-0">
          <span class="text-tv-muted truncate flex-1 min-w-0 basis-full sm:basis-auto">
            {{ group.strategy_label || '\u2014' }}<span v-if="groupContractCount(group)" class="text-tv-text ml-1">({{ groupContractCount(group) }})</span>
            <span v-if="group.partially_rolled" class="text-tv-cyan ml-0.5" title="Partially rolled">&#9432;</span>
          </span>
          <span v-for="tag in (group.tags || [])" :key="tag.id"
                class="text-[9px] px-1 py-0.5 rounded-full border shrink-0 leading-none"
                :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
            {{ tag.name }}
          </span>
        </div>

        <!-- Dates + P&L grid -->
        <div class="grid grid-cols-2 gap-x-2 gap-y-1.5 text-[11px] pt-2 border-t border-tv-border/30">
          <div>
            <div class="text-tv-muted uppercase tracking-wide">Opened</div>
            <div class="text-tv-text text-sm">{{ formatDate(group.opening_date) }}</div>
          </div>
          <div class="text-right">
            <div class="text-tv-muted uppercase tracking-wide">Closed</div>
            <div class="text-sm" :class="group.closing_date ? 'text-tv-text' : 'text-tv-muted'">
              {{ group.closing_date ? formatDate(group.closing_date) : '\u2014' }}
            </div>
          </div>
          <div>
            <div class="text-tv-muted uppercase tracking-wide">Initial Prem</div>
            <div class="text-sm"
                 :class="groupInitialPremium(group) > 0 ? 'text-tv-green' : groupInitialPremium(group) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ groupInitialPremium(group) ? '$' + formatNumber(groupInitialPremium(group)) : '\u2014' }}
            </div>
          </div>
          <div class="text-right">
            <div class="text-tv-muted uppercase tracking-wide">Realized P&amp;L</div>
            <div class="text-sm font-medium leading-tight"
                 :class="group.realized_pnl > 0 ? 'text-tv-green' : group.realized_pnl < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ group.realized_pnl ? '$' + formatNumber(group.realized_pnl) : '\u2014' }}
            </div>
            <div class="text-[11px] leading-tight"
                 :class="groupReturnPercent(group) > 0 ? 'text-tv-green' : groupReturnPercent(group) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ groupReturnPercent(group) != null ? formatNumber(groupReturnPercent(group)) + '%' : '' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Mobile expanded detail -->
      <div v-show="group.expanded" class="bg-tv-bg border-t border-tv-border/30 px-3 py-2 space-y-2">
        <!-- Notes -->
        <textarea :value="getGroupNote(group)"
                  @input="updateGroupNote(group, $event.target.value)"
                  @click.stop rows="2"
                  class="w-full bg-transparent text-tv-text text-xs border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                  placeholder="Add notes..."></textarea>

        <!-- Equity aggregate -->
        <div v-if="openEquityLots(group).length > 0"
             class="flex items-center justify-between text-xs py-1.5 border-t border-tv-border/30">
          <div class="flex items-center gap-2">
            <span class="font-medium" :class="equityAggregate(group).quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
              {{ equityAggregate(group).quantity }}
            </span>
            <span class="text-tv-muted">shares</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="text-[9px] px-1.5 py-0.5 rounded bg-tv-green/20 text-tv-green border border-tv-green/50">OPEN</span>
            <span class="text-tv-muted">@${{ formatNumber(equityAggregate(group).avgPrice) }}</span>
          </div>
        </div>

        <!-- Option legs -->
        <div v-for="leg in groupedOptionLegs(group)" :key="'m-leg-' + leg.key"
             class="flex items-center justify-between text-xs py-1.5 border-t border-tv-border/30">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="font-medium w-8 text-right shrink-0"
                  :class="leg.totalQuantity > 0 ? 'text-tv-green' : leg.totalQuantity < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ leg.totalQuantity }}
            </span>
            <span v-if="leg.expiration" class="text-tv-text">{{ formatExpirationShort(leg.expiration) }}</span>
            <span v-if="leg.strike" class="text-tv-text">{{ leg.strike }}</span>
            <span v-if="leg.option_type" class="text-tv-muted">{{ leg.option_type.toUpperCase().startsWith('C') ? 'C' : 'P' }}</span>
            <span v-if="!leg.expiration && leg.instrument_type === 'EQUITY'" class="text-tv-muted">Shares</span>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            <span class="text-[9px] px-1 py-0.5 rounded border"
                  :class="leg.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50'
                    : leg.expired ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                    : leg.exercised ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                    : leg.assigned ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50'
                    : 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'">
              {{ leg.expired ? 'EXP' : leg.exercised ? 'EX' : leg.assigned ? 'ASN' : leg.status }}
            </span>
            <span class="text-tv-muted">${{ formatNumber(leg.avgEntryPrice) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Bottom spacer (desktop only — lets the last row scroll comfortably above the fold) -->
  <div class="hidden md:block h-96"></div>
  </div><!-- /in-page content wrapper -->

  <!-- Roll Chain Modal -->
  <RollChainModal
    :group-id="rollChainModal"
    :underlying="groups.find(g => g.group_id === rollChainModal)?.underlying || ''"
    @close="rollChainModal = null"
  />

</template>
