<script setup>
import { formatNumber, formatDate, formatExpirationShort, pnlColorClass } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import BaseIcon from '@/components/BaseIcon.vue'

defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  notesState: Object,
  getAccountSymbol: Function,
})
defineEmits(['toggle-expanded', 'open-roll-chain'])
</script>

<template>
  <div :id="'m-group-' + group.group_id"
       class="bg-tv-row border border-tv-border rounded-lg overflow-hidden min-w-0 max-w-full">
    <!-- Summary header (tap to expand) -->
    <div @click="$emit('toggle-expanded', group.group_id)"
         class="px-3 py-3 cursor-pointer active:bg-tv-border/20 transition-colors min-w-0">
      <!-- Top row: symbol, status, indicators, chevron -->
      <div class="flex items-center gap-2 mb-1.5 min-w-0">
        <span class="text-lg font-semibold text-tv-text truncate min-w-0">{{ group.underlying }}</span>
        <span v-show="selectedAccount === ''"
              class="text-xl leading-none -ml-1"
              :style="{ color: accountDotColor(getAccountSymbol(group.account_number)) }"
              :title="getAccountTooltip(accounts, group.account_number)">●</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0"
              :class="group.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-muted/20 text-tv-muted'">
          {{ group.status }}
        </span>
        <BaseIcon v-if="group.has_roll_chain" name="link" class="text-tv-blue text-[11px] cursor-pointer shrink-0"
           @click.stop="$emit('open-roll-chain', group.group_id)" title="Roll chain" />
        <BaseIcon v-if="notesState.getGroupNote(group)" name="sticky-note" class="text-tv-amber text-[11px] shrink-0" title="Has notes" />
        <BaseIcon name="chevron-right" class="text-tv-muted text-[11px] ml-auto shrink-0 transition-transform duration-150" :class="{ 'rotate-90': group.expanded }" />
      </div>

      <!-- Strategy + tags -->
      <div class="flex flex-wrap items-center gap-1.5 mb-2 text-xs min-w-0">
        <span class="text-tv-muted truncate flex-1 min-w-0 basis-full sm:basis-auto">
          {{ group.strategy_label || '—' }}
          <span v-if="group.strikes" class="text-tv-text ml-1">{{ group.strikes }}</span>
          <span v-if="group.contractCount" class="text-tv-text ml-1">({{ group.contractCount }})</span>
          <span v-if="group.partially_rolled" class="text-tv-cyan ml-0.5" title="Partially rolled">&#9432;</span>
        </span>
        <span v-for="tag in (group.tags || [])" :key="tag.id"
              class="text-[9px] px-1 py-0.5 rounded-full border shrink-0 leading-none"
              :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
          {{ tag.name }}
        </span>
      </div>

      <!-- Dates + P&L grid -->
      <div class="grid grid-cols-2 gap-x-2 gap-y-1.5 text-[11px] pt-2 border-t border-tv-border/30">
        <div>
          <div class="text-tv-muted uppercase tracking-wide">Opened</div>
          <div class="text-tv-text text-sm">{{ formatDate(group.opening_date) }}</div>
        </div>
        <div class="text-right">
          <div class="text-tv-muted uppercase tracking-wide">Closed</div>
          <div class="text-sm" :class="group.closing_date ? 'text-tv-text' : 'text-tv-muted'">
            {{ group.closing_date ? formatDate(group.closing_date) : '—' }}
          </div>
        </div>
        <div>
          <div class="text-tv-muted uppercase tracking-wide">Initial Prem</div>
          <div class="text-sm"
               :class="group.initialPremium > 0 ? 'text-tv-green' : group.initialPremium < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ group.initialPremium ? '$' + formatNumber(group.initialPremium) : '—' }}
          </div>
        </div>
        <div class="text-right">
          <div class="text-tv-muted uppercase tracking-wide">Realized P&amp;L</div>
          <div class="text-sm font-medium leading-tight" :class="pnlColorClass(group.realized_pnl)">
            {{ group.realized_pnl ? '$' + formatNumber(group.realized_pnl) : '—' }}
          </div>
          <div class="text-[11px] leading-tight"
               :class="group.returnPercent > 0 ? 'text-tv-green' : group.returnPercent < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ group.returnPercent != null ? formatNumber(group.returnPercent) + '%' : '' }}
          </div>
        </div>
      </div>
    </div>

    <!-- Expanded detail -->
    <div v-if="group.expanded" class="bg-tv-bg border-t border-tv-border/30 px-3 py-2 space-y-2">
      <!-- Notes -->
      <textarea :value="notesState.getGroupNote(group)"
                @input="notesState.updateGroupNote(group, $event.target.value)"
                @click.stop rows="2"
                class="w-full bg-transparent text-tv-text text-xs border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                placeholder="Add notes..."></textarea>

      <!-- Equity aggregate -->
      <div v-if="group.hasEquityLots && group.equityAgg"
           class="flex items-center justify-between text-xs py-1.5 border-t border-tv-border/30">
        <div class="flex items-center gap-2">
          <span class="font-medium" :class="group.equityAgg.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
            {{ group.equityAgg.quantity }}
          </span>
          <span class="text-tv-muted">shares</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-[9px] px-1.5 py-0.5 rounded bg-tv-green/20 text-tv-green border border-tv-green/50">OPEN</span>
          <span class="text-tv-muted">@${{ formatNumber(group.equityAgg.avgPrice) }}</span>
        </div>
      </div>

      <!-- Option legs -->
      <div v-for="leg in group.optionLegs" :key="'m-leg-' + leg.key"
           class="flex items-center justify-between text-xs py-1.5 border-t border-tv-border/30">
        <div class="flex items-center gap-1.5 min-w-0">
          <span class="font-medium w-8 text-right shrink-0"
                :class="leg.totalQuantity > 0 ? 'text-tv-green' : leg.totalQuantity < 0 ? 'text-tv-red' : 'text-tv-muted'">
            {{ leg.totalQuantity }}
          </span>
          <span v-if="leg.expiration" class="text-tv-text">{{ formatExpirationShort(leg.expiration) }}</span>
          <span v-if="leg.strike" class="text-tv-text">{{ leg.strike }}</span>
          <span v-if="leg.option_type" class="text-tv-muted">{{ leg.option_type.toUpperCase().startsWith('C') ? 'C' : 'P' }}</span>
          <span v-if="!leg.expiration && leg.instrument_type === 'EQUITY'" class="text-tv-muted">Shares</span>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <span class="text-[9px] px-1 py-0.5 rounded border"
                :class="leg.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50'
                  : leg.expired ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                  : leg.exercised ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                  : leg.assigned ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50'
                  : 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'">
            {{ leg.expired ? 'EXP' : leg.exercised ? 'EX' : leg.assigned ? 'ASN' : leg.status }}
          </span>
          <span class="text-tv-muted">${{ formatNumber(leg.avgEntryPrice) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
