<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'
import StreamingPrice from '@/components/StreamingPrice.vue'
import PositionsToolbar from '@/components/PositionsToolbar.vue'

import { usePositionsData } from './usePositionsData'
import { usePositionsNotes } from './usePositionsNotes'
import {
  formatDollar, dollarSizeClass,
  getOptionType, getSignedQuantity, getExpirationDate, getStrikePrice, getDTE,
  getGroupStrategyLabel, sortedLegs, getAccountSymbol as getAccountSymbolPure,
} from './usePositionsDisplay'

const Auth = useAuth()

// --- Wire composables ---

const {
  allChains, allItems, filteredItems, accounts,
  underlyingQuotes, quoteUpdateCounter,
  selectedAccount, selectedUnderlying,
  isLoading, error, liveQuotesActive, lastQuoteUpdate, syncSummary,
  strategyTargets, rollAlertSettings, rollAnalysisMode,
  sortColumn, sortDirection, expandedRows,
  groupedPositions, underlyings,
  toggleRollAnalysisMode, toggleExpanded,
  fetchAccounts, fetchPositions, loadCachedQuotes,
  initializeWebSocket, requestLiveQuotes, cleanupWebSocket,
  applyFilters, filterPositions, saveFilterPreferences, loadFilterPreferences,
  onAccountChange, onSymbolFilterCommit,
  sortPositions,
  getGroupCostBasis, getGroupOpenPnL, getGroupRealizedPnL, getGroupTotalPnL,
  getGroupNetLiqWithLiveQuotes, getGroupPnLPercent, getGroupDaysOpen, getMinDTE,
  calculateLegMarketValue, calculateLegPnL,
  hasEquity, calculateEquityMarketValue,
  getUnderlyingQuote, getUnderlyingIVR, getOptionStratUrl,
  loadStrategyTargets, loadRollAlertSettings,
} = usePositionsData(Auth)

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

// --- Thin wrappers for template (adapt pure functions to reactive state) ---

const noteCallbacks = { migrateCommentKeysFn: migrateCommentKeys, loadCommentsFn: loadComments }

function syncPositions() {
  return fetchPositions(true, noteCallbacks)
}

function getAccountSymbol(accountNumber) {
  return getAccountSymbolPure(accounts.value, accountNumber)
}

// --- Lifecycle ---

onMounted(async () => {
  document.addEventListener('click', onDocumentClick)

  await loadComments()
  loadRollAlertSettings()
  await fetchAccounts()
  await loadStrategyTargets()
  loadFilterPreferences()
  await fetchPositions(false, noteCallbacks)
  await loadCachedQuotes()
  await loadAvailableTags()
  initializeWebSocket()
})

onUnmounted(() => {
  cleanupWebSocket()
  document.removeEventListener('click', onDocumentClick)
  cleanupNoteTimers()
})
</script>

