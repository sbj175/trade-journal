<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatDate } from '@/lib/formatters'
import RollChainModal from '@/components/RollChainModal.vue'
import {
  formatDollar,
  getOptionType, getSignedQuantity, getExpirationDate, getStrikePrice, getDTE,
  getGroupStrategyLabel, sortedLegs,
} from './usePositionsDisplay'
import { usePositionsData } from './usePositionsData'
import { usePositionsNotes } from './usePositionsNotes'

const Auth = useAuth()
const route = useRoute()
const router = useRouter()

const {
  allChains, allItems, filteredItems,
  underlyingQuotes, quoteUpdateCounter,
  isLoading, liveQuotesActive,
  groupedPositions,
  fetchPositions, loadCachedQuotes,
  initializeWebSocket, requestLiveQuotes, cleanupWebSocket,
  getGroupCostBasis, getGroupOpenPnL, getGroupRealizedPnL,
  getGroupNetLiqWithLiveQuotes, getGroupPnLPercent, getMinDTE,
  calculateLegMarketValue, calculateLegPnL,
  hasEquity, calculateEquityMarketValue,
  getUnderlyingQuote, getUnderlyingIVR,
  loadStrategyTargets, loadRollAlertSettings,
  rollAnalysisMode, toggleRollAnalysisMode,
} = usePositionsData(Auth)

function gcd(a, b) { a = Math.abs(a); b = Math.abs(b); while (b) { [a, b] = [b, a % b] }; return a }
function getPositionCount(group) {
  const legs = group.positions || []
  if (legs.length === 0) return null
  const quantities = legs.map(l => Math.abs(getSignedQuantity(l)))
  return quantities.reduce((a, b) => gcd(a, b))
}

const {
  positionComments,
  getPositionComment, updatePositionComment, loadPositionComments,
} = usePositionsNotes(Auth, { allItems })

// Roll chain modal
const rollChainGroupId = ref(null)
const rollChainUnderlying = ref('')
const rollChainOpenPnl = ref(null)

function openRollChainModal(group) {
  rollChainGroupId.value = group.group_id
  rollChainUnderlying.value = group.underlying
  rollChainOpenPnl.value = getGroupOpenPnL(group)
}

// Find the group matching the route param
const group = computed(() => {
  if (!groupedPositions.value) return null
  return groupedPositions.value.find(g => g.group_id === route.params.groupId) || null
})

function goBack() {
  router.push('/positions/options')
}

onMounted(async () => {
  await fetchPositions()
  await loadCachedQuotes()
  await loadPositionComments()
  initializeWebSocket()
  if (allItems.value.length > 0) {
    requestLiveQuotes()
  }
  loadStrategyTargets()
  loadRollAlertSettings()
})
</script>

