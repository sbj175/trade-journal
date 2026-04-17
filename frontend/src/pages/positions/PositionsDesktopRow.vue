<script setup>
import { formatDollar, dollarSizeClass } from './usePositionsDisplay'
import { tickerLogoUrl, accountDotColor, getAccountTooltip } from '@/lib/constants'
import StreamingPrice from '@/components/StreamingPrice.vue'
import PositionsExpandedPanel from './PositionsExpandedPanel.vue'

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
</script>

<template>
  <div>
    <!-- Group Row -->
    <div class="flex flex-wrap items-center px-4 min-h-12 py-1.5 hover:bg-tv-border/20 cursor-pointer transition-colors"
         @click="$emit('toggle-expanded', group.groupKey)">

      <!-- Chevron -->
      <div class="w-16">
        <i class="fas fa-chevron-right text-tv-muted transition-transform duration-200"
           :class="{ 'rotate-90': expandedRows.has(group.groupKey) }"></i>
      </div>

      <!-- Symbol -->
      <div class="w-28">
        <div class="font-semibold text-base text-tv-text flex items-center gap-1.5">
          <img :src="tickerLogoUrl(group.underlying)" alt="" class="w-7 h-7 rounded" loading="lazy">
          {{ group.displayKey || group.underlying }}
          <span v-show="selectedAccount === ''" class="text-xl leading-none -ml-0.5"
                :style="{ color: accountDotColor(getAccountSymbol(group.accountNumber)) }"
                :title="getAccountTooltip(accounts, group.accountNumber)">●</span>
          <span v-show="hasEquity(group) && (group.positions || []).length > 0"
                class="text-[10px] text-tv-muted ml-1 bg-tv-border/50 px-1 rounded">+stk</span>
        </div>
      </div>

      <!-- IVR -->
      <div class="w-16 text-right mr-1"
           :class="group.ivr >= 50 ? 'font-bold text-tv-amber' : 'text-tv-muted'">
        {{ group.ivr !== null ? group.ivr : '' }}
      </div>

      <!-- Price -->
      <div class="w-40 flex items-center gap-2">
        <StreamingPrice :quote="group.underlyingQuote" />
      </div>

      <!-- Ledger Link -->
      <div class="w-10 flex items-center gap-1.5">
        <a :href="'/ledger?underlying=' + encodeURIComponent(group.underlying) + '&group=' + encodeURIComponent(group.group_id)"
           @click.stop
           class="inline-flex items-center justify-center min-w-5 h-5 text-tv-muted hover:text-tv-blue transition-colors"
           title="View in Ledger">
          <i class="fas fa-book text-[11px]"></i>
        </a>
      </div>

      <!-- Strategy -->
      <div class="w-40">
        <div class="text-sm text-tv-muted truncate">
          {{ group.strategyLabel }}<span v-if="group.strikes" class="text-tv-text ml-1">{{ group.strikes }}</span><span v-if="group.positionCount"> ({{ group.positionCount }})</span>
          <span v-if="group.partially_rolled"
                class="text-tv-cyan cursor-help ml-0.5"
                title="Partially rolled — some legs have been rolled to different strikes or expirations">&#9432;</span>
        </div>
      </div>

      <!-- DTE -->
      <div class="w-10 text-center"
           :class="group.minDTE !== null && group.minDTE <= 21 ? 'font-bold text-tv-amber' : 'text-tv-text'">
        {{ group.minDTE !== null ? group.minDTE + 'd' : '' }}
      </div>

      <!-- Cost Basis -->
      <div class="w-[6.5rem] text-right"
           :class="(group.costBasis >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.costBasis)">
        <span v-show="group.costBasis < 0">-</span>${{ formatDollar(group.costBasis) }}
      </div>

      <!-- Net Liq -->
      <div class="w-[6.5rem] text-right font-medium"
           :class="(group.netLiq >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.netLiq)">
        <span v-show="group.netLiq < 0">-</span>${{ formatDollar(group.netLiq) }}
      </div>

      <!-- Open P/L -->
      <div class="w-[6.5rem] text-right font-medium"
           :class="(group.openPnL >= 0 ? 'text-tv-green' : 'text-tv-red') + ' ' + dollarSizeClass(group.openPnL)">
        <span v-show="group.openPnL < 0">-</span>${{ formatDollar(group.openPnL) }}
      </div>

      <!-- % Rtn -->
      <div class="w-20 text-right"
           :class="group.pnlPercent !== null ? (parseFloat(group.pnlPercent) >= 0 ? 'text-tv-green' : 'text-tv-red') : 'text-tv-muted'">
        {{ group.pnlPercent !== null ? group.pnlPercent + '%' : '' }}
      </div>

      <!-- Note indicator -->
      <div class="w-16 flex items-center justify-center">
        <i class="fas fa-sticky-note text-tv-amber text-sm"
           v-show="notesState.getPositionComment(group)" title="Has notes"></i>
      </div>

      <!-- Tags / Roll badges -->
      <div class="w-[250px] relative flex flex-nowrap items-center justify-end gap-2" data-tag-popover @click.stop>
        <template v-if="group.rollAnalysis && group.rollAnalysis.badges.length > 0">
          <span v-for="badge in group.rollAnalysis.badges" :key="badge.label"
                class="text-[11px] px-2 py-0.5 rounded-sm border leading-4"
                :class="{
                  'bg-tv-green/20 text-tv-green border-tv-green/50': badge.color === 'green',
                  'bg-tv-red/20 text-tv-red border-tv-red/50': badge.color === 'red',
                  'bg-tv-amber/20 text-tv-amber border-tv-amber/50': badge.color === 'yellow',
                  'bg-tv-orange/20 text-tv-orange border-tv-orange/50': badge.color === 'orange'
                }">{{ badge.label }}</span>
        </template>

        <span v-for="tag in (group.tags || [])" :key="tag.id"
              class="text-[11px] px-2 py-0.5 rounded-full border inline-flex items-center gap-1 leading-4"
              :style="`background: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color}50`">
          <span>{{ tag.name }}</span>
          <button @click="tagsState.removeTagFromGroup(group, tag.id, $event)"
                  class="hover:opacity-70 leading-none">&times;</button>
        </span>

        <button @click="tagsState.openTagPopover(group.group_id, $event)"
                class="text-[11px] px-2.5 py-1 rounded-full bg-tv-blue text-white hover:bg-tv-blue/80 cursor-pointer leading-4 font-medium transition-colors text-nowrap"
                title="Add tag">+ Tag</button>

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
              <i class="fas fa-plus text-[8px]"></i>
              <span>Create "{{ tagsState.tagSearch.value.trim() }}"</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Inline Chain P&L (rolled positions) -->
      <div v-if="group.roll_chain" class="w-full flex items-center pl-8 pt-0.5">
        <div class="text-[11px] text-tv-muted flex items-center">
          <span class="inline-flex items-center w-44">
            <span class="text-tv-muted/70">Chain Realized:</span>
            <span :class="group.roll_chain.cumulative_realized_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium ml-1">
              <span v-show="group.roll_chain.cumulative_realized_pnl < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl) }}
            </span>
          </span>
          <span class="inline-flex items-center w-40">
            <span class="text-tv-muted/70">Chain Total:</span>
            <span :class="(group.roll_chain.cumulative_realized_pnl + group.openPnL) >= 0 ? 'text-tv-green' : 'text-tv-red'" class="font-medium ml-1">
              <span v-show="(group.roll_chain.cumulative_realized_pnl + group.openPnL) < 0">-</span>${{ formatDollar(group.roll_chain.cumulative_realized_pnl + group.openPnL) }}
            </span>
          </span>
          <button @click.stop="$emit('open-roll-chain', group)"
                  class="text-[11px] px-2.5 py-1 rounded-full bg-tv-blue text-white hover:bg-tv-blue/80 cursor-pointer leading-4 font-medium transition-colors"
                  title="Rolls detected — click to see the full chain">
            <i class="fas fa-link text-[9px] mr-0.5"></i>{{ group.roll_chain.roll_count }} roll{{ group.roll_chain.roll_count > 1 ? 's' : '' }}
          </button>
        </div>
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
