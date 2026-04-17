<script setup>
import { formatNumber } from '@/lib/formatters'
import { formatDollar } from './usePositionsDisplay'
import {
  getOptionType, getSignedQuantity, getExpirationDate, getStrikePrice, getDTE,
  sortedLegs,
} from './usePositionsDisplay'
import { tickerLogoUrl, accountDotColor, getAccountTooltip } from '@/lib/constants'

defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  expandedRows: Object,
  notesState: Object,
  tagsState: Object,
  positionCalc: Object,
  hasEquity: Function,
  getAccountSymbol: Function,
})
defineEmits(['open-roll-chain', 'toggle-expanded'])
</script>

<template>
  <!-- Subtotal row -->
  <div v-if="group._isSubtotal"
       class="bg-tv-blue/10 border-l-2 border-tv-blue rounded px-3 py-2 flex items-center justify-between">
    <span class="font-bold text-tv-text">{{ group.displayKey }}</span>
    <div class="text-right">
      <span class="text-xs text-tv-muted mr-2">{{ group._childCount }} pos</span>
      <span class="font-medium"
            :class="group._subtotalOpenPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">
        <span v-show="group._subtotalOpenPnL < 0">-</span>${{ formatDollar(group._subtotalOpenPnL) }}
      </span>
    </div>
  </div>

  <!-- Position card -->
  <div v-else
       class="bg-tv-row border border-tv-border rounded-lg overflow-hidden"
       :class="group.rollAnalysis?.borderColor === 'green' ? 'border-l-2 border-l-tv-green/40' : group.rollAnalysis?.borderColor === 'red' ? 'border-l-2 border-l-tv-red/40' : ''">

    <!-- Card header — tap to navigate to detail -->
    <div class="px-3 py-3 active:bg-tv-border/20" @click="$router.push('/positions/options/' + group.group_id)">
      <!-- Row 1: Symbol + P&L -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 min-w-0 flex-1">
          <img :src="tickerLogoUrl(group.underlying)" alt="" class="w-7 h-7 rounded" loading="lazy">
          <span class="font-bold text-lg text-tv-text">{{ group.displayKey || group.underlying }}</span>
          <span v-show="selectedAccount === ''" class="text-xl leading-none -ml-1"
                :style="{ color: accountDotColor(getAccountSymbol(group.accountNumber)) }"
                :title="getAccountTooltip(accounts, group.accountNumber)">●</span>
          <span v-show="hasEquity(group) && (group.positions || []).length > 0"
                class="text-[11px] text-tv-muted bg-tv-border/50 px-1 rounded">+stk</span>
          <span class="text-sm text-tv-muted">{{ group.strategyLabel }}<span v-if="group.strikes" class="text-tv-text ml-1">{{ group.strikes }}</span><span v-if="group.positionCount"> ({{ group.positionCount }})</span></span>
        </div>
        <div class="text-right shrink-0">
          <div class="font-semibold text-base leading-tight"
               :class="group.openPnL >= 0 ? 'text-tv-green' : 'text-tv-red'">
            <span v-show="group.openPnL < 0">-</span>${{ formatDollar(group.openPnL) }}
          </div>
          <div class="text-xs leading-tight"
               :class="group.pnlPercent !== null ? (parseFloat(group.pnlPercent) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
            {{ group.pnlPercent !== null ? group.pnlPercent + '%' : '' }}
          </div>
        </div>
      </div>

      <!-- Row 2: Key metrics -->
      <div class="flex items-center justify-between mt-2 text-sm text-tv-muted">
        <div class="flex items-center gap-3">
          <span v-if="group.underlyingQuote?.last">
            Price: <span class="text-tv-text font-medium">{{ group.underlyingQuote.last.toFixed(2) }}</span>
          </span>
          <span v-if="group.minDTE !== null"
                :class="group.minDTE <= 21 ? 'font-bold text-tv-amber' : ''">
            {{ group.minDTE }}d DTE
          </span>
          <span :class="group.ivr >= 50 ? 'font-bold text-tv-amber' : ''"
                v-if="group.ivr !== null">
            IVR {{ group.ivr }}
          </span>
        </div>
        <i class="fas fa-chevron-right text-tv-muted/30 text-xs transition-transform duration-200"
           :class="{ 'rotate-90': expandedRows.has(group.groupKey) }"></i>
      </div>

      <!-- Row 3: Cost / Net Liq -->
      <div class="flex items-center gap-4 mt-1.5 text-sm text-tv-muted">
        <span>Cost: <span :class="group.costBasis >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-show="group.costBasis < 0">-</span>${{ formatDollar(group.costBasis) }}
        </span></span>
        <span>Net Liq: <span :class="group.netLiq >= 0 ? 'text-tv-green' : 'text-tv-red'">
          <span v-show="group.netLiq < 0">-</span>${{ formatDollar(group.netLiq) }}
        </span></span>
      </div>

      <!-- Row 4: Roll chain -->
      <div v-if="group.roll_chain" class="flex flex-wrap items-center gap-2 mt-2 text-xs">
        <span class="text-tv-muted">
          Realized:
          <span :class="group.roll_chain.cumulative_realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
            <span v-show="group.roll_chain.cumulative_realized_pnl < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl) }}
          </span>
        </span>
        <span class="text-tv-muted">
          Total:
          <span :class="(group.roll_chain.cumulative_realized_pnl + group.openPnL) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
            <span v-show="(group.roll_chain.cumulative_realized_pnl + group.openPnL) < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl + group.openPnL) }}
          </span>
        </span>
        <button @click.stop="$emit('open-roll-chain', group)"
                class="text-xs px-2.5 py-1 rounded-full bg-tv-blue text-white active:bg-tv-blue/80 cursor-pointer font-medium min-h-[32px]">
          <i class="fas fa-link text-[9px] mr-0.5"></i>{{ group.roll_chain.roll_count }} roll{{ group.roll_chain.roll_count > 1 ? 's' : '' }}
        </button>
      </div>

      <!-- Badges -->
      <div v-if="(group.rollAnalysis?.badges?.length > 0) || (group.tags?.length > 0)"
           class="flex flex-wrap items-center gap-1 mt-1.5">
        <span v-for="badge in (group.rollAnalysis?.badges || [])" :key="badge.label"
              class="text-[10px] px-1.5 py-0.5 rounded-sm border leading-3"
              :class="{
                'bg-tv-green/20 text-tv-green border-tv-green/50': badge.color === 'green',
                'bg-tv-red/20 text-tv-red border-tv-red/50': badge.color === 'red',
                'bg-tv-amber/20 text-tv-amber border-tv-amber/50': badge.color === 'yellow',
                'bg-tv-orange/20 text-tv-orange border-tv-orange/50': badge.color === 'orange'
              }">{{ badge.label }}</span>
        <span v-for="tag in (group.tags || [])" :key="tag.id"
              class="text-[10px] px-1.5 py-0.5 rounded-full border leading-3"
              :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
          {{ tag.name }}
        </span>
      </div>
    </div>

    <!-- Expanded Detail -->
    <div v-if="expandedRows.has(group.groupKey)" class="border-t border-tv-border bg-tv-bg px-3 py-2">
      <div v-if="(group.positions || []).length > 0" class="space-y-1">
        <div v-for="leg in sortedLegs(group.positions)" :key="leg.symbol"
             class="flex items-center justify-between text-xs py-1 border-b border-tv-border/20 last:border-0">
          <div class="flex items-center gap-2">
            <span class="text-tv-text font-medium w-8 text-right">{{ getSignedQuantity(leg) }}</span>
            <span class="text-tv-muted">{{ getExpirationDate(leg) }}</span>
            <span class="text-tv-text">{{ getStrikePrice(leg) }}</span>
            <span :class="getOptionType(leg) === 'Call' ? 'text-tv-green' : 'text-tv-red'" class="text-[10px]">
              {{ getOptionType(leg) === 'Call' ? 'C' : 'P' }}
            </span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-tv-muted">{{ getDTE(leg) }}d</span>
            <span :class="positionCalc.calculateLegPnL(leg) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
              ${{ formatNumber(positionCalc.calculateLegPnL(leg)) }}
            </span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-3 mt-2 text-xs">
        <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying) + '&group=' + encodeURIComponent(group.group_id)"
           class="text-tv-blue hover:underline">
          <i class="fas fa-book mr-1"></i>Ledger
        </a>
        <span v-if="notesState.getPositionComment(group)" class="text-tv-amber">
          <i class="fas fa-sticky-note mr-1"></i>Has notes
        </span>
      </div>
    </div>
  </div>
</template>
