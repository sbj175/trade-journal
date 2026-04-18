<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useBackDismiss } from '@/composables/useBackDismiss'
import { formatNumber, formatDate, pnlColorClass } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import StreamingPrice from '@/components/StreamingPrice.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useQuotesStore } from '@/stores/quotes'
import { useEquityQuotes } from '@/composables/useEquityQuotes'
import { useEquityPositions } from '@/composables/useEquityPositions'

const Auth = useAuth()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()
const quotesStore = useQuotesStore()

// Circular dependency: useEquityQuotes needs filteredItems (from positions),
// useEquityPositions needs quote accessors (from quotes). Broken via lazy getter
// -- the getter closure is only invoked at runtime, after both composables exist.

const {
  underlyingQuotes, quoteUpdateCounter, liveQuotesActive, lastQuoteUpdate,
  getQuote, getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent,
  getLotMarketValue, getLotPnL,
  loadCachedQuotes, initializeWebSocket, closeWebSocket,
} = useEquityQuotes(Auth, { get value() { return filteredItems.value } })

const {
  accounts, selectedAccount, selectedUnderlying,
  isLoading, error, syncSummary, expandedRows,
  filteredItems, groupedPositions, totalCostBasis, totalMarketValue, totalPnL,
  fetchAccounts, syncAndLoad, loadPositions,
  getAccountSymbol, getAccountBadgeClass,
  toggleExpanded, sort, sortIcon, onAccountChange,
} = useEquityPositions(Auth, {
  getQuotePrice, getMarketValue, getUnrealizedPnL, getPnLPercent, quoteUpdateCounter,
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

// Watch account store for changes from GlobalToolbar
watch(() => accountsStore.selectedAccount, (val) => {
  selectedAccount.value = val
  onAccountChange()
})

// Push quote timestamps to the quotes store
watch(lastQuoteUpdate, (val) => {
  quotesStore.setLastQuoteUpdate(val)
})

// Watch sync store — if sync triggered from toolbar, refetch
watch(() => syncStore.lastSyncTime, async (val) => {
  if (val) {
    await loadPositions()
    await loadCachedQuotes()
  }
})

// --- Lifecycle ---

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
  <!-- Page-specific filters teleported to GlobalToolbar -->
  <Teleport to="#page-filters">
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2.5 flex items-center gap-4">
      <!-- Symbol Filter -->
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
              :class="sortIcon(opt.key) ? 'text-tv-blue' : ''">
        <span>{{ opt.label }}</span>
        <span v-if="sortIcon(opt.key)" class="text-[11px]">{{ sortIcon(opt.key) }}</span>
      </button>
    </div>
  </Teleport>

  <!-- Header -->
  <div>
    <!-- Stats Bar (2-col grid on mobile, inline on desktop) -->
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2 grid grid-cols-2 gap-x-4 gap-y-1 md:flex md:items-center md:gap-x-8 text-xs md:text-base">
      <span class="text-tv-muted">
        Positions: <span class="text-tv-text">{{ filteredItems.length }}</span>
      </span>
      <span class="text-tv-muted">
        Cost: <span class="text-tv-text">${{ formatNumber(totalCostBasis) }}</span>
      </span>
      <span class="text-tv-muted">
        <span class="hidden md:inline">Market Value</span><span class="md:hidden">Mkt</span>: <span class="text-tv-text">${{ formatNumber(totalMarketValue) }}</span>
      </span>
      <span class="text-tv-muted">
        <span class="hidden md:inline">Unrealized </span>P&amp;L:
        <span :class="totalPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(totalPnL) }}</span>
      </span>
    </div>

    <!-- Column Headers (desktop only) -->
    <div v-if="!isLoading && groupedPositions.length > 0"
         class="hidden md:flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
      <span class="w-6 mr-2"></span>
      <span class="w-8 mr-3"></span>
      <span class="w-56 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sort('underlying')">
        Symbol <span v-if="sortIcon('underlying')" class="text-tv-blue">{{ sortIcon('underlying') }}</span>
      </span>
      <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sort('quantity')">
        Shares <span v-if="sortIcon('quantity')" class="text-tv-blue">{{ sortIcon('quantity') }}</span>
      </span>
      <span class="w-24 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-4" @click="sort('avg_price')">
        Avg Price <span v-if="sortIcon('avg_price')" class="text-tv-blue">{{ sortIcon('avg_price') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('cost_basis')">
        Cost Basis <span v-if="sortIcon('cost_basis')" class="text-tv-blue">{{ sortIcon('cost_basis') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('market_value')">
        Mkt Value <span v-if="sortIcon('market_value')" class="text-tv-blue">{{ sortIcon('market_value') }}</span>
      </span>
      <span class="w-28 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('pnl')">
        P&amp;L <span v-if="sortIcon('pnl')" class="text-tv-blue">{{ sortIcon('pnl') }}</span>
      </span>
      <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 ml-2" @click="sort('pnl_percent')">
        P&amp;L % <span v-if="sortIcon('pnl_percent')" class="text-tv-blue">{{ sortIcon('pnl_percent') }}</span>
      </span>
    </div>
  </div>

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

  <!-- Desktop Position List -->
  <div v-else class="hidden md:block bg-tv-row border-x border-b border-tv-border">
    <div class="divide-y divide-tv-border">
      <div v-for="item in groupedPositions" :key="item.groupId">
        <!-- Summary row -->
        <div class="flex items-center px-4 h-12 hover:bg-tv-border/20 transition-colors"
             :class="item.equityLegs.length > 1 ? 'cursor-pointer' : ''"
             @click="item.equityLegs.length > 1 && toggleExpanded(item.groupId)">
          <!-- Chevron (only when multiple lots) -->
          <span class="w-6 mr-2">
            <i v-if="item.equityLegs.length > 1"
               class="fas fa-chevron-right text-tv-muted text-xs transition-transform duration-150"
               :class="{ 'rotate-90': expandedRows[item.groupId] }"></i>
          </span>

          <!-- Symbol + Streaming Price -->
          <span class="w-56 flex items-center gap-3">
            <span class="text-lg font-semibold text-tv-text">{{ item.underlying }}</span>
            <span v-show="selectedAccount === ''" class="text-xl leading-none -ml-2" :style="{ color: accountDotColor(getAccountSymbol(item.accountNumber)) }" :title="getAccountTooltip(accounts, item.accountNumber)">●</span>
            <span v-if="item.hasOptions" class="text-[10px] px-1.5 py-0.5 rounded bg-tv-blue/20 text-tv-blue border border-tv-blue/30">
              {{ item.optionStrategy }}
            </span>
            <span v-if="item.equityLegs.length > 1" class="text-[10px] text-tv-muted">
              {{ item.equityLegs.length }} lots
            </span>
            <span class="ml-auto">
              <StreamingPrice :quote="getQuote(item.underlying).price ? getQuote(item.underlying) : null" />
            </span>
          </span>

          <!-- Shares -->
          <span class="w-20 text-right text-base font-medium"
                :class="item.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
            {{ item.quantity }}
          </span>

          <!-- Avg Price -->
          <span class="w-24 text-right text-tv-muted text-base ml-4">
            ${{ formatNumber(item.avgPrice) }}
          </span>

          <!-- Cost Basis -->
          <span class="w-28 text-right text-tv-muted text-base ml-2">
            ${{ formatNumber(item.costBasis) }}
          </span>

          <!-- Market Value -->
          <span class="w-28 text-right text-base ml-2"
                :class="getMarketValue(item) ? 'text-tv-text' : 'text-tv-muted'">
            {{ getMarketValue(item) ? '$' + formatNumber(getMarketValue(item)) : '\u2014' }}
          </span>

          <!-- Unrealized P&L -->
          <span class="w-28 text-right text-base font-medium ml-2"
                :class="pnlColorClass(getUnrealizedPnL(item))">
            {{ getMarketValue(item) ? '$' + formatNumber(getUnrealizedPnL(item)) : '' }}
          </span>

          <!-- P&L % -->
          <span class="w-20 text-right text-base ml-2"
                :class="getPnLPercent(item) > 0 ? 'text-tv-green' : getPnLPercent(item) < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ getMarketValue(item) ? formatNumber(getPnLPercent(item)) + '%' : '' }}
          </span>
        </div>

        <!-- Expanded lots -->
        <div v-if="expandedRows[item.groupId] && item.equityLegs.length > 1"
             class="bg-tv-bg border-t border-tv-border/30">
          <div v-for="leg in item.equityLegs" :key="leg.lot_id"
               class="flex items-center px-4 py-1.5 text-sm hover:bg-tv-border/10">
            <span class="w-6 mr-2"></span>
            <span class="w-8 mr-3"></span>
            <span class="w-56 flex items-center gap-2">
              <span v-if="leg.entry_date" class="text-tv-muted text-xs">{{ formatDate(leg.entry_date) }}</span>
              <span v-if="leg.derivation_type" class="text-[10px] px-1.5 py-0.5 rounded bg-tv-muted/15 text-tv-muted border border-tv-muted/20 uppercase">
                {{ leg.derivation_type }}
              </span>
            </span>
            <span class="w-20 text-right font-medium"
                  :class="leg.quantity_direction === 'Long' ? 'text-tv-green' : 'text-tv-red'">
              {{ leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity }}
            </span>
            <span class="w-24 text-right text-tv-muted ml-4">${{ formatNumber(leg.entry_price) }}</span>
            <span class="w-28 text-right text-tv-muted ml-2">${{ formatNumber(Math.abs(leg.cost_basis)) }}</span>
            <span class="w-28 text-right ml-2"
                  :class="getLotMarketValue(item, leg) ? 'text-tv-text' : 'text-tv-muted'">
              {{ getLotMarketValue(item, leg) ? '$' + formatNumber(getLotMarketValue(item, leg)) : '\u2014' }}
            </span>
            <span class="w-28 text-right font-medium ml-2"
                  :class="getLotPnL(item, leg) > 0 ? 'text-tv-green' : getLotPnL(item, leg) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ getLotMarketValue(item, leg) ? '$' + formatNumber(getLotPnL(item, leg)) : '' }}
            </span>
            <span class="w-20"></span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Mobile Card List -->
  <div v-if="!isLoading && groupedPositions.length > 0" class="md:hidden px-2 py-2 space-y-2">
    <div v-for="item in groupedPositions" :key="'m-' + item.groupId"
         class="bg-tv-row border border-tv-border rounded-lg overflow-hidden active:bg-tv-border/20 transition-colors"
         :class="item.equityLegs.length > 1 ? 'cursor-pointer' : ''"
         @click="item.equityLegs.length > 1 && toggleExpanded(item.groupId)">
      <div class="px-3 py-3">
        <!-- Top row: symbol, live price, expand chevron -->
        <div class="flex items-center gap-2 mb-2">
          <span class="text-lg font-semibold text-tv-text">{{ item.underlying }}</span>
          <span v-show="selectedAccount === ''" class="text-xl leading-none -ml-1" :style="{ color: accountDotColor(getAccountSymbol(item.accountNumber)) }" :title="getAccountTooltip(accounts, item.accountNumber)">●</span>
          <span v-if="item.hasOptions" class="text-[9px] px-1.5 py-0.5 rounded bg-tv-blue/20 text-tv-blue border border-tv-blue/30 uppercase">
            {{ item.optionStrategy }}
          </span>
          <span v-if="item.equityLegs.length > 1" class="text-[10px] text-tv-muted">
            {{ item.equityLegs.length }} lots
          </span>
          <span class="ml-auto text-sm">
            <StreamingPrice :quote="getQuote(item.underlying).price ? getQuote(item.underlying) : null" />
          </span>
          <i v-if="item.equityLegs.length > 1"
             class="fas fa-chevron-right text-tv-muted text-[11px] transition-transform duration-150"
             :class="{ 'rotate-90': expandedRows[item.groupId] }"></i>
        </div>

        <!-- Shares + P&L row -->
        <div class="flex items-end justify-between mb-2.5">
          <div class="flex items-baseline gap-1.5">
            <span class="text-xl font-semibold"
                  :class="item.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
              {{ item.quantity }}
            </span>
            <span class="text-[11px] text-tv-muted">sh &middot; @${{ formatNumber(item.avgPrice) }}</span>
          </div>
          <div class="text-right">
            <div class="text-base font-semibold leading-tight"
                 :class="pnlColorClass(getUnrealizedPnL(item))">
              {{ getMarketValue(item) ? '$' + formatNumber(getUnrealizedPnL(item)) : '\u2014' }}
            </div>
            <div class="text-[11px] leading-tight"
                 :class="getPnLPercent(item) > 0 ? 'text-tv-green' : getPnLPercent(item) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ getMarketValue(item) ? formatNumber(getPnLPercent(item)) + '%' : '' }}
            </div>
          </div>
        </div>

        <!-- Cost + Mkt Value row -->
        <div class="grid grid-cols-2 gap-2 text-[11px] pt-2 border-t border-tv-border/30">
          <div>
            <div class="text-tv-muted uppercase tracking-wide">Cost</div>
            <div class="text-tv-text text-sm">${{ formatNumber(item.costBasis) }}</div>
          </div>
          <div class="text-right">
            <div class="text-tv-muted uppercase tracking-wide">Mkt Value</div>
            <div class="text-sm"
                 :class="getMarketValue(item) ? 'text-tv-text' : 'text-tv-muted'">
              {{ getMarketValue(item) ? '$' + formatNumber(getMarketValue(item)) : '\u2014' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Expanded lots (mobile) -->
      <div v-if="expandedRows[item.groupId] && item.equityLegs.length > 1"
           class="bg-tv-bg border-t border-tv-border/30 px-3 py-2 space-y-1.5">
        <div v-for="leg in item.equityLegs" :key="'m-lot-' + leg.lot_id"
             class="flex items-center justify-between text-xs">
          <div class="flex items-center gap-1.5 min-w-0">
            <span v-if="leg.entry_date" class="text-tv-muted shrink-0">{{ formatDate(leg.entry_date) }}</span>
            <span v-if="leg.derivation_type" class="text-[9px] px-1 py-0.5 rounded bg-tv-muted/15 text-tv-muted border border-tv-muted/20 uppercase">
              {{ leg.derivation_type }}
            </span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="font-medium"
                  :class="leg.quantity_direction === 'Long' ? 'text-tv-green' : 'text-tv-red'">
              {{ leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity }}
            </span>
            <span class="text-tv-muted">@${{ formatNumber(leg.entry_price) }}</span>
            <span class="font-medium min-w-[60px] text-right"
                  :class="getLotPnL(item, leg) > 0 ? 'text-tv-green' : getLotPnL(item, leg) < 0 ? 'text-tv-red' : 'text-tv-muted'">
              {{ getLotMarketValue(item, leg) ? '$' + formatNumber(getLotPnL(item, leg)) : '\u2014' }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Bottom spacer -->
  <div class="h-96"></div>
</template>
