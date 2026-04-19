<script setup>
import { formatNumber, formatPercent } from '@/lib/formatters'

defineProps({ summary: Object })
</script>

<template>
  <div class="grid grid-cols-3 md:grid-cols-6 gap-2 md:gap-3 mb-3 md:mb-4">
    <!-- Total P&L -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2"
         :class="summary.totalPnl >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Total P&L</div>
      <div class="text-base md:text-2xl font-bold leading-tight" :class="summary.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
        <span v-if="summary.totalPnl < 0">-</span>${{ formatNumber(Math.abs(summary.totalPnl), 0) }}
      </div>
      <div class="text-[10px] md:text-xs text-tv-muted mt-0.5 md:mt-1">{{ summary.totalTrades }} trades</div>
    </div>

    <!-- Win Rate -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2 border-l-tv-blue">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Win Rate</div>
      <div class="text-base md:text-2xl font-bold text-tv-blue leading-tight">{{ formatPercent(summary.winRate) }}%</div>
      <div class="text-[10px] md:text-xs text-tv-muted mt-0.5 md:mt-1">
        <span class="text-tv-green">{{ summary.wins }}</span>W / <span class="text-tv-red">{{ summary.losses }}</span>L
      </div>
    </div>

    <!-- Avg P&L -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2"
         :class="summary.avgPnl >= 0 ? 'border-l-tv-green' : 'border-l-tv-red'">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Avg / Trade</div>
      <div class="text-base md:text-2xl font-bold leading-tight" :class="summary.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
        <span v-if="summary.avgPnl < 0">-</span>${{ formatNumber(Math.abs(summary.avgPnl), 0) }}
      </div>
      <div class="text-[10px] md:text-xs text-tv-muted mt-0.5 md:mt-1 hidden md:block">
        W: ${{ formatNumber(summary.avgWin, 0) }} | L: ${{ formatNumber(Math.abs(summary.avgLoss), 0) }}
      </div>
    </div>

    <!-- Largest Win -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2 border-l-tv-green">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Best Win</div>
      <div class="text-base md:text-2xl font-bold text-tv-green leading-tight">${{ formatNumber(summary.largestWin, 0) }}</div>
    </div>

    <!-- Largest Loss -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2 border-l-tv-red">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Worst Loss</div>
      <div class="text-base md:text-2xl font-bold text-tv-red leading-tight">-${{ formatNumber(Math.abs(summary.largestLoss), 0) }}</div>
    </div>

    <!-- Risk/Reward -->
    <div class="bg-tv-panel border border-tv-border p-2.5 md:p-4 border-l-2 border-l-tv-amber">
      <div class="text-tv-muted text-[9px] md:text-xs uppercase tracking-wider mb-1 md:mb-2 leading-tight">Risk / Reward</div>
      <div class="text-sm md:text-lg font-bold leading-tight">
        <span class="text-tv-amber">${{ formatNumber(summary.avgMaxRisk, 0) }}</span>
        <span class="text-tv-muted mx-0.5 md:mx-1">/</span>
        <span class="text-tv-cyan">${{ formatNumber(summary.avgMaxReward, 0) }}</span>
      </div>
    </div>
  </div>
</template>
