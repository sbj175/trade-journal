<script setup>
import { computed } from 'vue'
import { formatDollar, dollarSizeClass } from '@/composables/usePositionsDisplay'
import { tickerLogoUrl, accountDotColor, getAccountTooltip } from '@/lib/constants'
import StreamingPrice from '@/components/StreamingPrice.vue'
import PositionsExpandedPanel from '@/components/PositionsExpandedPanel.vue'
import { DESKTOP_COLS_CLASS } from '@/lib/positionsDesktopCols'
import BaseButton from '@/components/BaseButton.vue'
import BaseIcon from '@/components/BaseIcon.vue'
import RollCountBadge from '@/components/RollCountBadge.vue'
import RollChainButton from '@/components/RollChainButton.vue'

const props = defineProps({
  group: Object,
  selectedAccount: String,
  accounts: Array,
  expandedRows: Object,
  rollAnalysisMode: String,
  notesState: Object,
  tagsState: Object,
  positionCalc: Object,
  hasEquity: Function,
  getAccountSymbol: Function,
})
defineEmits(['open-roll-chain', 'toggle-expanded', 'toggle-roll-analysis-mode'])

// Prefer backend-computed current_strike_label (walk-and-balance authoritative);
// fall back to the client-side union of open-leg strikes.
const strikeLabel = computed(() => props.group.current_strike_label || props.group.strikes || '')
const rollCount = computed(() => Number(props.group.roll_count || 0))
</script>

