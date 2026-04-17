<script setup>
defineOptions({ name: 'PositionsOptions' })
import { onMounted, onUnmounted, onActivated, onDeactivated, ref, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import RollChainModal from '@/components/RollChainModal.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useQuotesStore } from '@/stores/quotes'

import { usePositionsData } from './usePositionsData'
import { usePositionsNotes } from './usePositionsNotes'
import { getAccountSymbol as getAccountSymbolPure } from './usePositionsDisplay'
import PositionsMobileCard from './PositionsMobileCard.vue'
import PositionsDesktopRow from './PositionsDesktopRow.vue'
import { formatDollar, dollarSizeClass } from './usePositionsDisplay'

function debounce(fn, ms) {
  let t
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms) }
}

const Auth = useAuth()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()
const quotesStore = useQuotesStore()

// --- Wire composables ---

const {
  allChains, allItems, filteredItems, accounts,
  underlyingQuotes, quoteUpdateCounter,
  selectedAccount, selectedUnderlying,
  isLoading, isSyncing, error, liveQuotesActive, lastQuoteUpdate, syncSummary,
  rollAnalysisMode,
  sortColumn, sortDirection, expandedRows,
  groupedPositions, underlyings,
  toggleRollAnalysisMode, toggleExpanded,
  fetchAccounts, fetchPositions, loadCachedQuotes,
  initializeWebSocket, requestLiveQuotes, cleanupWebSocket,
  applyFilters, filterPositions, saveFilterPreferences, loadFilterPreferences,
  onAccountChange, onSymbolFilterCommit: onSymbolFilterCommitImmediate,
  sortPositions,
  calculateLegMarketValue, calculateLegPnL,
  hasEquity, calculateEquityMarketValue,
  loadStrategyTargets, loadRollAlertSettings,
} = usePositionsData(Auth)

const onSymbolFilterCommit = debounce(onSymbolFilterCommitImmediate, 300)
const onSymbolFilterCommitNow = onSymbolFilterCommitImmediate

const {
  positionComments,
  availableTags, tagPopoverGroup, tagSearch,
  filteredTagSuggestions,
  loadComments, migrateCommentKeys, getPositionComment, updatePositionComment,
  cleanupNoteTimers,
  loadAvailableTags, openTagPopover, closeTagPopover,
  addTagToGroup, removeTagFromGroup, handleTagInput,
  onDocumentClick,
} = usePositionsNotes(Auth, { allItems })


const rollChainModal = ref(null)
const rollChainUnderlying = ref('')
const rollChainGroup = ref(null)

// --- Mobile sort menu ---
const showSortMenu = ref(false)
const sortOptions = [
  { key: 'underlying', label: 'Symbol' },
  { key: 'strategy', label: 'Strategy' },
  { key: 'dte', label: 'DTE' },
  { key: 'ivr', label: 'IV Rank' },
  { key: 'price', label: 'Price' },
  { key: 'cost_basis', label: 'Cost Basis' },
  { key: 'net_liq', label: 'Net Liq' },
  { key: 'open_pnl', label: 'Open P&L' },
  { key: 'pnl_percent', label: 'P&L %' },
]
function toggleSortMenu(e) {
  e?.stopPropagation()
  showSortMenu.value = !showSortMenu.value
}
function selectSort(key) {
  sortPositions(key)
  showSortMenu.value = false
}
function closeSortMenu() { showSortMenu.value = false }

useBackDismiss(showSortMenu, closeSortMenu)

function openRollChainModal(group) {
  rollChainModal.value = group.group_id
  rollChainUnderlying.value = group.underlying
  rollChainGroup.value = group
}

// --- Thin wrappers for template (adapt pure functions to reactive state) ---

const noteCallbacks = { migrateCommentKeysFn: migrateCommentKeys, loadCommentsFn: loadComments }
let lastPositionsFetchAt = 0

async function syncPositions() {
  await syncStore.performSync()
  await fetchPositions(false, noteCallbacks)
  await loadCachedQuotes()
  lastPositionsFetchAt = Date.now()
  requestLiveQuotes()
}

function getAccountSymbol(accountNumber) {
  return getAccountSymbolPure(accounts.value, accountNumber)
}

const notesState = {
  getPositionComment,
  updatePositionComment,
}

const tagsState = {
  tagPopoverGroup,
  tagSearch,
  filteredTagSuggestions,
  openTagPopover,
  closeTagPopover,
  addTagToGroup,
  removeTagFromGroup,
  handleTagInput,
}

