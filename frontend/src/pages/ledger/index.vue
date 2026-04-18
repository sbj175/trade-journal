<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber } from '@/lib/formatters'
import { DEFAULT_TAG_COLOR } from '@/lib/constants'
import DateFilter from '@/components/DateFilter.vue'
import RollChainModal from '@/components/RollChainModal.vue'
import InfoPopover from '@/components/InfoPopover.vue'
import LedgerDesktopHeader from '@/components/LedgerDesktopHeader.vue'
import LedgerDesktopRow from '@/components/LedgerDesktopRow.vue'
import LedgerMobileCard from '@/components/LedgerMobileCard.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useLedgerGroups } from '@/composables/useLedgerGroups'

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

const notesState = { getGroupNote, updateGroupNote }
const tagsState = {
  tagPopoverGroup, tagSearch, filteredTagSuggestions,
  openTagPopover, closeTagPopover,
  addTagToGroup, removeTagFromGroup, handleTagInput,
}

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

const rollChainOpen = computed(() => !!rollChainModal.value)
useBackDismiss(rollChainOpen, () => { rollChainModal.value = null })

// Aggregate header stats
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
    den += Math.abs(g.initialPremium || 0)
  }
  return den > 0 ? (num / den) * 100 : null
})

watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

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
                <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: tag.color || DEFAULT_TAG_COLOR }"></span>
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
        <DateFilter ref="dateFilterRef" storage-key="ledger_dateFilter" default-preset="Last 30 Days" @update="onDateFilterUpdate" />
      </div>

      <!-- Row 2: Direction, Type, Status, Rolls, Strategy, Tags -->
      <div class="px-4 py-2.5 flex items-center gap-6">
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

        <button @click="filterRollsOnly = !filterRollsOnly; applyFilters()"
                :class="filterRollsOnly ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5">
          <i class="fas fa-link text-xs"></i>
          Rolls
        </button>

        <div class="w-px h-6 bg-tv-border"></div>

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
              <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: tag.color || DEFAULT_TAG_COLOR }"></span>
              <span :class="filterTagIds.includes(tag.id) ? 'text-tv-text' : 'text-tv-muted'">{{ tag.name }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
  </Teleport>

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

    <!-- Loading State -->
    <div v-if="loading" class="text-center py-16">
      <div class="spinner mx-auto mb-4 w-8 h-8 border-[3px]"></div>
      <p class="text-tv-muted">Loading ledger data...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="filteredGroups.length === 0" class="text-center py-16">
      <i class="fas fa-book-open text-3xl text-tv-muted mb-3"></i>
      <p class="text-tv-muted">No position groups found.</p>
      <p class="text-tv-muted mt-2">Sync your data from the <router-link to="/positions" class="text-tv-blue hover:underline">Positions</router-link> page first.</p>
    </div>

    <template v-else>
      <!-- Desktop -->
      <div class="hidden md:block bg-tv-row border-x border-b border-tv-border">
        <LedgerDesktopHeader
          :sort-column="sortColumn"
          :sort-direction="sortDirection"
          @sort="sortGroups"
        />
        <div class="divide-y divide-tv-border">
          <div v-for="group in filteredGroups" :key="group.group_id" :id="'group-' + group.group_id">
            <LedgerDesktopRow
              :group="group"
              :selected-account="selectedAccount"
              :accounts="accounts"
              :notes-state="notesState"
              :tags-state="tagsState"
              :get-account-symbol="getAccountSymbol"
              :update-group-strategy="updateGroupStrategy"
              @toggle-expanded="onGroupHeaderClick(filteredGroups.find(g => g.group_id === $event))"
              @open-roll-chain="rollChainModal = $event"
            />
          </div>
        </div>
      </div>

      <!-- Mobile sort button + dropdown -->
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
      <div class="md:hidden px-2 py-2 space-y-2 overflow-x-hidden">
        <LedgerMobileCard
          v-for="group in filteredGroups"
          :key="'m-' + group.group_id"
          :group="group"
          :selected-account="selectedAccount"
          :accounts="accounts"
          :notes-state="notesState"
          :get-account-symbol="getAccountSymbol"
          @toggle-expanded="onGroupHeaderClick(filteredGroups.find(g => g.group_id === $event))"
          @open-roll-chain="rollChainModal = $event"
        />
      </div>
    </template>

    <div class="hidden md:block h-96"></div>
  </div>

  <!-- Roll Chain Modal -->
  <RollChainModal
    :group-id="rollChainModal"
    :underlying="groups.find(g => g.group_id === rollChainModal)?.underlying || ''"
    @close="rollChainModal = null"
  />
</template>
