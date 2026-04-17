<script setup>
import { DESKTOP_COLS_CLASS } from './positionsDesktopCols.js'

defineProps({
  sortColumn: String,
  sortDirection: String,
})
defineEmits(['sort'])
</script>

<template>
  <div :class="DESKTOP_COLS_CLASS"
       class="hidden md:grid py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <!-- Chevron spacer -->
    <div></div>

    <!-- Symbol -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'underlying')">
      Symbol
      <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- IVR -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'ivr')">
      IVR
      <span v-show="sortColumn === 'ivr'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Price -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'price')">
      Price
      <span v-show="sortColumn === 'price'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Ledger spacer -->
    <div></div>

    <!-- Strategy -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'strategy')">
      Strategy
      <span v-show="sortColumn === 'strategy'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- DTE -->
    <div class="text-center cursor-pointer hover:text-tv-text flex items-center justify-center gap-1"
         @click="$emit('sort', 'dte')">
      DTE
      <span v-show="sortColumn === 'dte'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Cost Basis -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'cost_basis')">
      Cost Basis
      <span v-show="sortColumn === 'cost_basis'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Net Liq -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'net_liq')">
      Net Liq
      <span v-show="sortColumn === 'net_liq'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Open P&L -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'open_pnl')">
      Open P&L
      <span v-show="sortColumn === 'open_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- % Rtn -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'pnl_percent')"
         title="Return on capital: Total P&L ÷ Cost Basis. Measures how much you've made or lost relative to what you put in.">
      % Rtn
      <span v-show="sortColumn === 'pnl_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Notes spacer -->
    <div></div>

    <!-- Tags / Signals -->
    <div class="text-right">Tags / Signals</div>
  </div>
</template>
