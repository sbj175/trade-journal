<script setup>
import { formatNumber, formatDate, pnlColorClass } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import StreamingPrice from '@/components/StreamingPrice.vue'
import { EQUITIES_COLS_CLASS } from '@/lib/equitiesDesktopCols'
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
  <div>
    <!-- Summary row -->
    <div :class="[EQUITIES_COLS_CLASS, item.equityLegs.length > 1 ? 'cursor-pointer' : '']"
         class="min-h-12 py-1.5 hover:bg-tv-border/20 transition-colors"
         @click="item.equityLegs.length > 1 && $emit('toggle-expanded', item.groupId)">

      <!-- Chevron -->
      <div>
        <BaseIcon v-if="item.equityLegs.length > 1" name="chevron-right" size="xs" class="text-tv-muted transition-transform duration-150" :class="{ 'rotate-90': expandedRows[item.groupId] }" />
      </div>

      <!-- Symbol + badges -->
      <div class="flex items-center gap-2 min-w-0">
        <span class="text-base font-semibold text-tv-text truncate">{{ item.underlying }}</span>
        <span v-show="selectedAccount === ''"
              class="text-xl leading-none flex-none"
              :style="{ color: accountDotColor(getAccountSymbol(item.accountNumber)) }"
              :title="getAccountTooltip(accounts, item.accountNumber)">●</span>
        <span v-if="item.hasOptions"
              class="text-[10px] px-1.5 py-0.5 rounded bg-tv-blue/20 text-tv-blue border border-tv-blue/30 flex-none">
          {{ item.optionStrategy }}
        </span>
        <span v-if="item.equityLegs.length > 1" class="text-[10px] text-tv-muted flex-none">
          {{ item.equityLegs.length }} lots
        </span>
      </div>

      <!-- Shares -->
      <div class="text-right text-base font-medium"
           :class="item.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
        {{ item.quantity }}
      </div>

      <!-- Unrealized P&L -->
      <div class="text-right text-base font-medium"
           :class="pnlColorClass(item.unrealizedPnL)">
        {{ item.marketValue ? '$' + formatNumber(item.unrealizedPnL) : '' }}
      </div>

      <!-- P&L % -->
      <div class="text-right text-base"
           :class="item.pnlPercent > 0 ? 'text-tv-green' : item.pnlPercent < 0 ? 'text-tv-red' : 'text-tv-muted'">
        {{ item.marketValue ? formatNumber(item.pnlPercent) + '%' : '' }}
      </div>

      <!-- Price -->
      <div>
        <StreamingPrice :quote="item.underlyingQuote" />
      </div>

      <!-- Market Value -->
      <div class="text-right text-base"
           :class="item.marketValue ? 'text-tv-text' : 'text-tv-muted'">
        {{ item.marketValue ? '$' + formatNumber(item.marketValue) : '—' }}
      </div>

      <!-- Avg Price -->
      <div class="text-right text-tv-muted text-base">${{ formatNumber(item.avgPrice) }}</div>

      <!-- Cost Basis -->
      <div class="text-right text-tv-muted text-base">${{ formatNumber(item.costBasis) }}</div>
    </div>

    <!-- Expanded lots -->
    <div v-if="expandedRows[item.groupId] && item.equityLegs.length > 1"
         class="bg-tv-bg border-t border-tv-border/30">
      <div v-for="leg in item.equityLegs" :key="leg.lot_id"
           :class="EQUITIES_COLS_CLASS"
           class="py-1.5 text-sm hover:bg-tv-border/10">
        <!-- Chevron spacer -->
        <div></div>

        <!-- Date + derivation type -->
        <div class="flex items-center gap-2 min-w-0">
          <span v-if="leg.entry_date" class="text-tv-muted text-xs">{{ formatDate(leg.entry_date) }}</span>
          <span v-if="leg.derivation_type"
                class="text-[10px] px-1.5 py-0.5 rounded bg-tv-muted/15 text-tv-muted border border-tv-muted/20 uppercase flex-none">
            {{ leg.derivation_type }}
          </span>
        </div>

        <!-- Signed quantity (Shares col) -->
        <div class="text-right font-medium"
             :class="leg.quantity_direction === 'Long' ? 'text-tv-green' : 'text-tv-red'">
          {{ leg.quantity_direction === 'Short' ? -leg.quantity : leg.quantity }}
        </div>

        <!-- Lot P&L (P&L col) -->
        <div class="text-right font-medium"
             :class="leg.lotPnL > 0 ? 'text-tv-green' : leg.lotPnL < 0 ? 'text-tv-red' : 'text-tv-muted'">
          {{ leg.lotMarketValue ? '$' + formatNumber(leg.lotPnL) : '' }}
        </div>

        <!-- P&L % spacer -->
        <div></div>

        <!-- Price spacer (live price is symbol-level, not per-lot) -->
        <div></div>

        <!-- Lot market value (Mkt Value col) -->
        <div class="text-right"
             :class="leg.lotMarketValue ? 'text-tv-text' : 'text-tv-muted'">
          {{ leg.lotMarketValue ? '$' + formatNumber(leg.lotMarketValue) : '—' }}
        </div>

        <!-- Entry price (Avg Price col) -->
        <div class="text-right text-tv-muted">${{ formatNumber(leg.entry_price) }}</div>

        <!-- Cost basis (Cost Basis col) -->
        <div class="text-right text-tv-muted">${{ formatNumber(Math.abs(leg.cost_basis)) }}</div>
      </div>
    </div>
  </div>
</template>
