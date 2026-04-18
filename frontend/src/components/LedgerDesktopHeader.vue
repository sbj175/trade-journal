<script setup>
import { LEDGER_COLS_CLASS } from '@/lib/ledgerDesktopCols'

defineProps({ sortColumn: String, sortDirection: String })
defineEmits(['sort'])
</script>

<template>
  <div :class="LEDGER_COLS_CLASS"
       class="hidden md:grid py-2 text-xs uppercase tracking-wider text-tv-muted border-b border-tv-border bg-tv-panel">
    <!-- chevron spacer -->
    <div></div>
    <!-- logo spacer -->
    <div></div>

    <!-- Symbol -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'underlying')">
      Symbol
      <span v-show="sortColumn === 'underlying'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Strategy (not sortable) -->
    <div>Strategy</div>

    <!-- Status -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'status')">
      Status
      <span v-show="sortColumn === 'status'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Opened -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'opening_date')">
      Opened
      <span v-show="sortColumn === 'opening_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Closed -->
    <div class="cursor-pointer hover:text-tv-text flex items-center gap-1"
         @click="$emit('sort', 'closing_date')">
      Closed
      <span v-show="sortColumn === 'closing_date'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Rolls (center, not sortable) -->
    <div class="text-center">Rolls</div>

    <!-- Notes spacer -->
    <div></div>

    <!-- Initial Premium -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'initial_premium')">
      Initial Prem
      <span v-show="sortColumn === 'initial_premium'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- Realized P&L -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'realized_pnl')">
      Realized P&amp;L
      <span v-show="sortColumn === 'realized_pnl'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>

    <!-- % Return -->
    <div class="text-right cursor-pointer hover:text-tv-text flex items-center justify-end gap-1"
         @click="$emit('sort', 'return_percent')">
      % Return
      <span v-show="sortColumn === 'return_percent'" class="text-tv-blue">{{ sortDirection === 'asc' ? '▲' : '▼' }}</span>
    </div>
  </div>
</template>
