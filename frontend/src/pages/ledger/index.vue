<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber } from '@/lib/formatters'
import RollChainModal from '@/components/RollChainModal.vue'
import InfoPopover from '@/components/InfoPopover.vue'
import LedgerFilters from '@/components/LedgerFilters.vue'
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
const filterStrategy = ref([])
const filterTagIds = ref([])

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

// Bundled for LedgerFilters
const filterState = {
  filterUnderlying, showOpen, showClosed, filterRollsOnly,
  filterDirection, filterType, filterStrategy, filterTagIds,
}
const filterHandlers = {
  onSymbolFilterApply, clearSymbolFilter, onDateFilterUpdate,
  applyFilters, saveState, toggleFilter, toggleStrategyFilter, toggleTagFilter,
}

// ==================== MOBILE SORT MENU ====================
const showSortMenu = ref(false)
const ledgerFiltersRef = ref(null)

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

function onDocumentClick(e) {
  if (showSortMenu.value && !e.target.closest('.ledger-sort-wrapper')) {
    showSortMenu.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

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
      ledgerFiltersRef.value?.clearDateFilter()
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
  <Teleport to="#page-filters">
    <LedgerFilters
      ref="ledgerFiltersRef"
      :filter-state="filterState"
      :handlers="filterHandlers"
      :unique-strategies="uniqueStrategies"
      :available-tags="availableTags"
    />
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
      
      <span class="text-tv-muted whitespace-nowrap md:relative md:bottom-[-2px]">
        Realized:
        <span :class="totalRealized > 0 ? 'text-tv-green' : totalRealized < 0 ? 'text-tv-red' : 'text-tv-text'">
          ${{ formatNumber(totalRealized) }}
        </span>
        <InfoPopover>
          Sum of realized P&amp;L across every group in the current filter — including partial closes and rolls on still-open groups.
        </InfoPopover>
      </span>
      <span class="text-tv-muted whitespace-nowrap md:relative md:bottom-[-2px]">
        Win:
        <span class="text-tv-text">{{ winRatePct != null ? formatNumber(winRatePct) + '%' : '\u2014' }}</span>
        <span v-if="winRatePct != null" class="text-tv-muted">({{ closedFilteredGroups.length }})</span>
        <InfoPopover>
          Percent of <strong>closed</strong> groups in the current filter with realized P&amp;L &gt; 0. The number in parentheses is how many closed groups went into the calculation.
        </InfoPopover>
      </span>
      <span class="text-tv-muted whitespace-nowrap md:relative md:bottom-[-2px]">
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