<template>
  <Teleport to="#nav-right">
    <select v-model="selectedAccount" @change="onAccountChange()"
            class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded">
      <option value="">All Accounts</option>
      <option v-for="account in accounts" :key="account.account_number"
              :value="account.account_number">
        ({{ getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
      </option>
    </select>
  </Teleport>

  <!-- Sticky header block (action bar + column headers) -->
  <div class="sticky top-14 z-30">

  <!-- Action Bar -->
  <PositionsToolbar
    :is-loading="isLoading"
    :live-quotes-active="liveQuotesActive"
    :last-quote-update="lastQuoteUpdate"
    :sync-summary="syncSummary"
    :selected-account="selectedAccount"
    v-model:symbol-filter="selectedUnderlying"
    @sync="syncPositions"
    @update:sync-summary="syncSummary = $event"
    @symbol-commit="onSymbolFilterCommit"
  />

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

  <!-- Column Headers -->
  <div v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0"
       class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <span class="w-8"></span>
    <span class="w-6 text-center" v-show="selectedAccount === ''"></span>
    <span class="w-14 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('underlying')">
      Symbol
      <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-8 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1 mr-1" @click="sortPositions('ivr')">
      IVR
      <span v-show="sortColumn === 'ivr'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-40 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('price')">
      Price
      <span v-show="sortColumn === 'price'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-10"></span>
    <span class="w-32 cursor-pointer hover:text-tv-text flex items-center gap-1" @click="sortPositions('strategy')">
      Strategy
      <span v-show="sortColumn === 'strategy'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-10 text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1" @click="sortPositions('dte')">
      DTE
      <span v-show="sortColumn === 'dte'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-10 text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1" @click="sortPositions('days')">
      Days
      <span v-show="sortColumn === 'days'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('cost_basis')">
      Cost Basis
      <span v-show="sortColumn === 'cost_basis'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('net_liq')">
      Net Liq
      <span v-show="sortColumn === 'net_liq'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('realized_pnl')">
      Realized
      <span v-show="sortColumn === 'realized_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('open_pnl')">
      Open
      <span v-show="sortColumn === 'open_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-[6.5rem] text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('total_pnl')">
      Total
      <span v-show="sortColumn === 'total_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
    <span class="w-20 text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1" @click="sortPositions('pnl_percent')"
          title="Return on capital: Total P&L ÷ Cost Basis. Measures how much you've made or lost relative to what you put in.">
      % Rtn
      <span v-show="sortColumn === 'pnl_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </span>
  </div>

  </div><!-- /sticky header block -->

  <!-- Main Content -->
  <main v-show="!isLoading && !error && filteredItems.length > 0 && allItems.length > 0">
   <div class="bg-tv-panel border-x border-b border-tv-border">
    <!-- Position Groups -->
    <div class="divide-y divide-tv-border">
      <div v-for="(group, index) in groupedPositions" :key="group.groupKey">

        <!-- Subtotal Row -->
        <div v-if="group._isSubtotal" class="flex items-center px-4 h-12 bg-tv-blue/10 border-l-2 border-tv-blue">
          <div class="w-8"></div>
          <div class="w-6" v-show="selectedAccount === ''"></div>
          <div class="w-14">
            <div class="font-bold text-base text-tv-text">{{ group.displayKey }}</div>
          </div>
          <div class="w-8 mr-1"></div>
          <div class="w-40"></div>
          <div class="w-10"></div>
          <!-- Strategy -->
          <div class="w-32 text-xs text-tv-muted">{{ group._childCount }} positions</div>
          <!-- DTE -->
          <div class="w-10"></div>
          <!-- Days -->
          <div class="w-10"></div>
          <!-- Cost Basis -->
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalCostBasis >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalCostBasis)">
            <span v-show="group._subtotalCostBasis < 0">-</span>${{ formatDollar(group._subtotalCostBasis) }}
          </div>
          <!-- Net Liq -->
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalNetLiq >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalNetLiq)">
            <span v-show="group._subtotalNetLiq < 0">-</span>${{ formatDollar(group._subtotalNetLiq) }}
          </div>
          <!-- Realized -->
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalRealizedPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalRealizedPnL)">
            <span v-show="group._subtotalRealizedPnL !== 0">
              <span v-show="group._subtotalRealizedPnL < 0">-</span>${{ formatDollar(group._subtotalRealizedPnL) }}
            </span>
          </div>
          <!-- Open P/L -->
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalOpenPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalOpenPnL)">
            <span v-show="group._subtotalOpenPnL < 0">-</span>${{ formatDollar(group._subtotalOpenPnL) }}
          </div>
          <!-- Total P/L -->
          <div class="w-[6.5rem] text-right font-medium"
               :class="(group._subtotalTotalPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group._subtotalTotalPnL)">
            <span v-show="group._subtotalTotalPnL < 0">-</span>${{ formatDollar(group._subtotalTotalPnL) }}
          </div>
          <!-- % Rtn -->
          <div class="w-20"></div>
        </div>

        <!-- Regular Row (Chain or Share) -->
        <template v-else>
          <div>
            <!-- Group Row -->
            <div class="flex items-center px-4 h-12 hover:bg-tv-border/20 cursor-pointer transition-colors"
                 @click="toggleExpanded(group.groupKey)">
              <!-- Chevron -->
              <div class="w-8">
                <i class="fas fa-chevron-right text-tv-muted transition-transform duration-200"
                   :class="{ 'rotate-90': expandedRows.has(group.groupKey) }"></i>
              </div>

              <!-- Account Symbol (only when All Accounts selected) -->
              <div class="w-6 text-center text-tv-muted text-sm" v-show="selectedAccount === ''">
                {{ getAccountSymbol(group.accountNumber) }}
              </div>

              <!-- Symbol -->
              <div class="w-14">
                <div class="font-semibold text-base text-tv-text">
                  {{ group.displayKey || group.underlying }}
                  <span v-show="hasEquity(group) && (group.positions || []).length > 0" class="text-[10px] text-tv-muted ml-1 bg-tv-border/50 px-1 rounded">+stk</span>
                </div>
              </div>

              <!-- IVR -->
              <div class="w-8 text-right mr-1"
                   :class="getUnderlyingIVR(group.underlying) >= 50 ? 'font-bold text-tv-amber' : 'text-tv-muted'">
                {{ getUnderlyingIVR(group.underlying) !== null ? getUnderlyingIVR(group.underlying) : '' }}
              </div>

              <!-- Price -->
              <div class="w-40 flex items-center gap-2">
                <StreamingPrice :quote="getUnderlyingQuote(group.underlying)" />
              </div>

              <!-- Ledger Link -->
              <div class="w-10">
                <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying) + '&group=' + encodeURIComponent(group.group_id)"
                   @click.stop
                   class="text-tv-blue hover:text-tv-blue"
                   title="View in Ledger">
                  <i class="fas fa-book"></i>
                  <span v-show="group.roll_count > 0" class="text-xs text-tv-muted ml-0.5">R{{ group.roll_count }}</span>
                </a>
              </div>

              <!-- Strategy -->
              <div class="w-32 relative">
                <div class="text-sm text-tv-muted">{{ getGroupStrategyLabel(group) }}</div>
                <template v-if="group.rollAnalysis && group.rollAnalysis.badges.length > 0">
                  <div class="flex flex-wrap gap-1 mt-0.5">
                    <span v-for="badge in group.rollAnalysis.badges" :key="badge.label"
                          class="text-[10px] px-1.5 py-0 rounded-sm border leading-4"
                          :class="{
                            'bg-tv-green/20 text-tv-green border-tv-green/50': badge.color === 'green',
                            'bg-tv-red/20 text-tv-red border-tv-red/50': badge.color === 'red',
                            'bg-tv-amber/20 text-tv-amber border-tv-amber/50': badge.color === 'yellow',
                            'bg-tv-orange/20 text-tv-orange border-tv-orange/50': badge.color === 'orange'
                          }">{{ badge.label }}</span>
                  </div>
                </template>
                <!-- Tag chips -->
                <div class="flex flex-wrap gap-1 mt-0.5 items-center" data-tag-popover @click.stop>
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
                     data-tag-popover
                     @click.stop>
                  <input type="text"
                         :id="'tag-input-' + group.group_id"
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
              </div>

              <!-- DTE -->
              <div class="w-10 text-center"
                   :class="getMinDTE(group) !== null && getMinDTE(group) <= 21 ? 'font-bold text-tv-amber' : 'text-tv-text'">
                {{ getMinDTE(group) !== null ? getMinDTE(group) + 'd' : '' }}
              </div>

              <!-- Days -->
              <div class="w-10 text-center text-tv-text">{{ getGroupDaysOpen(group) || '' }}</div>

              <!-- Cost Basis -->
              <div class="w-[6.5rem] text-right"
                   :class="(getGroupCostBasis(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupCostBasis(group))">
                <span v-show="getGroupCostBasis(group) < 0">-</span>${{ formatDollar(getGroupCostBasis(group)) }}
              </div>

              <!-- Net Liq -->
              <div class="w-[6.5rem] text-right font-medium"
                   :class="(getGroupNetLiqWithLiveQuotes(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupNetLiqWithLiveQuotes(group))">
                <span v-show="getGroupNetLiqWithLiveQuotes(group) < 0">-</span>${{ formatDollar(getGroupNetLiqWithLiveQuotes(group)) }}
              </div>

              <!-- Realized P/L -->
              <div class="w-[6.5rem] text-right"
                   :class="(getGroupRealizedPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupRealizedPnL(group))">
                <template v-if="getGroupRealizedPnL(group) !== 0">
                  <span v-show="getGroupRealizedPnL(group) < 0">-</span>${{ formatDollar(getGroupRealizedPnL(group)) }}
                </template>
              </div>

              <!-- Open P/L -->
              <div class="w-[6.5rem] text-right font-medium"
                   :class="(getGroupOpenPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupOpenPnL(group))">
                <span v-show="getGroupOpenPnL(group) < 0">-</span>${{ formatDollar(getGroupOpenPnL(group)) }}
              </div>

              <!-- Total P/L -->
              <div class="w-[6.5rem] text-right font-medium"
                   :class="(getGroupTotalPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(getGroupTotalPnL(group))">
                <span v-show="getGroupTotalPnL(group) < 0">-</span>${{ formatDollar(getGroupTotalPnL(group)) }}
              </div>

              <!-- % Rtn -->
              <div class="w-20 text-right"
                   :class="getGroupPnLPercent(group) !== null ? (parseFloat(getGroupPnLPercent(group)) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
                {{ getGroupPnLPercent(group) !== null ? getGroupPnLPercent(group) + '%' : '' }}
              </div>

              <!-- Note indicator -->
              <i class="fas fa-sticky-note text-tv-amber text-sm pl-2"
                 v-show="getPositionComment(group)" title="Has notes"></i>
            </div>

            <!-- Expanded Detail Panel -->
            <div v-show="expandedRows.has(group.groupKey)" class="bg-tv-bg border-t border-tv-border">
              <div class="mx-4 my-3 p-3 bg-tv-panel rounded border border-tv-border font-mono">
                <div class="flex gap-4">
                  <div class="flex-shrink-0 space-y-1">
                    <!-- Option legs section -->
                    <template v-if="(group.positions || []).length > 0">
                      <div>
                        <!-- Header row -->
                        <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                          <span class="w-10 text-right">Qty</span>
                          <span class="w-16 text-center mx-2">Exp</span>
                          <span class="w-10">DTE</span>
                          <span class="w-16 text-center mx-2">Strike</span>
                          <span class="w-6">Type</span>
                          <span class="w-[6.5rem] text-right ml-4">Cost Basis</span>
                          <span class="w-20 text-right ml-3">Net Liq</span>
                          <span class="w-20 text-right ml-3">Open P/L</span>
                        </div>

                        <!-- Option legs -->
                        <div v-for="leg in sortedLegs(group.positions)" :key="leg.lot_id || leg.symbol"
                             class="flex items-center text-sm py-0.5">
                          <span class="w-10 text-right font-medium"
                                :class="getSignedQuantity(leg) > 0 ? 'text-tv-green' : 'text-tv-red'">
                            {{ getSignedQuantity(leg) }}
                          </span>
                          <span class="w-16 text-center bg-tv-border/30 mx-2 py-0.5 rounded text-tv-text">
                            {{ getExpirationDate(leg) }}
                          </span>
                          <span class="w-10 text-tv-muted"
                                :class="getDTE(leg) <= 7 ? 'text-tv-red' : getDTE(leg) <= 30 ? 'text-tv-amber' : ''">
                            {{ getDTE(leg) !== null ? getDTE(leg) + 'd' : '' }}
                          </span>
                          <span class="w-16 text-center bg-tv-border/30 mx-2 py-0.5 rounded text-tv-text">
                            {{ getStrikePrice(leg) }}
                          </span>
                          <span class="w-6 text-tv-muted">{{ getOptionType(leg) }}</span>
                          <span class="w-[6.5rem] text-right ml-4"
                                :class="(leg.cost_basis || 0) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(leg.cost_basis || 0) }}
                          </span>
                          <span class="w-20 text-right ml-3 text-tv-muted">
                            ${{ formatNumber(calculateLegMarketValue(leg)) }}
                          </span>
                          <span class="w-20 text-right ml-3 font-medium"
                                :class="calculateLegPnL(leg) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(calculateLegPnL(leg)) }}
                          </span>
                        </div>
                      </div>
                    </template>

                    <!-- Equity section -->
                    <template v-if="(group.equityLegs || []).length > 0">
                      <div :class="(group.positions || []).length > 0 ? 'mt-2 pt-2 border-t border-tv-border/30' : ''">
                        <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                          <span class="w-16">Shares</span>
                          <span class="w-20 text-right">Avg Price</span>
                          <span class="w-[6.5rem] text-right ml-4">Cost Basis</span>
                          <span class="w-20 text-right ml-3">Mkt Value</span>
                          <span class="w-20 text-right ml-3">Open P/L</span>
                        </div>
                        <div class="flex items-center text-sm py-0.5">
                          <span class="w-16 font-medium text-tv-text">{{ group.equitySummary?.quantity || 0 }}</span>
                          <span class="w-20 text-right text-tv-muted">${{ formatNumber(group.equitySummary?.average_price || 0) }}</span>
                          <span class="w-[6.5rem] text-right ml-4 text-tv-muted">
                            ${{ formatNumber(group.equitySummary?.cost_basis || 0) }}
                          </span>
                          <span class="w-20 text-right ml-3 text-tv-muted">
                            ${{ formatNumber(calculateEquityMarketValue(group)) }}
                          </span>
                          <span class="w-20 text-right ml-3 font-medium"
                                :class="(calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                            ${{ formatNumber(calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) }}
                          </span>
                        </div>
                      </div>
                    </template>

                    <!-- No legs message for assigned chains -->
                    <template v-if="(group.positions || []).length === 0 && (group.equityLegs || []).length === 0">
                      <div class="text-xs text-tv-muted py-1">
                        <span v-show="group.has_assignment">All positions assigned/exercised</span>
                        <span v-show="!group.has_assignment">No open legs</span>
                      </div>
                    </template>

                    <!-- Chain summary -->
                    <div class="flex items-center text-xs text-tv-muted mt-2 pt-1 border-t border-tv-border/30 gap-4">
                      <span>Opened: {{ formatDate(group.opening_date) || 'N/A' }}</span>
                      <span>Orders: {{ group.order_count || 1 }}</span>
                      <span v-show="group.roll_count > 0" class="text-tv-blue">Rolls: {{ group.roll_count }}</span>
                      <span v-show="group.realized_pnl !== 0"
                            :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                        Realized: ${{ formatNumber(group.realized_pnl) }}
                      </span>
                    </div>
                  </div>

                  <!-- Comments -->
                  <div class="flex-1 min-w-0">
                    <div class="text-xs text-tv-muted pb-1 border-b border-tv-border/30 mb-1">Notes</div>
                    <textarea :value="getPositionComment(group)"
                              @input="updatePositionComment(group, $event.target.value)"
                              @click.stop
                              rows="3"
                              class="w-full bg-transparent text-tv-text text-sm font-sans border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                              placeholder="Add notes..."></textarea>
                  </div>
                </div>
              </div>

              <!-- Roll Analysis Panel -->
              <template v-if="group.rollAnalysis">
                <div class="mx-4 mb-3 p-3 bg-tv-panel rounded border-l-2"
                     :class="{
                       'border-tv-green border border-l-2 border-tv-green/30': group.rollAnalysis.borderColor === 'green',
                       'border-tv-red border border-l-2 border-tv-red/30': group.rollAnalysis.borderColor === 'red',
                       'border-tv-amber border border-l-2 border-tv-amber/30': group.rollAnalysis.borderColor === 'yellow',
                       'border-tv-blue border border-l-2 border-tv-blue/30': group.rollAnalysis.borderColor === 'blue'
                     }">
                  <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold text-tv-text">Roll Analysis</span>
                      <button v-if="group.realized_pnl !== 0"
                              @click.stop="toggleRollAnalysisMode()"
                              class="text-[10px] px-1.5 py-0 rounded-sm border leading-4 transition-colors cursor-pointer"
                              :class="rollAnalysisMode === 'chain'
                                ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50'
                                : 'bg-tv-panel text-tv-muted border-tv-border/50 hover:text-tv-text'"
                              :title="rollAnalysisMode === 'chain'
                                ? 'Chain: P&L and targets include roll costs — shows true trade performance. Signals and alerts always evaluate the open position only, since prior costs don\'t change the current spread\'s risk/reward.'
                                : 'Open: P&L and targets based on current position only, ignoring prior rolls.'">
                        {{ rollAnalysisMode === 'chain' ? 'Chain' : 'Open' }}
                      </button>
                    </div>
                  </div>
                  <!-- Compact 3-column layout -->
                  <div class="flex gap-6 text-xs mb-2">
                    <!-- P&L Status -->
                    <div class="space-y-1">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">P&L Status</div>
                      <div class="flex justify-between gap-3" :title="group.rollAnalysis.pnlTooltip">
                        <span class="text-tv-muted cursor-help border-b border-dotted border-tv-muted/40">{{ group.rollAnalysis.pnlLabel }}</span>
                        <span class="font-medium" :class="group.rollAnalysis.pnlPositive ? 'text-tv-green' : 'text-tv-red'">
                          {{ group.rollAnalysis.pnlValue }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Remaining Reward</span>
                        <span class="font-medium text-tv-green">${{ group.rollAnalysis.rewardRemaining }}</span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Remaining Risk</span>
                        <span class="font-medium text-tv-red">${{ group.rollAnalysis.riskRemaining }}</span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Reward:Risk</span>
                        <span class="font-medium" :class="group.rollAnalysis.rewardToRiskRaw < (group.rollAnalysis.isCredit ? 0.3 : 0.6) ? 'text-tv-orange' : 'text-tv-text'">
                          {{ group.rollAnalysis.rewardToRisk }}
                        </span>
                      </div>
                    </div>
                    <!-- Greeks -->
                    <div class="space-y-1 border-l border-tv-border/20 pl-6">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">Greeks</div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Net Delta</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.netDelta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netDelta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          {{ group.rollAnalysis.netDelta.toFixed(2) }}
                        </span>
                      </div>
                      <div v-if="group.rollAnalysis.qtyGcd > 1" class="flex justify-between gap-3">
                        <span class="text-tv-muted">Delta/Qty</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.deltaPerQty > 0.01 ? 'text-tv-green' : group.rollAnalysis.deltaPerQty < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          {{ group.rollAnalysis.deltaPerQty.toFixed(2) }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Theta/Day</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.netTheta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netTheta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          ${{ group.rollAnalysis.netTheta.toFixed(2) }}
                        </span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Gamma</span>
                        <span class="font-medium text-tv-text">{{ group.rollAnalysis.netGamma.toFixed(2) }}</span>
                      </div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Vega</span>
                        <span class="font-medium text-tv-text">{{ group.rollAnalysis.netVega.toFixed(2) }}</span>
                      </div>
                    </div>
                    <!-- Context -->
                    <div class="space-y-1 border-l border-tv-border/20 pl-6">
                      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">Context</div>
                      <div class="flex justify-between gap-3">
                        <span class="text-tv-muted">Near Short</span>
                        <span class="font-medium" :class="parseFloat(group.rollAnalysis.proximityToShort) < 3 ? 'text-tv-amber' : 'text-tv-text'">
                          {{ group.rollAnalysis.proximityToShort }}%
                        </span>
                      </div>
                      <div class="flex justify-between gap-3 cursor-help" :title="group.rollAnalysis.deltaSatTooltip">
                        <span class="text-tv-muted">Delta Sat.</span>
                        <span class="font-medium" :class="parseFloat(group.rollAnalysis.deltaSaturation) >= 65 ? (group.rollAnalysis.isCredit ? 'text-tv-red' : 'text-tv-orange') : 'text-tv-text'">
                          {{ group.rollAnalysis.deltaSaturation }}%
                        </span>
                      </div>
                      <div class="flex justify-between gap-3 cursor-help" :title="group.rollAnalysis.evTooltip">
                        <span class="text-tv-muted">EV</span>
                        <span class="font-medium"
                              :class="group.rollAnalysis.ev > 0.01 ? 'text-tv-green' : group.rollAnalysis.ev < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                          ${{ group.rollAnalysis.ev.toFixed(0) }}
                        </span>
                      </div>
                    </div>
                  </div>
                  <!-- Footer: Signals from rules engine -->
                  <div class="space-y-1">
                    <div v-for="signal in group.rollAnalysis.signals" :key="signal.id"
                         class="pl-3 py-1.5 border-l-2 text-xs text-tv-text bg-tv-bg/50 rounded-r flex items-center gap-2"
                         :class="{
                           'border-tv-red': signal.color === 'red',
                           'border-tv-amber': signal.color === 'orange' || signal.color === 'yellow',
                           'border-tv-green': signal.color === 'green',
                           'border-tv-blue': signal.color === 'blue',
                         }">
                      <i class="fas text-[10px]"
                         :class="{
                           'fa-circle-exclamation text-tv-red': signal.type === 'action' && signal.color === 'red',
                           'fa-triangle-exclamation text-tv-amber': signal.type === 'action' && signal.color !== 'red',
                           'fa-eye text-tv-amber': signal.type === 'warning',
                           'fa-circle-check text-tv-blue': signal.type === 'hold',
                           'fa-circle-check text-tv-green': signal.color === 'green',
                         }"></i>
                      <span>{{ signal.message }}</span>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </template>

      </div>
    </div>
   </div>
  </main>
</template>