// Watch account store for changes from GlobalToolbar
watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

// Push quote timestamps to the quotes store
watch(lastQuoteUpdate, (val) => {
  quotesStore.setLastQuoteUpdate(val)
})

// Watch sync store — if another page triggers sync, refetch
watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) {
    await fetchPositions(false, noteCallbacks)
    await loadCachedQuotes()
    requestLiveQuotes()
  }
})

// --- Lifecycle ---

onMounted(async () => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('click', closeSortMenu)

  // Sync selectedAccount from store
  selectedAccount.value = accountsStore.selectedAccount

  await loadComments()
  loadRollAlertSettings()
  await fetchAccounts()
  await loadStrategyTargets()
  loadFilterPreferences()
  await fetchPositions(false, noteCallbacks)
  await loadCachedQuotes()
  lastPositionsFetchAt = Date.now()
  await loadAvailableTags()
  initializeWebSocket()
})

onActivated(async () => {
  initializeWebSocket()
  requestLiveQuotes()
  const stale = Date.now() - lastPositionsFetchAt > 10_000
  if (stale) {
    await fetchPositions(false, noteCallbacks)
    await loadCachedQuotes()
    lastPositionsFetchAt = Date.now()
  }
})

onDeactivated(() => {
  cleanupWebSocket()
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('click', closeSortMenu)
})

onUnmounted(() => {
  cleanupWebSocket()
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('click', closeSortMenu)
  cleanupNoteTimers()
})
</script>

