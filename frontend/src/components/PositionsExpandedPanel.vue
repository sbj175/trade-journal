<script setup>
import { formatNumber, formatDate } from '@/lib/formatters'
import {
  getOptionType, getSignedQuantity, getExpirationDate, getStrikePrice, getDTE,
  sortedLegs,
} from '@/composables/usePositionsDisplay'
import PositionsRollAnalysis from '@/components/PositionsRollAnalysis.vue'

const props = defineProps({
  group: Object,
  rollAnalysisMode: String,
  notesState: Object,
  positionCalc: Object,
})
defineEmits(['toggle-roll-analysis-mode', 'open-roll-chain'])
</script>

<template>
  <div class="bg-tv-bg border-t border-tv-border">
    <div class="mx-4 my-3 p-3 bg-tv-panel rounded border border-tv-border font-mono">
      <div class="flex gap-4">
        <div class="flex-shrink-0 space-y-1">

          <!-- Option legs -->
          <template v-if="(group.positions || []).length > 0">
            <div>
              <div class="flex items-center text-xs text-tv-muted pb-1 border-b border-tv-border/30">
                <span class="w-16 text-center mx-2">Exp</span>
                <span class="w-10">DTE</span>
                <span class="w-16 text-center mx-2">Strike</span>
                <span class="w-6">Type</span>
                <span class="w-[6.5rem] text-right ml-4">Cost Basis</span>
                <span class="w-20 text-right ml-3">Net Liq</span>
                <span class="w-20 text-right ml-3">Open P/L</span>
              </div>
              <div v-for="leg in sortedLegs(group.positions)" :key="leg.lot_id || leg.symbol"
                   class="flex items-center text-sm py-0.5">
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
                  ${{ formatNumber(positionCalc.calculateLegMarketValue(leg)) }}
                </span>
                <span class="w-20 text-right ml-3 font-medium"
                      :class="positionCalc.calculateLegPnL(leg) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                  ${{ formatNumber(positionCalc.calculateLegPnL(leg)) }}
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
                  ${{ formatNumber(positionCalc.calculateEquityMarketValue(group)) }}
                </span>
                <span class="w-20 text-right ml-3 font-medium"
                      :class="(positionCalc.calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                  ${{ formatNumber(positionCalc.calculateEquityMarketValue(group) + (group.equityLegs || []).reduce((s, l) => s + (l.cost_basis || 0), 0)) }}
                </span>
              </div>
            </div>
          </template>

          <!-- Empty legs message -->
          <template v-if="(group.positions || []).length === 0 && (group.equityLegs || []).length === 0">
            <div class="text-xs text-tv-muted py-1">
              <span v-show="group.has_assignment">All positions assigned/exercised</span>
              <span v-show="!group.has_assignment">No open legs</span>
            </div>
          </template>

          <!-- Chain summary -->
          <div class="flex items-center text-xs text-tv-muted mt-2 pt-1 border-t border-tv-border/30 gap-4">
            <span>Opened: {{ formatDate(group.roll_chain ? group.roll_chain.first_opened : group.opening_date) || 'N/A' }}</span>
            <span>Orders: {{ group.order_count || 1 }}</span>
            <span v-if="group.roll_chain" class="text-tv-blue cursor-pointer hover:underline"
                  @click.stop="$emit('open-roll-chain', group)">
              Rolls: {{ group.roll_chain.roll_count }}
            </span>
            <span v-show="group.realized_pnl !== 0"
                  :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
              Realized: ${{ formatNumber(group.realized_pnl) }}
            </span>
          </div>

          <!-- Roll chain cumulative stats -->
          <div v-if="group.roll_chain" class="flex items-center text-xs mt-1 gap-4">
            <span class="text-tv-muted">Chain Realized:
              <span :class="group.roll_chain.cumulative_realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
                ${{ formatNumber(group.roll_chain.cumulative_realized_pnl) }}
              </span>
            </span>
            <span class="text-tv-muted">Chain Total:
              <span :class="(group.roll_chain.cumulative_realized_pnl + group.openPnL) >= 0 ? 'text-tv-green' : 'text-tv-red'">
                ${{ formatNumber(group.roll_chain.cumulative_realized_pnl + group.openPnL) }}
              </span>
            </span>
            <span class="text-tv-muted">Last Rolled: {{ formatDate(group.roll_chain.last_rolled) }}</span>
          </div>
        </div>

        <!-- Notes -->
        <div class="flex-1 min-w-0">
          <div class="text-xs text-tv-muted pb-1 border-b border-tv-border/30 mb-1">Notes</div>
          <textarea :value="notesState.getPositionComment(group)"
                    @input="notesState.updatePositionComment(group, $event.target.value)"
                    @click.stop
                    rows="3"
                    class="w-full bg-transparent text-tv-text text-sm font-sans border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                    placeholder="Add notes..."></textarea>
        </div>
      </div>
    </div>

    <!-- Roll Analysis -->
    <PositionsRollAnalysis
      v-if="group.rollAnalysis"
      :group="group"
      :roll-analysis-mode="rollAnalysisMode"
      @toggle-roll-analysis-mode="$emit('toggle-roll-analysis-mode')"
    />
  </div>
</template>
