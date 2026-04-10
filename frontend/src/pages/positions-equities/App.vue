<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'
import StreamingPrice from '@/components/StreamingPrice.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useQuotesStore } from '@/stores/quotes'
import { useEquityQuotes } from './useEquityQuotes'
import { useEquityPositions } from './useEquityPositions'

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
  selectedAccount.value = accountsStore.selectedAccount
  await fetchAccounts()
  await loadPositions()
  await loadCachedQuotes()
  await initializeWebSocket()
})

onUnmounted(() => {
  closeWebSocket()
})
</script>

<template>
  <!-- Page-specific filters teleported to GlobalToolbar -->
  <Teleport to="#page-filters">
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2.5 flex items-center gap-4">
      <!-- Symbol Filter -->
      <div class="relative">
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

  <!-- Header -->
  <div>
    <!-- Stats Bar -->
    <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center gap-8 text-base">
      <span class="text-tv-muted">
        Positions: <span class="text-tv-text">{{ filteredItems.length }}</span>
      </span>
      <span class="text-tv-muted">
        Cost Basis: <span class="text-tv-text">${{ formatNumber(totalCostBasis) }}</span>
      </span>
      <span class="text-tv-muted">
        Market Value: <span class="text-tv-text">${{ formatNumber(totalMarketValue) }}</span>
      </span>
      <span class="text-tv-muted">
        Unrealized P&amp;L:
        <span :class="totalPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">${{ formatNumber(totalPnL) }}</span>
      </span>
    </div>

    <!-- Column Headers -->
    <div v-if="!isLoading && groupedPositions.length > 0"
         class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
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

  <!-- Position List -->
  <div v-else class="bg-tv-row border-x border-b border-tv-border">
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

          <!-- Account badge -->
          <span class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mr-3"
                :class="getAccountBadgeClass(item.accountNumber)">
            {{ getAccountSymbol(item.accountNumber) }}
          </span>

          <!-- Symbol + Streaming Price -->
          <span class="w-56 flex items-center gap-3">
            <span class="text-lg font-semibold text-tv-text">{{ item.underlying }}</span>
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
                :class="getUnrealizedPnL(item) > 0 ? 'text-tv-green' : getUnrealizedPnL(item) < 0 ? 'text-tv-red' : 'text-tv-muted'">
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

  <!-- Bottom spacer -->
  <div class="h-96"></div>
</template>
