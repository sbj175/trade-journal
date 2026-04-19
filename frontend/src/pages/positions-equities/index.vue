<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber } from '@/lib/formatters'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useQuotesStore } from '@/stores/quotes'
import { useEquityQuotes } from '@/composables/useEquityQuotes'
import { useEquityPositions } from '@/composables/useEquityPositions'
import EquitiesDesktopHeader from '@/components/EquitiesDesktopHeader.vue'
import EquitiesDesktopRow from '@/components/EquitiesDesktopRow.vue'
import EquitiesMobileCard from '@/components/EquitiesMobileCard.vue'

const Auth = useAuth()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()
const quotesStore = useQuotesStore()

// Circular dependency: useEquityQuotes needs filteredItems (from positions),
// useEquityPositions needs quote accessors (from quotes). Broken via lazy getter
// -- the getter closure is only invoked at runtime, after both composables exist.

const {
  quoteUpdateCounter, liveQuotesActive, lastQuoteUpdate,
  getQuote, getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent,
  getLotMarketValue, getLotPnL,
  loadCachedQuotes, initializeWebSocket, closeWebSocket,
} = useEquityQuotes(Auth, { get value() { return filteredItems.value } })

const {
  accounts, selectedAccount, selectedUnderlying,
  isLoading, error, expandedRows,
  filteredItems, groupedPositions, totalCostBasis, totalMarketValue, totalPnL,
  fetchAccounts, loadPositions,
  getAccountSymbol,
  toggleExpanded, sort, sortColumn, sortDirection, sortIcon, onAccountChange,
} = useEquityPositions(Auth, {
  getQuote, getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent,
  getLotMarketValue, getLotPnL, quoteUpdateCounter,
})

// --- Mobile sort menu ---
const showSortMenu = ref(false)
const sortOptions = [
  { key: 'underlying', label: 'Symbol' },
  { key: 'quantity', label: 'Shares' },
  { key: 'avg_price', label: 'Avg Price' },
  { key: 'cost_basis', label: 'Cost Basis' },
  { key: 'market_value', label: 'Mkt Value' },
  { key: 'pnl', label: 'P&L' },
  { key: 'pnl_percent', label: 'P&L %' },
]
function toggleSortMenu(e) {
  e?.stopPropagation()
  showSortMenu.value = !showSortMenu.value
}
function selectSort(key) {
  sort(key)
  showSortMenu.value = false
}
function closeSortMenu() { showSortMenu.value = false }

useBackDismiss(showSortMenu, closeSortMenu)

watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

watch(lastQuoteUpdate, (val) => {
  quotesStore.setLastQuoteUpdate(val)
})

watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) {
    await loadPositions()
    await loadCachedQuotes()
  }
})

onMounted(async () => {
  document.addEventListener('click', closeSortMenu)
  selectedAccount.value = accountsStore.selectedAccount
  await fetchAccounts()
  await loadPositions()
  await loadCachedQuotes()
  await initializeWebSocket()
})

onUnmounted(() => {
  document.removeEventListener('click', closeSortMenu)
  closeWebSocket()
})
</script>

<template>
  <Teleport to="#page-filters">
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2.5 flex items-center gap-4">
      <div class="relative w-full">
        <input type="text"
               :value="selectedUnderlying"
               @input="selectedUnderlying = $event.target.value.toUpperCase()"
               @focus="$event.target.select()"
               placeholder="Symbol"
               maxlength="5"
               class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted w-full md:max-w-[300px]"
               :class="selectedUnderlying ? 'pr-8' : ''">
        <button v-show="selectedUnderlying"
                @click="selectedUnderlying = ''"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text"
                title="Clear symbol filter">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>
    </div>
  </Teleport>

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
              :class="sortIcon(opt.key) ? 'text-tv-blue' : ''">
        <span>{{ opt.label }}</span>
        <span v-if="sortIcon(opt.key)" class="text-[11px]">{{ sortIcon(opt.key) }}</span>
      </button>
    </div>
  </Teleport>

  <!-- Stats Bar -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2 grid grid-cols-2 gap-x-4 gap-y-1 md:flex md:items-center md:gap-x-8 text-xs md:text-base">
    <span class="text-tv-muted">
      Positions: <span class="text-tv-text">{{ filteredItems.length }}</span>
    </span>
    <span class="text-tv-muted">
      Cost: <span class="text-tv-text">${{ formatNumber(totalCostBasis) }}</span>
    </span>
    <span class="text-tv-muted">
      <span class="hidden md:inline">Market Value</span><span class="md:hidden">Mkt</span>:
      <span class="text-tv-text">${{ formatNumber(totalMarketValue) }}</span>
    </span>
    <span class="text-tv-muted">
      <span class="hidden md:inline">Unrealized </span>P&amp;L:
      <span :class="totalPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(totalPnL) }}</span>
    </span>
  </div>

  <!-- Column Headers (desktop only) -->
  <EquitiesDesktopHeader
    v-show="!isLoading && groupedPositions.length > 0"
    :sort-column="sortColumn"
    :sort-direction="sortDirection"
    @sort="sort"
  />

  <!-- Loading State -->
  <div v-if="isLoading" class="text-center py-16">
    <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
    <p class="text-tv-muted">Loading equity positions...</p>
  </div>

  <!-- Empty State -->
  <div v-else-if="groupedPositions.length === 0" class="text-center py-16">
    <i class="fas fa-layer-group text-3xl text-tv-muted mb-3"></i>
    <p class="text-tv-muted">No equity positions found.</p>
  </div>

  <template v-else>
    <!-- Desktop Position List -->
    <div class="hidden md:block bg-tv-row border-x border-b border-tv-border">
      <div class="divide-y divide-tv-border">
        <EquitiesDesktopRow
          v-for="item in groupedPositions"
          :key="item.groupId"
          :item="item"
          :selected-account="selectedAccount"
          :accounts="accounts"
          :expanded-rows="expandedRows"
          :get-account-symbol="getAccountSymbol"
          @toggle-expanded="toggleExpanded"
        />
      </div>
    </div>

    <!-- Mobile Card List -->
    <div class="md:hidden px-2 py-2 space-y-2">
      <EquitiesMobileCard
        v-for="item in groupedPositions"
        :key="'m-' + item.groupId"
        :item="item"
        :selected-account="selectedAccount"
        :accounts="accounts"
        :expanded-rows="expandedRows"
        :get-account-symbol="getAccountSymbol"
        @toggle-expanded="toggleExpanded"
      />
    </div>
  </template>

  <div class="h-96"></div>
</template>