<template>
  <div>
    <!-- Clickable row area (main row + optional roll chain bar) -->
    <div class="hover:bg-tv-border/20 cursor-pointer transition-colors"
         @click="$emit('toggle-expanded', group.groupKey)">

      <!-- Main columns grid -->
      <div :class="DESKTOP_COLS_CLASS" class="min-h-12 py-1.5">

        <!-- Chevron -->
        <div>
          <BaseIcon name="chevron-right" class="text-tv-muted transition-transform duration-200" :class="{ 'rotate-90': expandedRows.has(group.groupKey) }" />
        </div>

        <!-- Symbol -->
        <div class="min-w-0">
          <div class="font-semibold text-base text-tv-text flex items-center gap-1.5 min-w-0">
            <img :src="tickerLogoUrl(group.underlying)" alt="" class="w-7 h-7 rounded flex-none" loading="lazy">
            <span class="truncate">{{ group.displayKey || group.underlying }}</span>
            <span v-show="selectedAccount === ''" class="text-xl leading-none flex-none"
                  :style="{ color: accountDotColor(getAccountSymbol(group.accountNumber)) }"
                  :title="getAccountTooltip(accounts, group.accountNumber)">●</span>
            <span v-show="hasEquity(group) && (group.positions || []).length > 0"
                  class="text-[10px] text-tv-muted flex-none bg-tv-border/50 px-1 rounded">+stk</span>
          </div>
        </div>

        <!-- Strategy -->
        <div class="min-w-0">
          <div class="text-sm text-tv-muted truncate">
            {{ group.strategyLabel }}<span v-if="strikeLabel" class="text-tv-text ml-1">{{ strikeLabel }}</span><span v-if="group.positionCount"> ({{ group.positionCount }})</span>
            <RollCountBadge :count="rollCount" class="ml-1.5" />
          </div>
        </div>

        <!-- DTE -->
        <div class="text-center"
             :class="group.minDTE !== null && group.minDTE <= 21 ? 'font-bold text-tv-amber' : 'text-tv-text'">
          {{ group.minDTE !== null ? group.minDTE + 'd' : '' }}
        </div>

        <!-- Open P/L -->
        <div class="text-right font-medium"
             :class="(group.openPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.openPnL)">
          <span v-show="group.openPnL < 0">-</span>${{ formatDollar(group.openPnL) }}
        </div>

        <!-- % Rtn -->
        <div class="text-right"
             :class="group.pnlPercent !== null ? (parseFloat(group.pnlPercent) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
          {{ group.pnlPercent !== null ? group.pnlPercent + '%' : '' }}
        </div>

        <!-- IVR -->
        <div class="text-right"
             :class="group.ivr >= 50 ? 'font-bold text-tv-amber' : 'text-tv-muted'">
          {{ group.ivr !== null ? group.ivr : '' }}
        </div>

        <!-- Price -->
        <div class="flex items-center gap-2 min-w-0">
          <StreamingPrice :quote="group.underlyingQuote" />
        </div>

        <!-- Net Liq -->
        <div class="text-right font-medium"
             :class="(group.netLiq >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.netLiq)">
          <span v-show="group.netLiq < 0">-</span>${{ formatDollar(group.netLiq) }}
        </div>

        <!-- Cost Basis -->
        <div class="text-right"
             :class="(group.costBasis >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.costBasis)">
          <span v-show="group.costBasis < 0">-</span>${{ formatDollar(group.costBasis) }}
        </div>

        <!-- Note indicator -->
        <div class="flex items-center justify-center">
          <BaseIcon name="sticky-note" size="sm" class="text-tv-amber" v-show="notesState.getPositionComment(group)" title="Has notes" />
        </div>

        <!--
        Ledger link (hidden):
        <div class="flex items-center justify-center">
          <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying) + '&group=' + encodeURIComponent(group.group_id)"
             @click.stop class="inline-flex items-center justify-center w-5 h-5 text-tv-muted hover:text-tv-blue transition-colors"
             title="View in Ledger"><BaseIcon name="book" class="text-[11px]" /></a>
        </div>
        -->

        <!-- Tags / Roll badges -->
        <div class="relative flex flex-nowrap items-center justify-end gap-2 min-w-0" data-tag-popover @click.stop>
          <template v-if="group.rollAnalysis && group.rollAnalysis.badges.length > 0">
            <span v-for="badge in group.rollAnalysis.badges" :key="badge.label"
                  class="text-[11px] px-2 py-0.5 rounded-sm border leading-4 flex-none"
                  :class="{
                    'bg-tv-green/20 text-tv-green border-tv-green/50': badge.color === 'green',
                    'bg-tv-red/20 text-tv-red border-tv-red/50': badge.color === 'red',
                    'bg-tv-amber/20 text-tv-amber border-tv-amber/50': badge.color === 'yellow',
                    'bg-tv-orange/20 text-tv-orange border-tv-orange/50': badge.color === 'orange'
                  }">{{ badge.label }}</span>
          </template>

          <span v-for="tag in (group.tags || [])" :key="tag.id"
                class="text-[11px] px-2 py-0.5 rounded-full border inline-flex items-center gap-1 leading-4 flex-none"
                :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
            <span>{{ tag.name }}</span>
            <button @click="tagsState.removeTagFromGroup(group, tag.id, $event)"
                    class="hover:opacity-70 leading-none">&times;</button>
          </span>

          <!-- + Tag button hidden
          <button @click="tagsState.openTagPopover(group.group_id, $event)"
                  class="text-[11px] px-2.5 py-1 rounded-full bg-tv-blue text-white hover:bg-tv-blue/80 cursor-pointer leading-4 font-medium transition-colors text-nowrap flex-none"
                  title="Add tag">+ Tag</button>
          -->

          <!-- Tag popover -->
          <div v-if="tagsState.tagPopoverGroup.value === group.group_id"
               class="absolute top-full right-0 mt-1 z-50 bg-tv-panel border border-tv-border rounded shadow-lg p-1.5 w-44"
               data-tag-popover
               @click.stop>
            <input type="text"
                   :id="'tag-input-' + group.group_id"
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
      </div>

      <!-- Roll chain bar (below main grid row, full width) -->
      <div v-if="group.roll_chain" class="flex items-center pl-10 py-1.5 text-[11px] text-tv-muted gap-4 border-t border-tv-border/40 bg-tv-bg/60">
        <span class="inline-flex items-center gap-1">
          <span class="text-tv-muted/70">Chain Realized:</span>
          <span :class="group.roll_chain.cumulative_realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
            <span v-show="group.roll_chain.cumulative_realized_pnl < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl) }}
          </span>
        </span>
        <span class="inline-flex items-center gap-1">
          <span class="text-tv-muted/70">Chain Total:</span>
          <span :class="(group.roll_chain.cumulative_realized_pnl + group.openPnL) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium">
            <span v-show="(group.roll_chain.cumulative_realized_pnl + group.openPnL) < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl + group.openPnL) }}
          </span>
        </span>
        <RollChainButton
          :has-chain="true"
          :chain-roll-count="group.roll_chain.roll_count"
          @click="$emit('open-roll-chain', group)" />
      </div>
    </div>

    <!-- Expanded Detail Panel -->
    <PositionsExpandedPanel
      v-if="expandedRows.has(group.groupKey)"
      :group="group"
      :roll-analysis-mode="rollAnalysisMode"
      :notes-state="notesState"
      :position-calc="positionCalc"
      @toggle-roll-analysis-mode="$emit('toggle-roll-analysis-mode')"
      @open-roll-chain="$emit('open-roll-chain', $event)"
    />
  </div>
</template>
