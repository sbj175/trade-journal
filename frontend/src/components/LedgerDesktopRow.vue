<script setup>
import { formatNumber, formatDate, formatExpirationShort } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import { LEDGER_COLS_CLASS } from '@/lib/ledgerDesktopCols'

defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  notesState: Object,
  tagsState: Object,
  getAccountSymbol: Function,
  updateGroupStrategy: Function,
})
defineEmits(['toggle-expanded', 'open-roll-chain'])
</script>

<template>
  <div>
    <!-- Group header row -->
    <div :class="LEDGER_COLS_CLASS"
         class="h-12 cursor-pointer hover:bg-tv-border/20 transition-colors"
         @click="$emit('toggle-expanded', group.group_id)">

      <!-- Chevron -->
      <i class="fas fa-chevron-right text-tv-muted transition-transform duration-200"
         :class="group.expanded ? 'rotate-90' : ''"></i>

      <!-- Logo spacer -->
      <div></div>

      <!-- Symbol + account dot -->
      <div class="flex items-center gap-1 min-w-0">
        <span class="text-lg font-semibold text-tv-text truncate">{{ group.underlying }}</span>
        <span v-show="selectedAccount === ''"
              class="text-xl leading-none flex-none"
              :style="{ color: accountDotColor(getAccountSymbol(group.account_number)) }"
              :title="getAccountTooltip(accounts, group.account_number)">●</span>
      </div>

      <!-- Strategy (inline edit + tags + popover) -->
      <div class="relative min-w-0" @click.stop>
        <template v-if="!group._editingStrategy">
          <span class="flex items-center group/strat min-w-0">
            <span class="text-tv-muted text-base truncate flex-1 min-w-0">
              {{ group.strategy_label || '—' }}
              <span v-if="group.strikes" class="text-tv-text ml-1">{{ group.strikes }}</span>
              <span v-if="group.contractCount" class="text-tv-text ml-1">({{ group.contractCount }})</span>
              <span v-if="group.partially_rolled"
                    class="text-tv-cyan cursor-help ml-0.5"
                    title="Partially rolled — some legs have been rolled to different strikes or expirations">&#9432;</span>
            </span>
            <span class="flex items-center gap-1.5 ml-1.5 flex-shrink-0">
              <i class="fas fa-pencil-alt text-xs text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                 @click.stop="group._editingStrategy = true"
                 title="Edit strategy label"></i>
            </span>
          </span>
        </template>
        <template v-else>
          <input type="text"
                 :value="group.strategy_label || ''"
                 @keyup.enter="updateGroupStrategy(group, $event.target.value); group._editingStrategy = false"
                 @blur="updateGroupStrategy(group, $event.target.value); group._editingStrategy = false"
                 @keyup.escape="group._editingStrategy = false"
                 @click.stop
                 @vue:mounted="({ el }) => { el.focus(); el.select() }"
                 class="w-36 bg-tv-bg border border-tv-border text-tv-text text-base px-2 py-1 rounded"
                 placeholder="Strategy label">
        </template>

        <!-- Tag chips -->
        <div class="flex flex-wrap gap-1 mt-0.5 items-center">
          <span v-for="tag in (group.tags || [])" :key="tag.id"
                class="text-[10px] px-1.5 py-0.5 rounded-full border inline-flex items-center gap-0.5 leading-3"
                :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
            <span>{{ tag.name }}</span>
            <button @click.stop="tagsState.removeTagFromGroup(group, tag.id, $event)"
                    class="hover:opacity-70 ml-0.5 leading-none">&times;</button>
          </span>
          <button @click.stop="tagsState.openTagPopover(group.group_id, $event)"
                  class="text-[10px] w-4 h-4 rounded-full border border-tv-border/50 text-tv-muted hover:text-tv-blue hover:border-tv-blue/50 flex items-center justify-center leading-none"
                  title="Add tag">+</button>
        </div>

        <!-- Tag popover -->
        <div v-if="tagsState.tagPopoverGroup.value === group.group_id"
             class="absolute top-full left-0 mt-1 z-50 bg-tv-panel border border-tv-border rounded shadow-lg p-1.5 w-44"
             @click.stop>
          <input type="text"
                 :id="'ledger-tag-input-' + group.group_id"
                 v-model="tagsState.tagSearch.value"
                 @keydown="tagsState.handleTagInput($event, group)"
                 class="w-full bg-tv-bg border border-tv-border text-tv-text text-xs px-2 py-1 rounded outline-none focus:border-tv-blue/50"
                 placeholder="Type tag name...">
          <div class="max-h-28 overflow-y-auto mt-1">
            <button v-for="tag in tagsState.filteredTagSuggestions.value" :key="tag.id"
                    @click="tagsState.addTagToGroup(group, tag); tagsState.closeTagPopover()"
                    class="flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs text-tv-text hover:bg-tv-panel rounded">
              <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="`background: ${tag.color}`"></span>
              <span>{{ tag.name }}</span>
            </button>
            <button v-if="tagsState.tagSearch.value.trim() && !tagsState.filteredTagSuggestions.value.find(t => t.name.toLowerCase() === tagsState.tagSearch.value.trim().toLowerCase())"
                    @click="tagsState.addTagToGroup(group, tagsState.tagSearch.value.trim()); tagsState.closeTagPopover()"
                    class="flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs text-tv-blue hover:bg-tv-panel rounded">
              <i class="fas fa-plus text-[8px]"></i>
              <span>Create "{{ tagsState.tagSearch.value.trim() }}"</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Status -->
      <div>
        <span class="text-sm px-2 py-0.5 rounded"
              :class="group.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green' : 'bg-tv-muted/20 text-tv-muted'">
          {{ group.status }}
        </span>
      </div>

      <!-- Opened -->
      <div class="text-tv-muted text-base">{{ formatDate(group.opening_date) }}</div>

      <!-- Closed -->
      <div class="text-tv-muted text-base">{{ group.closing_date ? formatDate(group.closing_date) : '—' }}</div>

      <!-- Rolls toggle -->
      <div class="flex items-center justify-center">
        <label v-if="group.has_roll_chain"
               class="relative inline-flex items-center cursor-pointer"
               @click.stop="$emit('open-roll-chain', group.group_id)"
               title="Roll chain">
          <span class="w-8 h-4 rounded-full transition-colors bg-tv-border">
            <span class="absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform"></span>
          </span>
        </label>
      </div>

      <!-- Notes indicator -->
      <div class="flex items-center justify-center">
        <i v-if="notesState.getGroupNote(group)"
           class="fas fa-sticky-note text-tv-amber text-sm"
           title="Has notes"></i>
      </div>

      <!-- Initial Premium -->
      <div class="text-right text-base"
           :class="group.initialPremium > 0 ? 'text-tv-green' : group.initialPremium < 0 ? 'text-tv-red' : 'text-tv-muted'">
        {{ group.initialPremium ? '$' + formatNumber(group.initialPremium) : '' }}
      </div>

      <!-- Realized P&L -->
      <div class="text-right text-base font-medium"
           :class="group.realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'">
        {{ group.realized_pnl ? '$' + formatNumber(group.realized_pnl) : '' }}
      </div>

      <!-- % Return -->
      <div class="text-right text-base"
           :class="group.returnPercent > 0 ? 'text-tv-green' : group.returnPercent < 0 ? 'text-tv-red' : 'text-tv-muted'">
        {{ group.returnPercent != null ? formatNumber(group.returnPercent) + '%' : '' }}
      </div>
    </div>

    <!-- Expanded Detail -->
    <div v-if="group.expanded" class="bg-tv-bg border-t border-tv-border/50 px-4 py-3">
      <!-- Group Notes -->
      <div class="px-4 pb-2">
        <textarea :value="notesState.getGroupNote(group)"
                  @input="notesState.updateGroupNote(group, $event.target.value)"
                  @click.stop rows="1"
                  class="w-full bg-transparent text-tv-text text-sm border border-tv-border/30 rounded px-2 py-1 resize-none outline-none focus:border-tv-blue/50"
                  placeholder="Add notes..."></textarea>
      </div>

      <!-- Lots Table -->
      <div>
        <!-- Lots Table Header -->
        <div class="flex items-center text-sm text-tv-muted px-4 py-2 border-b border-tv-border/30 font-mono">
          <span class="w-10 text-right">Qty</span>
          <span class="w-16 text-center mx-2">Exp</span>
          <span class="w-16 text-center mx-2">Strike</span>
          <span class="w-10">Type</span>
          <span class="w-20 text-center ml-3">Status</span>
          <span class="w-24 text-right">Entry Price</span>
          <span class="w-24 text-right ml-2">Exit Price</span>
          <span class="w-48 ml-3">Exit Type</span>
          <span class="w-20 text-right ml-2">Fees</span>
        </div>

        <!-- Equity Aggregate -->
        <template v-if="group.hasEquityLots && group.equityAgg">
          <div class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono">
            <span class="w-10 text-right font-medium"
                  :class="group.equityAgg.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
              {{ group.equityAgg.quantity }}
            </span>
            <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">Shares</span>
            <span class="w-16 text-center mx-2 py-0.5 rounded text-tv-muted">&mdash;</span>
            <span class="w-10 text-tv-muted">Stk</span>
            <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3 bg-tv-green/20 text-tv-green border-tv-green/50">OPEN</span>
            <span class="w-24 text-right text-tv-muted">${{ formatNumber(group.equityAgg.avgPrice) }}</span>
            <span class="w-24 text-right ml-2"></span>
            <span class="w-48 ml-3"></span>
            <span class="w-20 text-right ml-2"></span>
          </div>
        </template>

        <!-- Separator between equity and option legs -->
        <div v-if="group.hasEquityLots && group.optionLegs.length > 0"
             class="border-t border-tv-muted/20 my-2 mx-4"></div>

        <!-- Option legs -->
        <template v-for="(leg, legIdx) in group.optionLegs" :key="leg.key">
          <div>
            <div v-if="legIdx > 0 && leg.status === 'CLOSED' && group.optionLegs[legIdx - 1].status !== 'CLOSED'"
                 class="border-t border-tv-muted/40 my-3 mx-4"></div>
            <div class="flex items-center text-sm px-4 py-1.5 hover:bg-tv-panel/50 font-mono">
              <span class="w-10 text-right font-medium"
                    :class="leg.totalQuantity > 0 ? 'text-tv-green' : leg.totalQuantity < 0 ? 'text-tv-red' : 'text-tv-muted'">
                {{ leg.totalQuantity }}
              </span>
              <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">
                {{ leg.expiration ? formatExpirationShort(leg.expiration) : (leg.instrument_type === 'EQUITY' ? 'Shares' : '—') }}
              </span>
              <span class="w-16 text-center mx-2 py-0.5 rounded"
                    :class="leg.strike ? 'bg-tv-panel text-tv-text' : 'text-tv-muted'">
                {{ leg.strike || '—' }}
              </span>
              <span class="w-10 text-tv-muted">
                {{ leg.option_type ? (leg.option_type.toUpperCase().startsWith('C') ? 'Call' : 'Put') : (leg.instrument_type === 'EQUITY' ? 'Stk' : '—') }}
              </span>
              <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3"
                    :class="leg.status === 'OPEN' ? 'bg-tv-green/20 text-tv-green border-tv-green/50'
                      : leg.expired ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                      : leg.exercised ? 'bg-tv-muted/20 text-tv-muted border-tv-muted/50'
                      : leg.assigned ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50'
                      : 'bg-tv-muted/20 text-tv-muted border-tv-red/50'">
                {{ leg.expired ? 'EXPIRED' : leg.exercised ? 'EXERCISED' : leg.assigned ? 'ASSIGNED' : leg.status }}
              </span>
              <span class="w-24 text-right text-tv-muted">${{ formatNumber(leg.avgEntryPrice) }}</span>
              <span class="w-24 text-right text-tv-muted ml-2">
                {{ (leg.expired || leg.exercised || leg.assigned) ? '—' : (leg.avgClosePrice != null ? '$' + formatNumber(leg.avgClosePrice) : '') }}
              </span>
              <span class="w-48 ml-3 text-tv-muted text-xs truncate">{{ leg.closeStatus || '' }}</span>
              <span class="w-20 text-right ml-2 text-tv-muted"
                    :class="leg.totalFees < 0 ? 'text-tv-red' : ''">
                {{ leg.totalFees ? '$' + formatNumber(Math.abs(leg.totalFees)) : '' }}
              </span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
