<script setup>
import { EQUITIES_COLS_CLASS } from '@/lib/equitiesDesktopCols'

defineProps({ sortColumn: String, sortDirection: String })
defineEmits(['sort'])
</script>

<template>
  <div :class="EQUITIES_COLS_CLASS"
       class="hidden md:grid py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <!-- Chevron spacer -->
    <div></div>

    <!-- Symbol -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'underlying')">
      Symbol
      <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Price (live — not sortable) -->
    <div>Price</div>

    <!-- Shares -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'quantity')">
      Shares
      <span v-show="sortColumn === 'quantity'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Avg Price -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'avg_price')">
      Avg Price
      <span v-show="sortColumn === 'avg_price'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Cost Basis -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'cost_basis')">
      Cost Basis
      <span v-show="sortColumn === 'cost_basis'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Market Value -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'market_value')">
      Mkt Value
      <span v-show="sortColumn === 'market_value'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- P&L -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'pnl')">
      P&amp;L
      <span v-show="sortColumn === 'pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- P&L % -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'pnl_percent')">
      P&amp;L %
      <span v-show="sortColumn === 'pnl_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>
  </div>
</template>
