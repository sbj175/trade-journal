<script setup>
import { formatNumber } from '@/lib/formatters'

defineProps({
  quote: { type: Object, default: null },
})
</script>

<template>
  <template v-if="quote">
    <div class="flex items-center gap-2">
      <div class="w-20 px-2 py-1 rounded-sm text-base font-medium border text-right"
           style="font-variant-numeric: tabular-nums"
           :class="(quote.change || 0) >= 0 ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-border text-tv-muted border-tv-border'">
        {{ formatNumber(quote.price || 0) }}
      </div>
      <div class="w-16 text-right text-sm"
           style="font-variant-numeric: tabular-nums"
           :class="(quote.change || 0) >= 0 ? 'text-tv-green' : 'text-tv-muted'">
        {{ ((quote.change || 0) >= 0 ? '+' : '') + (quote.changePercent || 0).toFixed(2) + '%' }}
      </div>
    </div>
  </template>
  <template v-else>
    <span class="text-tv-muted text-sm"><i class="fas fa-spinner fa-spin"></i></span>
  </template>
</template>
