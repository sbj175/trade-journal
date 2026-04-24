<script setup>
import { computed } from 'vue'
import { formatNumber, formatDate, pnlColorClass } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import BaseIcon from '@/components/BaseIcon.vue'
import RollTimeline from '@/components/RollTimeline.vue'
import RollCountBadge from '@/components/RollCountBadge.vue'
import RollChainButton from '@/components/RollChainButton.vue'

const props = defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  notesState: Object,
  getAccountSymbol: Function,
})
defineEmits(['toggle-expanded', 'open-roll-chain'])

const strikeLabel = computed(() => props.group.current_strike_label || props.group.strikes || '')
const rollCount = computed(() => Number(props.group.roll_count || 0))
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
        <RollCountBadge :count="rollCount" size="sm" class="shrink-0" />
        <RollChainButton
          :has-chain="!!group.has_roll_chain"
          :chain-roll-count="group.roll_chain ? group.roll_chain.roll_count : null"
          size="sm"
          class="shrink-0"
          @click="$emit('open-roll-chain', group.group_id)" />
        <BaseIcon v-if="notesState.getGroupNote(group)" name="sticky-note" class="text-tv-amber text-[11px] shrink-0" title="Has notes" />
        <BaseIcon name="chevron-right" class="text-tv-muted text-[11px] ml-auto shrink-0 transition-transform duration-150" :class="{ 'rotate-90': group.expanded }" />
      </div>

      <!-- Strategy + tags -->
      <div class="flex flex-wrap items-center gap-1.5 mb-2 text-xs min-w-0">
        <span class="text-tv-muted truncate flex-1 min-w-0 basis-full sm:basis-auto">
          {{ group.strategy_label || '—' }}
          <span v-if="strikeLabel" class="text-tv-text ml-1">{{ strikeLabel }}</span>
          <span v-if="group.contractCount" class="text-tv-text ml-1">({{ group.contractCount }})</span>
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

      <!-- Option roll timeline -->
      <RollTimeline v-if="group.roll_timeline" :timeline="group.roll_timeline" />
    </div>
  </div>
</template>
