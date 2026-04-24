<script setup>
import { computed } from 'vue'
import { formatNumber, formatDate } from '@/lib/formatters'
import { accountDotColor, getAccountTooltip } from '@/lib/constants'
import { LEDGER_COLS_CLASS } from '@/lib/ledgerDesktopCols'
import BaseIcon from '@/components/BaseIcon.vue'
import RollTimeline from '@/components/RollTimeline.vue'
import RollCountBadge from '@/components/RollCountBadge.vue'
import RollChainButton from '@/components/RollChainButton.vue'

const props = defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  notesState: Object,
  tagsState: Object,
  getAccountSymbol: Function,
  updateGroupStrategy: Function,
})
defineEmits(['toggle-expanded', 'open-roll-chain'])

// Strike label prefers backend-computed current_strike_label (legitimate strategy shape);
// falls back to client-side union for groups pre-dating the backend field.
const strikeLabel = computed(() => props.group.current_strike_label || props.group.strikes || '')

// Same-exp rolls show a count badge; different-exp roll chains (linked via
// rolled_from_group_id) keep the toggle that opens RollChainModal.
const hasDifferentExpChain = computed(() => !!props.group.has_roll_chain)
const rollCount = computed(() => Number(props.group.roll_count || 0))
</script>

<template>
  <div>
    <!-- Group header row -->
    <div :class="LEDGER_COLS_CLASS"
         class="h-12 cursor-pointer hover:bg-tv-border/20 transition-colors"
         @click="$emit('toggle-expanded', group.group_id)">

      <!-- Chevron -->
      <BaseIcon name="chevron-right" class="text-tv-muted transition-transform duration-200" :class="group.expanded ? 'rotate-90' : ''" />

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
              <span v-if="strikeLabel" class="text-tv-text ml-1">{{ strikeLabel }}</span>
              <span v-if="group.contractCount" class="text-tv-text ml-1">({{ group.contractCount }})</span>
            </span>
            <!-- pencil edit hidden
            <span class="flex items-center gap-1.5 ml-1.5 flex-shrink-0">
              <BaseIcon name="pencil-alt" size="xs" class="text-tv-muted/40 group-hover/strat:text-tv-muted hover:!text-tv-blue cursor-pointer transition-colors"
                 @click.stop="group._editingStrategy = true"
                 title="Edit strategy label" />
            </span>
            -->
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
        <!-- <div class="flex flex-wrap gap-1 mt-0.5 items-center">
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
        </div> -->

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
              <BaseIcon name="plus" class="text-[8px]" />
              <span>Create "{{ tagsState.tagSearch.value.trim() }}"</span>
            </button>
          </div>
        </div>
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

      <!-- Initial Premium -->
      <div class="text-right text-base"
           :class="group.initialPremium > 0 ? 'text-tv-green' : group.initialPremium < 0 ? 'text-tv-red' : 'text-tv-muted'">
        {{ group.initialPremium ? '$' + formatNumber(group.initialPremium) : '' }}
      </div>

      <!-- Rolls column: count badge for same-exp rolls (inline details below);
           toggle for different-exp roll chains (opens RollChainModal) -->
      <div class="flex items-center justify-center gap-1">
        <RollCountBadge :count="rollCount" />
        <RollChainButton
          :has-chain="hasDifferentExpChain"
          :chain-roll-count="group.roll_chain ? group.roll_chain.roll_count : null"
          compact
          @click="$emit('open-roll-chain', group.group_id)" />
      </div>

      <!-- Notes indicator -->
      <div class="flex items-center justify-center">
        <BaseIcon v-if="notesState.getGroupNote(group)" name="sticky-note" size="sm" class="text-tv-amber" title="Has notes" />
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

      <!-- Equity Aggregate (still shown outside the option timeline) -->
      <div v-if="group.hasEquityLots && group.equityAgg"
           class="flex items-center text-sm px-4 py-1.5 font-mono border-b border-tv-border/30">
        <span class="w-10 text-right font-medium"
              :class="group.equityAgg.quantity > 0 ? 'text-tv-green' : 'text-tv-red'">
          {{ group.equityAgg.quantity }}
        </span>
        <span class="w-16 text-center bg-tv-panel mx-2 py-0.5 rounded text-tv-text">Shares</span>
        <span class="w-10 text-tv-muted ml-2">Stk</span>
        <span class="w-20 text-center text-sm px-1 py-0.5 rounded border ml-3 bg-tv-green/20 text-tv-green border-tv-green/50">OPEN</span>
        <span class="w-24 text-right text-tv-muted ml-3">${{ formatNumber(group.equityAgg.avgPrice) }}</span>
      </div>

      <!-- Option roll timeline: Closing / Roll / Opening sections in descending order -->
      <RollTimeline v-if="group.roll_timeline" :timeline="group.roll_timeline" />
    </div>
  </div>
</template>
