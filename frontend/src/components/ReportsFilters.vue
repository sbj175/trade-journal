<script setup>
import { onMounted, onUnmounted } from 'vue'
import DateFilter from '@/components/DateFilter.vue'

const props = defineProps({
  filterState: Object,
  handlers: Object,
  allStrategyNames: Array,
  activeStrategyCount: Number,
  totalStrategyCount: Number,
})

const f = props.filterState
const h = props.handlers

function onDocumentClick(e) {
  if (f.strategyDropdownOpen.value && !e.target.closest('.strategy-dropdown-wrapper')) {
    f.strategyDropdownOpen.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div class="bg-tv-panel border-b border-tv-border">
    <!-- Mobile Filters -->
    <div class="md:hidden">
      <!-- Row 1: Date -->
      <div class="px-4 py-3 border-b border-tv-border/50">
        <DateFilter storage-key="reports_dateFilter" default-preset="This Month" @update="h.onDateFilterUpdate" />
      </div>

      <!-- Row 2: Direction + Type -->
      <div class="px-4 py-3 space-y-3 border-b border-tv-border/50">
        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Direction</div>
          <div class="flex flex-wrap gap-2">
            <button v-for="dir in [
              { value: 'bullish', active: 'bg-tv-green/20 text-tv-green border-tv-green/50' },
              { value: 'bearish', active: 'bg-tv-red/20 text-tv-red border-tv-red/50' },
              { value: 'neutral', active: 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' },
            ]" :key="dir.value"
              @click="h.toggleFilter('direction', dir.value)"
              class="px-3 py-1.5 text-sm border rounded transition-colors capitalize"
              :class="f.filterDirection.value.includes(dir.value) ? dir.active : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              {{ dir.value }}
            </button>
          </div>
        </div>

        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Type</div>
          <div class="flex flex-wrap gap-2">
            <button @click="h.toggleFilter('type', 'credit')"
                    class="px-3 py-1.5 text-sm border rounded transition-colors"
                    :class="f.filterType.value.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              Credit
            </button>
            <button @click="h.toggleFilter('type', 'debit')"
                    class="px-3 py-1.5 text-sm border rounded transition-colors"
                    :class="f.filterType.value.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              Debit
            </button>
            <button @click="h.toggleShares()"
                    class="px-3 py-1.5 text-sm border rounded transition-colors"
                    :class="f.filterShares.value ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              Shares
            </button>
          </div>
        </div>
      </div>

      <!-- Row 3: Strategy -->
      <div class="px-4 py-3">
        <div class="flex flex-col gap-2">
          <div class="relative strategy-dropdown-wrapper">
            <button @click="f.strategyDropdownOpen.value = !f.strategyDropdownOpen.value"
                    class="w-full px-3 py-2 text-sm border rounded transition-colors flex items-center justify-between"
                    :class="f.filterStrategies.value.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              <span class="flex items-center gap-1.5">
                <span>Strategy</span>
                <span v-if="f.filterStrategies.value.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterStrategies.value.length }}</span>
              </span>
              <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
            </button>
            <div v-if="f.strategyDropdownOpen.value"
                 class="mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 w-full max-h-64 overflow-y-auto">
              <button v-if="f.filterStrategies.value.length"
                      @click="f.filterStrategies.value = []; h.saveFilters(); h.fetchReport()"
                      class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
                Clear all
              </button>
              <button v-for="s in allStrategyNames" :key="s"
                      @click="h.toggleStrategyPick(s)"
                      class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
                <i class="fas text-[10px]" :class="f.filterStrategies.value.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
                <span :class="f.filterStrategies.value.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
              </button>
            </div>
          </div>

          <div v-if="activeStrategyCount < totalStrategyCount" class="text-sm text-tv-muted">
            {{ activeStrategyCount }} of {{ totalStrategyCount }} strategies
          </div>
        </div>
      </div>
    </div>

    <!-- Desktop Filters -->
    <div class="hidden md:block">
      <!-- Row 1: Date -->
      <div class="px-4 py-2.5 flex items-center gap-5 border-b border-tv-border/50">
        <DateFilter storage-key="reports_dateFilter" default-preset="This Month" @update="h.onDateFilterUpdate" />
      </div>

      <!-- Row 2: All Filters -->
      <div class="px-4 py-2.5 flex items-center gap-6">
        <div class="flex items-center gap-2">
          <span class="text-tv-muted text-sm">Direction:</span>
          <button v-for="dir in [
            { value: 'bullish', active: 'bg-tv-green/20 text-tv-green border-tv-green/50' },
            { value: 'bearish', active: 'bg-tv-red/20 text-tv-red border-tv-red/50' },
            { value: 'neutral', active: 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' },
          ]" :key="dir.value"
            @click="h.toggleFilter('direction', dir.value)"
            class="px-3 py-1.5 text-sm border rounded transition-colors capitalize"
            :class="f.filterDirection.value.includes(dir.value) ? dir.active : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            {{ dir.value }}
          </button>
        </div>

        <div class="w-px h-6 bg-tv-border"></div>

        <div class="flex items-center gap-2">
          <span class="text-tv-muted text-sm">Type:</span>
          <button @click="h.toggleFilter('type', 'credit')"
                  class="px-3 py-1.5 text-sm border rounded transition-colors"
                  :class="f.filterType.value.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            Credit
          </button>
          <button @click="h.toggleFilter('type', 'debit')"
                  class="px-3 py-1.5 text-sm border rounded transition-colors"
                  :class="f.filterType.value.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            Debit
          </button>
        </div>

        <div class="w-px h-6 bg-tv-border"></div>

        <button @click="h.toggleShares()"
                class="px-3 py-1.5 text-sm border rounded transition-colors"
                :class="f.filterShares.value ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
          Shares
        </button>

        <div class="w-px h-6 bg-tv-border"></div>

        <div class="relative strategy-dropdown-wrapper">
          <button @click="f.strategyDropdownOpen.value = !f.strategyDropdownOpen.value"
                  class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                  :class="f.filterStrategies.value.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            Strategy
            <span v-if="f.filterStrategies.value.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterStrategies.value.length }}</span>
            <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
          </button>
          <div v-if="f.strategyDropdownOpen.value"
               class="fixed mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 min-w-[200px] max-h-64 overflow-y-auto">
            <button v-if="f.filterStrategies.value.length"
                    @click="f.filterStrategies.value = []; h.saveFilters(); h.fetchReport()"
                    class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
              Clear all
            </button>
            <button v-for="s in allStrategyNames" :key="s"
                    @click="h.toggleStrategyPick(s)"
                    class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
              <i class="fas text-[10px]" :class="f.filterStrategies.value.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
              <span :class="f.filterStrategies.value.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
            </button>
          </div>
        </div>

        <div v-if="activeStrategyCount < totalStrategyCount" class="flex-1 text-right text-sm text-tv-muted">
          {{ activeStrategyCount }} of {{ totalStrategyCount }} strategies
        </div>
      </div>
    </div>
  </div>
</template>
