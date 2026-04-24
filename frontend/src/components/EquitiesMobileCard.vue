<script setup>
import { formatNumber, formatDate, pnlColorClass } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import StreamingPrice from '@/components/StreamingPrice.vue'
import BaseIcon from '@/components/BaseIcon.vue'

defineProps({
  item: Object,
  selectedAccount: String,
  accounts: Array,
  expandedRows: Object,
  getAccountSymbol: Function,
})
defineEmits(['toggle-expanded'])
</script>

<template>
  <div class="bg-tv-row border border-tv-border rounded-lg overflow-hidden active:bg-tv-border/20 transition-colors"
       :class="item.equityLegs.length > 1 ? 'cursor-pointer' : ''"
       @click="item.equityLegs.length > 1 && $emit('toggle-expanded', item.groupId)">
    <div class="p-4">
      <!-- Top row: symbol, live price, expand chevron -->
      <div class="flex items-center gap-2 mb-2">
        <span class="text-lg font-semibold text-tv-text">{{ item.underlying }}</span>
        <span v-show="selectedAccount === ''"
              class="text-xl leading-none -ml-1"
              :style="{ color: accountDotColor(getAccountSymbol(item.accountNumber)) }"
              :title="getAccountTooltip(accounts, item.accountNumber)">●</span>
        <span v-if="item.hasOptions"
              class="text-[9px] px-1.5 py-0.5 rounded bg-tv-blue/20 text-tv-blue border border-tv-blue/30 uppercase">
          {{ item.optionStrategy }}
        </span>
        <span v-if="item.equityLegs.length > 1" class="text-[10px] text-tv-muted">
          {{ item.equityLegs.length }} lots
        </span>
        <span class="ml-auto text-sm">
          <StreamingPrice :quote="item.underlyingQuote" />
        </span>
        <BaseIcon v-if="item.equityLegs.length > 1" name="chevron-right" class="text-tv-muted text-[11px] transition-transform duration-150" :class="{ 'rotate-90': expandedRows[item.groupId] }" />
      </div>

      <!-- Shares + P&L row -->
      <div class="flex items-end justify-between mb-2.5">
        <div class="flex items-baseline gap-1.5">
          <span class="text-xl font-semibold"
                :class="item.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
            {{ item.quantity }}
          </span>
          <span class="text-[11px] text-tv-muted">sh &middot; @${{ formatNumber(item.avgPrice) }}</span>
        </div>
        <div class="text-right">
          <div class="text-base font-semibold leading-tight" :class="pnlColorClass(item.unrealizedPnL)">
            {{ item.marketValue ? '$' + formatNumber(item.unrealizedPnL) : '—' }}
          </div>
          <div class="text-[11px] leading-tight"
               :class="item.pnlPercent > 0 ? 'text-tv-green' : item.pnlPercent < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ item.marketValue ? formatNumber(item.pnlPercent) + '%' : '' }}
          </div>
        </div>
      </div>

      <!-- Cost + Mkt Value row -->
      <div class="grid grid-cols-2 gap-2 text-[11px] pt-2 border-t border-tv-border/30">
        <div>
          <div class="text-tv-muted uppercase tracking-wide">Cost</div>
          <div class="text-tv-text text-sm">${{ formatNumber(item.costBasis) }}</div>
        </div>
        <div class="text-right">
          <div class="text-tv-muted uppercase tracking-wide">Mkt Value</div>
          <div class="text-sm" :class="item.marketValue ? 'text-tv-text' : 'text-tv-muted'">
            {{ item.marketValue ? '$' + formatNumber(item.marketValue) : '—' }}
          </div>
        </div>
      </div>
    </div>

    <!-- Expanded lots (mobile) -->
    <div v-if="expandedRows[item.groupId] && item.equityLegs.length > 1"
         class="bg-tv-bg border-t border-tv-border/30 px-3 py-2 space-y-1.5">
      <div v-for="leg in item.equityLegs" :key="'m-lot-' + leg.lot_id"
           class="flex items-center justify-between text-xs">
        <div class="flex items-center gap-1.5 min-w-0">
          <span v-if="leg.entry_date" class="text-tv-muted shrink-0">{{ formatDate(leg.entry_date) }}</span>
          <span v-if="leg.derivation_type"
                class="text-[9px] px-1 py-0.5 rounded bg-tv-muted/15 text-tv-muted border border-tv-muted/20 uppercase">
            {{ leg.derivation_type }}
          </span>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <span class="font-medium"
                :class="leg.quantity_direction === 'Long' ? 'text-tv-green' : 'text-tv-red'">
            {{ leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity }}
          </span>
          <span class="text-tv-muted">@${{ formatNumber(leg.entry_price) }}</span>
          <span class="font-medium min-w-[60px] text-right"
                :class="leg.lotPnL > 0 ? 'text-tv-green' : leg.lotPnL < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ leg.lotMarketValue ? '$' + formatNumber(leg.lotPnL) : '—' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