<template>
  <div class="min-h-screen bg-tv-bg max-w-full overflow-x-hidden">
    <!-- Back bar -->
    <div class="px-4 pt-3 pb-1">
      <button @click="goBack()"
              class="text-tv-muted active:text-tv-text min-h-[44px] min-w-[44px] flex items-center gap-2">
        <i class="fas fa-arrow-left"></i>
        <span class="text-xs uppercase tracking-wider">Positions</span>
      </button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="text-center py-16">
      <div class="spinner mx-auto mb-4" style="width: 32px; height: 32px; border-width: 3px;"></div>
      <p class="text-tv-muted">Loading position...</p>
    </div>

    <!-- Not found -->
    <div v-else-if="!group" class="text-center py-16">
      <i class="fas fa-exclamation-circle text-3xl text-tv-muted mb-3"></i>
      <p class="text-tv-muted">Position not found</p>
      <button @click="goBack()" class="mt-4 text-tv-blue text-sm">Back to positions</button>
    </div>

    <!-- Detail content -->
    <div v-else class="max-w-full">

      <!-- Hero section — no borders, flows on background -->
      <div class="px-4 pt-2 pb-4">
        <!-- Symbol + Strategy -->
        <div class="flex items-baseline gap-2">
          <span class="font-bold text-2xl text-white">{{ group.displayKey || group.underlying }}</span>
          <span class="text-base text-tv-muted">{{ getGroupStrategyLabel(group) }}<span v-if="getPositionCount(group)" class="ml-1">({{ getPositionCount(group) }})</span></span>
        </div>

        <!-- Hero P&L -->
        <div class="mt-2">
          <span class="font-bold text-3xl"
                :class="getGroupOpenPnL(group) >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-show="getGroupOpenPnL(group) < 0">-</span>${{ formatDollar(getGroupOpenPnL(group)) }}
          </span>
          <span class="text-lg ml-2"
                :class="getGroupPnLPercent(group) !== null ? (parseFloat(getGroupPnLPercent(group)) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
            {{ getGroupPnLPercent(group) !== null ? '(' + getGroupPnLPercent(group) + '%)' : '' }}
          </span>
        </div>

        <!-- Secondary metrics — flowing, no grid box -->
        <div class="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <span :class="getMinDTE(group) !== null && getMinDTE(group) <= 21 ? 'text-tv-amber' : 'text-tv-muted'">
            {{ getMinDTE(group) !== null ? getMinDTE(group) + 'd' : '--' }}
          </span>
          <span :class="getUnderlyingIVR(group.underlying) >= 50 ? 'text-tv-amber' : 'text-tv-muted'"
                v-if="getUnderlyingIVR(group.underlying) !== null">
            IVR {{ getUnderlyingIVR(group.underlying) }}
          </span>
          <span class="text-tv-muted">
            {{ formatDate(group.roll_chain ? group.roll_chain.first_opened : group.opening_date) }}
          </span>
        </div>

        <!-- Cost / Net Liq — inline -->
        <div class="mt-3 flex gap-6 text-sm">
          <div>
            <span class="text-tv-muted">Cost </span>
            <span :class="getGroupCostBasis(group) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
              <span v-show="getGroupCostBasis(group) < 0">-</span>${{ formatDollar(getGroupCostBasis(group)) }}
            </span>
          </div>
          <div>
            <span class="text-tv-muted">Net Liq </span>
            <span :class="getGroupNetLiqWithLiveQuotes(group) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
              <span v-show="getGroupNetLiqWithLiveQuotes(group) < 0">-</span>${{ formatDollar(getGroupNetLiqWithLiveQuotes(group)) }}
            </span>
          </div>
        </div>
      </div>

      <!-- Divider -->
      <div class="border-t border-tv-border/30 mx-4"></div>

      <!-- Sections with cards below the fold -->
      <div class="px-4 py-2 divide-y divide-tv-border/20">

        <!-- Roll Chain -->
        <div v-if="group.roll_chain" class="px-1 py-2">
          <div class="flex items-center justify-between mb-3">
            <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider">Roll Chain</span>
            <button @click="openRollChainModal(group)"
                    class="text-xs px-3 py-1.5 rounded-full bg-tv-blue text-white active:bg-tv-blue/80 font-medium min-h-[36px]">
              <i class="fas fa-link text-[9px] mr-1"></i>{{ group.roll_chain.roll_count }} roll{{ group.roll_chain.roll_count > 1 ? 's' : '' }}
            </button>
          </div>
          <div class="flex gap-6 text-sm">
            <div>
              <span class="text-tv-muted text-xs block">Realized</span>
              <span class="font-medium"
                    :class="group.roll_chain.cumulative_realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                <span v-show="group.roll_chain.cumulative_realized_pnl < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl) }}
              </span>
            </div>
            <div>
              <span class="text-tv-muted text-xs block">Chain Total</span>
              <span class="font-medium"
                    :class="(group.roll_chain.cumulative_realized_pnl + getGroupOpenPnL(group)) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                <span v-show="(group.roll_chain.cumulative_realized_pnl + getGroupOpenPnL(group)) < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl + getGroupOpenPnL(group)) }}
              </span>
            </div>
            <div>
              <span class="text-tv-muted text-xs block">Last Rolled</span>
              <span class="text-tv-text text-sm">{{ formatDate(group.roll_chain.last_rolled) }}</span>
            </div>
          </div>
        </div>

      <!-- Option Legs -->
      <div v-if="(group.positions || []).length > 0"
           class="px-1 py-2">
        <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider block mb-3">Option Legs</span>
        <div class="space-y-2">
          <div v-for="leg in sortedLegs(group.positions)" :key="leg.lot_id || leg.symbol"
               class="flex items-center justify-between py-2 border-b border-tv-border/20 last:border-0">
            <div class="flex items-center gap-2">
              <div class="flex flex-col">
                <div class="flex items-center gap-1.5">
                  <span class="text-white text-base font-semibold">{{ getStrikePrice(leg) }}</span>
                  <span :class="getOptionType(leg) === 'Call' ? 'text-tv-green' : 'text-tv-red'" class="text-sm font-medium">
                    {{ getOptionType(leg) }}
                  </span>
                </div>
                <div class="flex items-center gap-2 text-sm text-tv-muted">
                  <span>{{ getExpirationDate(leg) }}</span>
                  <span :class="getDTE(leg) <= 7 ? 'text-tv-red' : getDTE(leg) <= 21 ? 'text-tv-amber' : ''">
                    {{ getDTE(leg) }}d
                  </span>
                </div>
              </div>
            </div>
            <div class="text-right">
              <span class="font-semibold text-base block"
                    :class="calculateLegPnL(leg) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                ${{ formatNumber(calculateLegPnL(leg)) }}
              </span>
              <div class="flex items-center gap-3 text-sm text-tv-muted justify-end">
                <span>Cost ${{ formatNumber(leg.cost_basis || 0) }}</span>
                <span>Mkt ${{ formatNumber(calculateLegMarketValue(leg)) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Equity Section -->
      <div v-if="(group.equityLegs || []).length > 0"
           class="px-1 py-2">
        <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider block mb-3">Shares</span>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span class="text-tv-muted text-xs block">Quantity</span>
            <span class="text-tv-text font-medium">{{ group.equitySummary?.quantity || 0 }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-xs block">Avg Price</span>
            <span class="text-tv-text">${{ formatNumber(group.equitySummary?.average_price || 0) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-xs block">Cost Basis</span>
            <span class="text-tv-muted">${{ formatNumber(group.equitySummary?.cost_basis || 0) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-xs block">Market Value</span>
            <span class="text-tv-muted">${{ formatNumber(calculateEquityMarketValue(group)) }}</span>
          </div>
        </div>
      </div>

      <!-- Badges / Tags -->
      <div v-if="(group.rollAnalysis?.badges?.length > 0) || (group.tags?.length > 0)"
           class="px-1 py-2">
        <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider block mb-3">Signals & Tags</span>
        <div class="flex flex-wrap gap-2">
          <span v-for="badge in (group.rollAnalysis?.badges || [])" :key="badge.label"
                class="text-xs px-2.5 py-1 rounded-sm border"
                :class="{
                  'bg-tv-green/20 text-tv-green border-tv-green/50': badge.color === 'green',
                  'bg-tv-red/20 text-tv-red border-tv-red/50': badge.color === 'red',
                  'bg-tv-amber/20 text-tv-amber border-tv-amber/50': badge.color === 'yellow',
                  'bg-tv-orange/20 text-tv-orange border-tv-orange/50': badge.color === 'orange'
                }">{{ badge.label }}</span>
          <span v-for="tag in (group.tags || [])" :key="tag.id"
                class="text-xs px-2.5 py-1 rounded-full border"
                :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
            {{ tag.name }}
          </span>
        </div>
      </div>

      <!-- Roll Analysis -->
      <div v-if="group.rollAnalysis" class="px-1 py-3">
        <div class="flex items-center gap-2 mb-3">
          <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider">Roll Analysis</span>
          <button v-if="group.realized_pnl !== 0"
                  @click.stop="toggleRollAnalysisMode()"
                  class="text-[11px] px-2 py-0.5 rounded-sm border transition-colors"
                  :class="rollAnalysisMode === 'chain'
                    ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50'
                    : 'bg-tv-panel text-tv-muted border-tv-border/50'">
            {{ rollAnalysisMode === 'chain' ? 'Chain' : 'Open' }}
          </button>
        </div>

        <!-- P&L Status -->
        <div class="mb-5 pb-4 border-b border-tv-border/15">
          <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-3">P&L Status</div>
          <div class="space-y-2.5">
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">{{ group.rollAnalysis.pnlLabel }}</span>
              <span class="text-base font-semibold" :class="group.rollAnalysis.pnlPositive ? 'text-tv-green' : 'text-tv-red'">
                {{ group.rollAnalysis.pnlValue }}
              </span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Remaining Reward</span>
              <span class="text-base font-semibold text-tv-green">${{ group.rollAnalysis.rewardRemaining }}</span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Remaining Risk</span>
              <span class="text-base font-semibold text-tv-red">${{ group.rollAnalysis.riskRemaining }}</span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Reward:Risk</span>
              <span class="text-base font-semibold" :class="group.rollAnalysis.rewardToRiskRaw < (group.rollAnalysis.isCredit ? 0.3 : 0.6) ? 'text-tv-orange' : 'text-tv-text'">
                {{ group.rollAnalysis.rewardToRisk }}
              </span>
            </div>
          </div>
        </div>

        <!-- Greeks -->
        <div class="mb-5 pb-4 border-b border-tv-border/15">
          <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-3">Greeks</div>
          <div class="space-y-2.5">
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Net Delta</span>
              <span class="text-base font-semibold"
                    :class="group.rollAnalysis.netDelta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netDelta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                {{ group.rollAnalysis.netDelta.toFixed(2) }}
              </span>
            </div>
            <div v-if="group.rollAnalysis.qtyGcd > 1" class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Delta/Qty</span>
              <span class="text-base font-semibold"
                    :class="group.rollAnalysis.deltaPerQty > 0.01 ? 'text-tv-green' : group.rollAnalysis.deltaPerQty < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                {{ group.rollAnalysis.deltaPerQty.toFixed(2) }}
              </span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Theta/Day</span>
              <span class="text-base font-semibold"
                    :class="group.rollAnalysis.netTheta > 0.01 ? 'text-tv-green' : group.rollAnalysis.netTheta < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                ${{ group.rollAnalysis.netTheta.toFixed(2) }}
              </span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Gamma</span>
              <span class="text-base font-semibold text-tv-text">{{ group.rollAnalysis.netGamma.toFixed(2) }}</span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Vega</span>
              <span class="text-base font-semibold text-tv-text">{{ group.rollAnalysis.netVega.toFixed(2) }}</span>
            </div>
          </div>
        </div>

        <!-- Context -->
        <div class="mb-4">
          <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-3">Context</div>
          <div class="space-y-2.5">
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Near Short</span>
              <span class="text-base font-semibold" :class="parseFloat(group.rollAnalysis.proximityToShort) < 3 ? 'text-tv-amber' : 'text-tv-text'">
                {{ group.rollAnalysis.proximityToShort }}%
              </span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">Delta Sat.</span>
              <span class="text-base font-semibold" :class="parseFloat(group.rollAnalysis.deltaSaturation) >= 65 ? (group.rollAnalysis.isCredit ? 'text-tv-red' : 'text-tv-orange') : 'text-tv-text'">
                {{ group.rollAnalysis.deltaSaturation }}%
              </span>
            </div>
            <div class="flex justify-between items-baseline">
              <span class="text-sm text-tv-muted">EV</span>
              <span class="text-base font-semibold"
                    :class="group.rollAnalysis.ev > 0.01 ? 'text-tv-green' : group.rollAnalysis.ev < -0.01 ? 'text-tv-red' : 'text-tv-text'">
                ${{ group.rollAnalysis.ev.toFixed(0) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Signals -->
        <div v-if="group.rollAnalysis.signals?.length" class="space-y-1.5">
          <div v-for="signal in group.rollAnalysis.signals" :key="signal.id"
               class="pl-3 py-2 border-l-2 text-sm text-tv-text bg-tv-bg/50 rounded-r"
               :class="{
                 'border-tv-red': signal.color === 'red',
                 'border-tv-amber': signal.color === 'orange' || signal.color === 'yellow',
                 'border-tv-green': signal.color === 'green',
                 'border-tv-blue': signal.color === 'blue',
               }">
            <i class="fas text-[10px] mr-1.5"
               :class="{
                 'fa-circle-exclamation text-tv-red': signal.type === 'action' && signal.color === 'red',
                 'fa-triangle-exclamation text-tv-amber': signal.type === 'action' && signal.color !== 'red',
                 'fa-eye text-tv-amber': signal.type === 'warning',
                 'fa-circle-check text-tv-blue': signal.type === 'hold',
                 'fa-circle-check text-tv-green': signal.color === 'green',
               }"></i>
            {{ signal.message }}
          </div>
        </div>
      </div>

      <!-- Notes -->
      <div class="px-1 py-2">
        <span class="text-xs font-semibold text-tv-muted uppercase tracking-wider block mb-3">Notes</span>
        <textarea :value="getPositionComment(group)"
                  @input="updatePositionComment(group, $event.target.value)"
                  rows="4"
                  class="w-full bg-tv-bg text-tv-text text-sm border border-tv-border/30 rounded px-3 py-2 resize-none outline-none focus:border-tv-blue/50"
                  placeholder="Add notes about this position..."></textarea>
      </div>

      <!-- Quick Links -->
      <div class="flex gap-3">
        <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying) + '&group=' + encodeURIComponent(group.group_id)"
           class="flex-1 text-center bg-tv-panel border border-tv-border rounded-lg py-3 text-sm text-tv-blue active:bg-tv-border/30 min-h-[44px]">
          <i class="fas fa-book mr-1.5"></i>View in Ledger
        </a>
      </div>
      </div><!-- /sections -->
    </div><!-- /detail content -->

    <!-- Roll Chain Modal -->
    <RollChainModal
      :groupId="rollChainGroupId"
      :underlying="rollChainUnderlying"
      :openPnl="rollChainOpenPnl"
      @close="rollChainGroupId = null"
    />
  </div>
</template>
