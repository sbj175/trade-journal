<script setup>
defineProps({
  group: Object,
  rollAnalysisMode: String,
})
defineEmits(['toggle-roll-analysis-mode'])
</script>

<template>
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
                @click.stop="$emit('toggle-roll-analysis-mode')"
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

    <!-- Signals -->
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
