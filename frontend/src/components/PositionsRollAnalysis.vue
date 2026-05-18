<script setup>
defineProps({
  group: Object,
  rollAnalysisMode: String,
})
defineEmits(['toggle-roll-analysis-mode'])
</script>

<template>
  <div class="mx-4 mb-3 p-3 bg-tv-panel rounded border border-l-2 border-tv-blue/30">
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-tv-text">Analysis</span>
        <button v-if="group.rollAnalysis.kind === 'covered_call' ? group.rollAnalysis.showModeToggle : group.realized_pnl !== 0"
                @click.stop="$emit('toggle-roll-analysis-mode')"
                class="text-[10px] px-1.5 py-0 rounded-sm border leading-4 transition-colors cursor-pointer"
                :class="rollAnalysisMode === 'chain'
                  ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50'
                  : 'bg-tv-panel text-tv-muted border-tv-border/50 hover:text-tv-text'"
                :title="rollAnalysisMode === 'chain'
                  ? 'Chain: P&L and targets include roll costs — shows true trade performance.'
                  : 'Open: P&L and targets based on current position only, ignoring prior rolls.'">
          {{ rollAnalysisMode === 'chain' ? 'Chain' : 'Open' }}
        </button>
      </div>
    </div>

    <!-- Covered-call branch (OPT-295): 2-col grid for label/value rows. -->
    <div v-if="group.rollAnalysis.kind === 'covered_call'" class="text-xs">
      <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">P&amp;L Status</div>
      <div class="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
        <span class="text-tv-muted">Premium Received</span>
        <span class="font-medium text-tv-green">${{ group.rollAnalysis.currentPremiumFormatted }}</span>

        <template v-if="group.rollAnalysis.cumulativePriorRealized !== 0">
          <span class="text-tv-muted">Chain Realized (prior)</span>
          <span class="font-medium" :class="group.rollAnalysis.cumulativePriorRealized >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="group.rollAnalysis.cumulativePriorRealized < 0">-</span>${{ group.rollAnalysis.cumulativePriorRealizedAbsFormatted }}
          </span>
        </template>

        <template v-if="group.rollAnalysis.breakEvenPerContract != null && group.rollAnalysis.breakEvenPerContract > 0">
          <span class="text-tv-muted border-b border-dotted border-tv-muted/40 cursor-help w-fit"
                :title="group.rollAnalysis.useChainMode
                  ? 'Buy-to-close at or below this per-contract debit keeps the entire chain (this leg + all prior rolls) net-flat or in profit.'
                  : 'Buy-to-close at or below this per-contract debit closes the current leg at break-even.'">
            {{ group.rollAnalysis.useChainMode ? 'Chain B/E Close' : 'B/E Close' }}
          </span>
          <span class="font-medium text-tv-text">${{ group.rollAnalysis.breakEvenPerContractFormatted }}</span>
        </template>
        <template v-else-if="group.rollAnalysis.breakEvenPerContract != null">
          <span class="text-tv-muted border-b border-dotted border-tv-muted/40 cursor-help w-fit"
                :title="'Chain is underwater by $' + group.rollAnalysis.breakEvenTotalAbsFormatted + '; closing this leg alone cannot recover.'">
            Chain B/E Close
          </span>
          <span class="font-medium text-tv-red">unreachable</span>
        </template>
      </div>
    </div>

    <!-- Compact 3-column layout (spread strategies) -->
    <div v-else>
    <div class="flex gap-6 text-xs">
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

      <!-- Context: per-share prices, sorted high → low -->
      <div class="space-y-1 border-l border-tv-border/20 pl-6">
        <div class="text-[10px] text-tv-muted uppercase tracking-wider font-semibold mb-1.5">Context</div>
        <div v-for="row in group.rollAnalysis.contextRows" :key="row.label"
             class="flex justify-between gap-3"
             :class="row.tooltip ? 'cursor-help' : ''"
             :title="row.tooltip || ''">
          <span class="text-tv-muted"
                :class="row.tooltip ? 'border-b border-dotted border-tv-muted/40' : ''">{{ row.label }}</span>
          <span class="font-medium text-tv-text">${{ row.value.toFixed(2) }}</span>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>
