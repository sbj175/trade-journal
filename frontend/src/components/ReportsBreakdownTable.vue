<script setup>
import { formatNumber, formatPercent } from '@/lib/formatters'

defineProps({
  strategyBreakdown: Array,
  columns: Array,
  sortColumn: String,
  sortDirection: String,
})
defineEmits(['sort'])
</script>

<template>
  <!-- Desktop Table -->
  <div class="hidden md:block bg-tv-row border border-tv-border rounded">
    <div class="flex items-center px-4 py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel/50 sticky top-14 z-10">
      <span v-for="col in columns" :key="col.key"
            class="cursor-pointer hover:text-tv-text flex items-center gap-1"
            :class="[col.width, col.align]"
            @click="$emit('sort', col.key)">
        {{ col.label }}
        <span v-if="sortColumn === col.key" class="text-tv-blue">
          {{ sortDirection === 'asc' ? '▲' : '▼' }}
        </span>
      </span>
      <span class="w-28 text-right">Avg Risk</span>
      <span class="w-28 text-right">Avg Reward</span>
    </div>

    <div class="divide-y divide-tv-border">
      <div v-for="row in strategyBreakdown" :key="row.strategy"
           class="flex items-center px-4 h-12 hover:bg-tv-border/20 transition-colors">
        <span class="w-48 font-medium text-tv-text">{{ row.strategy }}</span>
        <span class="w-28 text-center">
          {{ row.totalTrades }}
          <span class="text-tv-muted text-sm">
            (<span class="text-tv-green">{{ row.wins }}</span>/<span class="text-tv-red">{{ row.losses }}</span>)
          </span>
        </span>
        <span class="w-24 text-right" :class="row.winRate >= 50 ? 'text-tv-green' : 'text-tv-red'">
          {{ formatPercent(row.winRate) }}%
        </span>
        <span class="w-32 text-right font-medium" :class="row.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="row.totalPnl < 0">-</span>${{ formatNumber(Math.abs(row.totalPnl), 0) }}
        </span>
        <span class="w-28 text-right" :class="row.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-if="row.avgPnl < 0">-</span>${{ formatNumber(Math.abs(row.avgPnl), 0) }}
        </span>
        <span class="w-28 text-right text-tv-green">${{ formatNumber(row.avgWin, 0) }}</span>
        <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.avgLoss), 0) }}</span>
        <span class="w-28 text-right text-tv-green">${{ formatNumber(row.largestWin, 0) }}</span>
        <span class="w-28 text-right text-tv-red">-${{ formatNumber(Math.abs(row.largestLoss), 0) }}</span>
        <span class="w-28 text-right text-tv-amber">
          <template v-if="row.avgMaxRisk > 0">${{ formatNumber(row.avgMaxRisk, 0) }}</template>
          <span v-else class="text-tv-muted">-</span>
        </span>
        <span class="w-28 text-right text-tv-cyan">
          <template v-if="row.avgMaxReward > 0">${{ formatNumber(row.avgMaxReward, 0) }}</template>
          <span v-else class="text-tv-muted">-</span>
        </span>
      </div>
    </div>

    <div v-if="strategyBreakdown.length === 0" class="px-4 py-16 text-center text-tv-muted">
      <i class="fas fa-chart-bar text-3xl mb-3"></i>
      <p>No closed trades found for the selected filters.</p>
    </div>
  </div>

  <!-- Mobile Cards -->
  <div class="md:hidden space-y-2">
    <div v-for="row in strategyBreakdown" :key="'m-' + row.strategy"
         class="bg-tv-panel border border-tv-border rounded-lg p-4">
      <!-- Strategy name -->
      <div class="text-sm font-semibold text-tv-text mb-2">{{ row.strategy }}</div>

      <!-- Row 1: Trades + Win Rate + Total P&L -->
      <div class="grid grid-cols-3 gap-2 text-xs mb-2">
        <div>
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Trades</div>
          <div class="text-tv-text font-medium">
            {{ row.totalTrades }}
            <span class="text-[10px] text-tv-muted">
              (<span class="text-tv-green">{{ row.wins }}</span>/<span class="text-tv-red">{{ row.losses }}</span>)
            </span>
          </div>
        </div>
        <div>
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Win Rate</div>
          <div class="font-medium" :class="row.winRate >= 50 ? 'text-tv-green' : 'text-tv-red'">
            {{ formatPercent(row.winRate) }}%
          </div>
        </div>
        <div class="text-right">
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Total P&L</div>
          <div class="font-semibold" :class="row.totalPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="row.totalPnl < 0">-</span>${{ formatNumber(Math.abs(row.totalPnl), 0) }}
          </div>
        </div>
      </div>

      <!-- Row 2: Avg P&L + Best + Worst -->
      <div class="grid grid-cols-3 gap-2 text-xs pt-2 border-t border-tv-border/30">
        <div>
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Avg / Trade</div>
          <div class="font-medium" :class="row.avgPnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-if="row.avgPnl < 0">-</span>${{ formatNumber(Math.abs(row.avgPnl), 0) }}
          </div>
        </div>
        <div>
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Best</div>
          <div class="text-tv-green font-medium">${{ formatNumber(row.largestWin, 0) }}</div>
        </div>
        <div class="text-right">
          <div class="text-tv-muted uppercase tracking-wide text-[9px] mb-0.5">Worst</div>
          <div class="text-tv-red font-medium">-${{ formatNumber(Math.abs(row.largestLoss), 0) }}</div>
        </div>
      </div>
    </div>

    <div v-if="strategyBreakdown.length === 0" class="py-16 text-center text-tv-muted">
      <i class="fas fa-chart-bar text-3xl mb-3"></i>
      <p>No closed trades found for the selected filters.</p>
    </div>
  </div>
</template>
