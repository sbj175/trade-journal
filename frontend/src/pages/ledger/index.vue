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

// Aggregate header stats — event-sourced when a date filter is active.
//
// Without a date filter, totals fall through to the group-level rollups (same
// as before). When a date filter is active, we sum closing events whose
// closing_date falls inside the window — so monthly sums reconcile to range
// sums, and a group spanning multiple months gets apportioned across them
// instead of being counted in full inside every window it touches.
const dateFilterActive = computed(() => !!(dateFrom.value || dateTo.value))

const closedFilteredGroups = computed(() => filteredGroups.value.filter(g => g.status !== 'OPEN'))

// Realized in window per group: sum of closings whose closing_date lies in
// [dateFrom, dateTo]. Returns the group's full realized_pnl when no filter.
function groupInWindowRealized(g) {
  if (!dateFilterActive.value) return g.realized_pnl || 0
  const from = dateFrom.value ? new Date(dateFrom.value + 'T00:00:00') : null
  const to = dateTo.value ? new Date(dateTo.value + 'T23:59:59') : null
  let sum = 0
  for (const lot of g.lots || []) {
    for (const c of lot.closings || []) {
      if (!c.closing_date) continue
      const d = new Date(c.closing_date)
      if (from && d < from) continue
      if (to && d > to) continue
      sum += c.realized_pnl || 0
    }
  }
  return sum
}

const totalRealized = computed(() =>
  filteredGroups.value.reduce((sum, g) => sum + groupInWindowRealized(g), 0)
)

// Win % and Wtd % scope: groups with closing activity inside the window. When
// no date filter is active, fall back to the previous "all closed groups in
// filter" scope so behavior matches today.
const winRateScope = computed(() => {
  if (!dateFilterActive.value) return closedFilteredGroups.value
  return filteredGroups.value.filter(g => {
    // A group is in scope if it has at least one closing event in the window.
    for (const lot of g.lots || []) {
      for (const c of lot.closings || []) {
        if (!c.closing_date) continue
        const d = new Date(c.closing_date)
        const from = dateFrom.value ? new Date(dateFrom.value + 'T00:00:00') : null
        const to = dateTo.value ? new Date(dateTo.value + 'T23:59:59') : null
        if (from && d < from) continue
        if (to && d > to) continue
        return true
      }
    }
    return false
  })
})

const winCount = computed(() => {
  if (!dateFilterActive.value) {
    return closedFilteredGroups.value.filter(g => (g.realized_pnl || 0) > 0).length
  }
  return winRateScope.value.filter(g => groupInWindowRealized(g) > 0).length
})
const winRatePct = computed(() => {
  const n = winRateScope.value.length
  return n > 0 ? (winCount.value / n) * 100 : null
})

const weightedReturnPct = computed(() => {
  const scope = winRateScope.value
  let num = 0, den = 0
  for (const g of scope) {
    num += groupInWindowRealized(g)
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
    <div class="bg-tv-panel border-b border-tv-border px-5 py-2 flex items-center flex-wrap gap-x-4 gap-y-1 md:gap-x-6 text-xs md:text-base">
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
          <template v-if="dateFilterActive">
            Sum of realized P&amp;L from closing events whose <strong>close date</strong> falls inside the selected window. Monthly totals will add up to the same range as a single query.
          </template>
          <template v-else>
            Sum of realized P&amp;L across every group in the current filter — including partial closes and rolls on still-open groups.
          </template>
        </InfoPopover>
      </span>
      <span class="text-tv-muted whitespace-nowrap md:relative md:bottom-[-2px]">
        Win:
        <span class="text-tv-text">{{ winRatePct != null ? formatNumber(winRatePct) + '%' : '\u2014' }}</span>
        <span v-if="winRatePct != null" class="text-tv-muted">({{ winRateScope.length }})</span>
        <InfoPopover>
          <template v-if="dateFilterActive">
            Percent of groups whose closing activity inside the window netted positive realized P&amp;L. The number in parentheses is how many groups had closings in the window.
          </template>
          <template v-else>
            Percent of <strong>closed</strong> groups in the current filter with realized P&amp;L &gt; 0. The number in parentheses is how many closed groups went into the calculation.
          </template>
        </InfoPopover>
      </span>
      <span class="text-tv-muted whitespace-nowrap md:relative md:bottom-[-2px]">
        Wtd %:
        <span :class="weightedReturnPct > 0 ? 'text-tv-green' : weightedReturnPct < 0 ? 'text-tv-red' : 'text-tv-text'">
          {{ weightedReturnPct != null ? formatNumber(weightedReturnPct) + '%' : '\u2014' }}
        </span>
        <span v-if="weightedReturnPct != null" class="text-tv-muted">({{ winRateScope.length }})</span>
        <InfoPopover>
          <div class="mb-1"><strong>Weighted % return</strong><template v-if="dateFilterActive"> on groups with closing activity in the window</template><template v-else> across closed groups in the current filter</template>.</div>
          <div class="text-tv-muted">Formula: sum(realized P&amp;L<template v-if="dateFilterActive"> in window</template>) &divide; sum(|initial premium|) &times; 100. This is your actual return on capital deployed — unlike a simple average, it accounts for the size of each position.</div>
        </InfoPopover>
      </span>
    </div>

    <!-- Scope caption: makes the list-vs-totals split explicit when a date filter is active -->
    <div v-if="dateFilterActive"
         class="bg-tv-panel/60 border-b border-tv-border px-5 py-1 text-[11px] text-tv-muted leading-tight">
      Totals reflect closing activity inside the selected window. The list below shows groups that touched the window for any reason (opening, rolling, partial close, or close).
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
      <div class="hidden md:block text-center py-3">
        <span class="text-[11px] text-tv-muted/40">Logos by <a href="https://logokit.com" target="_blank" rel="noopener" class="hover:text-tv-muted/60">LogoKit</a></span>
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
      <div class="md:hidden p-4 space-y-2 overflow-x-hidden">
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
      <div class="md:hidden text-center py-3">
        <span class="text-[11px] text-tv-muted/40">Logos by <a href="https://logokit.com" target="_blank" rel="noopener" class="hover:text-tv-muted/60">LogoKit</a></span>
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