<template>
  <Teleport to="#page-filters">
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2.5 flex items-center gap-4 ">
      <!-- Symbol Filter -->
      <div class="relative w-full">
        <input type="text"
               :value="selectedUnderlying"
               @input="selectedUnderlying = $event.target.value.toUpperCase(); onSymbolFilterCommit()"
               @focus="$event.target.select()"
               @keyup.enter="onSymbolFilterCommitNow()"
               @blur="selectedUnderlying = selectedUnderlying.trim(); onSymbolFilterCommitNow()"
               placeholder="Symbol"
               maxlength="5"
               class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted w-full md:max-w-[300px]"
               :class="selectedUnderlying ? 'pr-8' : ''">
        <button v-show="selectedUnderlying"
                @click="selectedUnderlying = ''; onSymbolFilterCommitNow()"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text"
                title="Clear symbol filter">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>
    </div>
  </Teleport>

  <!-- Mobile sort button + dropdown teleported next to the filter button -->
  <Teleport to="#page-sort">
    <button @click="toggleSortMenu($event)"
            class="text-xs px-3 py-2 rounded border font-medium transition-colors min-h-[44px] min-w-[44px] md:hidden"
            :class="showSortMenu ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border active:bg-tv-border/30'"
            title="Sort positions">
      <i class="fas fa-arrow-down-wide-short text-[11px]"></i>
    </button>
    <div v-if="showSortMenu"
         @click.stop
         class="absolute right-0 top-full mt-2 z-50 bg-tv-panel border border-tv-border rounded-lg shadow-2xl py-1 w-48 md:hidden">
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
  </Teleport>

   <!-- Column headers block -->
  <div>

  <!-- Loading State -->
  <div v-show="isLoading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading positions...</p>
  </div>

  <!-- Empty State -->
  <div v-show="!isLoading && !error && filteredItems.length === 0" class="text-center py-16">
    <i class="fas fa-layer-group text-3xl text-tv-muted mb-3"></i>
    <p class="text-tv-muted">No open positions found</p>
  </div>

  <!-- Column Headers (desktop only) -->
  <div v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0"
       class="hidden md:flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <span class="w-16"></span>
    <span class="w-6 text-center" v-show="selectedAccount === ''"></span>
    <span class="w-28 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('underlying')">
      Symbol
      <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-16 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 mr-1" @click="sortPositions('ivr')">
      IVR
      <span v-show="sortColumn === 'ivr'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-40 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('price')">
      Price
      <span v-show="sortColumn === 'price'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-10"></span>
    <span class="w-40 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('strategy')">
      Strategy
      <span v-show="sortColumn === 'strategy'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-10 text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1" @click="sortPositions('dte')">
      DTE
      <span v-show="sortColumn === 'dte'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('cost_basis')">
      Cost Basis
      <span v-show="sortColumn === 'cost_basis'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('net_liq')">
      Net Liq
      <span v-show="sortColumn === 'net_liq'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('open_pnl')">
      Open P&L
      <span v-show="sortColumn === 'open_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('pnl_percent')"
          title="Return on capital: Total P&L ÷ Cost Basis. Measures how much you've made or lost relative to what you put in.">
      % Rtn
      <span v-show="sortColumn === 'pnl_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-16 text-center"></span>
    <span class="w-[250px] text-right">Tags / Signals</span>
  </div>

  </div><!-- /column headers block -->

  <!-- Mobile Card View -->
  <div v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0"
       class="md:hidden px-2 py-2 space-y-2 overflow-x-hidden">
    <PositionsMobileCard
      v-for="group in groupedPositions"
      :key="'m-' + group.groupKey"
      :group="group"
      :selected-account="selectedAccount"
      :accounts="accounts"
      :expanded-rows="expandedRows"
      :notes-state="notesState"
      :tags-state="tagsState"
      :calculate-leg-pnl="calculateLegPnL"
      :has-equity="hasEquity"
      :get-account-symbol="getAccountSymbol"
      @open-roll-chain="openRollChainModal"
      @toggle-expanded="toggleExpanded"
    />
    <div class="text-center py-3">
      <span class="text-[11px] text-tv-muted/40">Logos by <a href="https://logokit.com" target="_blank" rel="noopener" class="hover:text-tv-muted/60">LogoKit</a></span>
    </div>
  </div>

  <!-- Desktop Main Content -->
  <main v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0"
        class="hidden md:block">
   <div class="bg-tv-row border-x border-b border-tv-border">
    <!-- Position Groups -->
    <div class="divide-y divide-tv-border">
      <div v-for="group in groupedPositions" :key="group.groupKey">
        <!-- Subtotal Row -->
        <div v-if="group._isSubtotal" class="flex items-center px-4 h-12 bg-tv-blue/10 border-l-2 border-tv-blue">
          <div class="w-16"></div>
          <div class="w-14">
            <div class="font-bold text-base text-tv-text">{{ group.displayKey }}</div>
          </div>
          <div class="w-16 mr-1"></div>
          <div class="w-40"></div>
          <div class="w-10"></div>
          <div class="w-40 text-xs text-tv-muted">{{ group._childCount }} positions</div>
          <div class="w-10"></div>
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalCostBasis >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalCostBasis)">
            <span v-show="group._subtotalCostBasis < 0">-</span>${{ formatDollar(group._subtotalCostBasis) }}
          </div>
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalNetLiq >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalNetLiq)">
            <span v-show="group._subtotalNetLiq < 0">-</span>${{ formatDollar(group._subtotalNetLiq) }}
          </div>
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalOpenPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalOpenPnL)">
            <span v-show="group._subtotalOpenPnL < 0">-</span>${{ formatDollar(group._subtotalOpenPnL) }}
          </div>
          <div class="w-20"></div>
          <div class="w-16"></div>
          <div class="w-[250px]"></div>
        </div>
        <!-- Regular Row -->
        <PositionsDesktopRow
          v-else
          :group="group"
          :selected-account="selectedAccount"
          :accounts="accounts"
          :expanded-rows="expandedRows"
          :roll-analysis-mode="rollAnalysisMode"
          :notes-state="notesState"
          :tags-state="tagsState"
          :calculate-leg-market-value="calculateLegMarketValue"
          :calculate-leg-pnl="calculateLegPnL"
          :calculate-equity-market-value="calculateEquityMarketValue"
          :has-equity="hasEquity"
          :get-account-symbol="getAccountSymbol"
          @open-roll-chain="openRollChainModal"
          @toggle-expanded="toggleExpanded"
          @toggle-roll-analysis-mode="toggleRollAnalysisMode"
        />
      </div>
    </div>
   </div>
    <div class="text-center py-3">
      <span class="text-[11px] text-tv-muted/40">Logos by <a href="https://logokit.com" target="_blank" rel="noopener" class="hover:text-tv-muted/60">LogoKit</a></span>
    </div>
  </main>

  <!-- Roll Chain Modal -->
  <RollChainModal
    :group-id="rollChainModal"
    :underlying="rollChainUnderlying"
    :open-pnl="rollChainGroup ? rollChainGroup.openPnL : null"
    @close="rollChainModal = null; rollChainGroup = null"
  />
</template>
