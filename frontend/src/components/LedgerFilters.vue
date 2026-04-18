<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import DateFilter from '@/components/DateFilter.vue'
import { DEFAULT_TAG_COLOR } from '@/lib/constants'

const props = defineProps({
  filterState: Object,
  handlers: Object,
  uniqueStrategies: Array,
  availableTags: Array,
})

const dateFilterRef = ref(null)
const strategyDropdownOpen = ref(false)
const tagDropdownOpen = ref(false)

defineExpose({
  clearDateFilter: () => dateFilterRef.value?.clear(),
})

function onDocumentClick(e) {
  if (strategyDropdownOpen.value && !e.target.closest('.strategy-dropdown-wrapper')) {
    strategyDropdownOpen.value = false
  }
  if (tagDropdownOpen.value && !e.target.closest('.tag-dropdown-wrapper')) {
    tagDropdownOpen.value = false
  }
}
onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))

// Shorthand accessors — avoids .value noise in template
const f = props.filterState
const h = props.handlers
</script>

<template>
  <div class="bg-tv-panel border-b border-tv-border">
    <!-- Mobile Filters -->
    <div class="md:hidden">
      <!-- Row 1: Symbol + Date -->
      <div class="px-4 py-3 space-y-3 border-b border-tv-border/50">
        <div class="relative w-full">
          <input type="text"
                 :value="f.filterUnderlying.value"
                 @input="f.filterUnderlying.value = $event.target.value.toUpperCase(); h.onSymbolFilterApply()"
                 @focus="$event.target.select()"
                 @keyup.enter="h.onSymbolFilterApply()"
                 @blur="h.onSymbolFilterApply()"
                 placeholder="Symbol"
                 class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted w-full"
                 :class="f.filterUnderlying.value ? 'pr-8' : ''">
          <button v-show="f.filterUnderlying.value"
                  @click="h.clearSymbolFilter()"
                  class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
            <i class="fas fa-times-circle"></i>
          </button>
        </div>
        <div class="w-full">
          <DateFilter ref="dateFilterRef" storage-key="ledger_dateFilter" default-preset="Last 30 Days" @update="h.onDateFilterUpdate" />
        </div>
      </div>

      <!-- Row 2: Status + Rolls + Direction + Type -->
      <div class="px-4 py-3 space-y-3 border-b border-tv-border/50">
        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Status</div>
          <div class="flex flex-wrap gap-2">
            <button @click="f.showOpen.value = !f.showOpen.value; h.applyFilters(); h.saveState()"
                    :class="f.showOpen.value ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Open
            </button>
            <button @click="f.showClosed.value = !f.showClosed.value; h.applyFilters(); h.saveState()"
                    :class="f.showClosed.value ? 'bg-tv-muted/20 text-tv-text border-tv-muted/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Closed
            </button>
            <button @click="f.filterRollsOnly.value = !f.filterRollsOnly.value; h.applyFilters()"
                    :class="f.filterRollsOnly.value ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5">
              <i class="fas fa-link text-xs"></i>
              Rolls
            </button>
          </div>
        </div>

        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Direction</div>
          <div class="flex flex-wrap gap-2">
            <button @click="h.toggleFilter('direction', 'bullish')"
                    :class="f.filterDirection.value.includes('bullish') ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Bullish
            </button>
            <button @click="h.toggleFilter('direction', 'bearish')"
                    :class="f.filterDirection.value.includes('bearish') ? 'bg-tv-red/20 text-tv-red border-tv-red/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Bearish
            </button>
            <button @click="h.toggleFilter('direction', 'neutral')"
                    :class="f.filterDirection.value.includes('neutral') ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Neutral
            </button>
          </div>
        </div>

        <div>
          <div class="text-tv-muted text-xs uppercase tracking-wider mb-2">Type</div>
          <div class="flex flex-wrap gap-2">
            <button @click="h.toggleFilter('type', 'credit')"
                    :class="f.filterType.value.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Credit
            </button>
            <button @click="h.toggleFilter('type', 'debit')"
                    :class="f.filterType.value.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                    class="px-3 py-1.5 text-sm border rounded transition-colors">
              Debit
            </button>
          </div>
        </div>
      </div>

      <!-- Row 3: Strategy + Tags -->
      <div class="px-4 py-3">
        <div class="flex flex-col gap-2">
          <div class="relative strategy-dropdown-wrapper">
            <button @click="strategyDropdownOpen = !strategyDropdownOpen; tagDropdownOpen = false"
                    class="w-full px-3 py-2 text-sm border rounded transition-colors flex items-center justify-between"
                    :class="f.filterStrategy.value.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              <span class="flex items-center gap-1.5">
                <span>Strategy</span>
                <span v-if="f.filterStrategy.value.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterStrategy.value.length }}</span>
              </span>
              <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
            </button>
            <div v-if="strategyDropdownOpen"
                 class="mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 w-full max-h-64 overflow-y-auto">
              <button v-if="f.filterStrategy.value.length"
                      @click="f.filterStrategy.value = []; h.saveState(); h.applyFilters()"
                      class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
                Clear all
              </button>
              <button v-for="s in uniqueStrategies" :key="s"
                      @click="h.toggleStrategyFilter(s)"
                      class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
                <i class="fas text-[10px]" :class="f.filterStrategy.value.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
                <span :class="f.filterStrategy.value.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
              </button>
              <div v-if="uniqueStrategies.length === 0" class="px-3 py-2 text-sm text-tv-muted">No strategies</div>
            </div>
          </div>

          <div v-if="availableTags.length" class="relative tag-dropdown-wrapper">
            <button @click="tagDropdownOpen = !tagDropdownOpen; strategyDropdownOpen = false"
                    class="w-full px-3 py-2 text-sm border rounded transition-colors flex items-center justify-between"
                    :class="f.filterTagIds.value.length ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
              <span class="flex items-center gap-1.5">
                <span>Tags</span>
                <span v-if="f.filterTagIds.value.length" class="bg-tv-purple text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterTagIds.value.length }}</span>
              </span>
              <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
            </button>
            <div v-if="tagDropdownOpen"
                 class="mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 w-full max-h-64 overflow-y-auto">
              <button v-if="f.filterTagIds.value.length"
                      @click="f.filterTagIds.value = []; h.saveState(); h.applyFilters()"
                      class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
                Clear all
              </button>
              <button v-for="tag in availableTags" :key="tag.id"
                      @click="h.toggleTagFilter(tag.id)"
                      class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
                <i class="fas text-[10px]" :class="f.filterTagIds.value.includes(tag.id) ? 'fa-check-square text-tv-purple' : 'fa-square text-tv-muted'"></i>
                <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: tag.color || DEFAULT_TAG_COLOR }"></span>
                <span :class="f.filterTagIds.value.includes(tag.id) ? 'text-tv-text' : 'text-tv-muted'">{{ tag.name }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Desktop Filters -->
    <div class="hidden md:block">
      <!-- Row 1: Symbol + Date -->
      <div class="px-4 py-2.5 flex items-center gap-5 border-b border-tv-border/50">
        <div class="relative">
          <input type="text"
                 :value="f.filterUnderlying.value"
                 @input="f.filterUnderlying.value = $event.target.value.toUpperCase(); h.onSymbolFilterApply()"
                 @focus="$event.target.select()"
                 @keyup.enter="h.onSymbolFilterApply()"
                 @blur="h.onSymbolFilterApply()"
                 placeholder="Symbol"
                 class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 uppercase placeholder:normal-case placeholder:text-tv-muted md:max-w-[300px]"
                 :class="f.filterUnderlying.value ? 'pr-8' : ''">
          <button v-show="f.filterUnderlying.value"
                  @click="h.clearSymbolFilter()"
                  class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text">
            <i class="fas fa-times-circle"></i>
          </button>
        </div>
        <DateFilter ref="dateFilterRef" storage-key="ledger_dateFilter" default-preset="Last 30 Days" @update="h.onDateFilterUpdate" />
      </div>

      <!-- Row 2: Direction, Type, Status, Rolls, Strategy, Tags -->
      <div class="px-4 py-2.5 flex items-center gap-6">
        <div class="flex items-center gap-2">
          <span class="text-tv-muted text-sm">Direction:</span>
          <button @click="h.toggleFilter('direction', 'bullish')"
                  :class="f.filterDirection.value.includes('bullish') ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Bullish
          </button>
          <button @click="h.toggleFilter('direction', 'bearish')"
                  :class="f.filterDirection.value.includes('bearish') ? 'bg-tv-red/20 text-tv-red border-tv-red/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Bearish
          </button>
          <button @click="h.toggleFilter('direction', 'neutral')"
                  :class="f.filterDirection.value.includes('neutral') ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Neutral
          </button>
        </div>

        <div class="w-px h-6 bg-tv-border"></div>

        <div class="flex items-center gap-2">
          <span class="text-tv-muted text-sm">Type:</span>
          <button @click="h.toggleFilter('type', 'credit')"
                  :class="f.filterType.value.includes('credit') ? 'bg-tv-cyan/20 text-tv-cyan border-tv-cyan/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Credit
          </button>
          <button @click="h.toggleFilter('type', 'debit')"
                  :class="f.filterType.value.includes('debit') ? 'bg-tv-amber/20 text-tv-amber border-tv-amber/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Debit
          </button>
        </div>

        <div class="w-px h-6 bg-tv-border"></div>

        <div class="flex items-center gap-2">
          <span class="text-tv-muted text-sm">Status:</span>
          <button @click="f.showOpen.value = !f.showOpen.value; h.applyFilters(); h.saveState()"
                  :class="f.showOpen.value ? 'bg-tv-green/20 text-tv-green border-tv-green/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Open
          </button>
          <button @click="f.showClosed.value = !f.showClosed.value; h.applyFilters(); h.saveState()"
                  :class="f.showClosed.value ? 'bg-tv-muted/20 text-tv-text border-tv-muted/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                  class="px-3 py-1.5 text-sm border rounded transition-colors">
            Closed
          </button>
        </div>

        <button @click="f.filterRollsOnly.value = !f.filterRollsOnly.value; h.applyFilters()"
                :class="f.filterRollsOnly.value ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'"
                class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5">
          <i class="fas fa-link text-xs"></i>
          Rolls
        </button>

        <div class="w-px h-6 bg-tv-border"></div>

        <div class="relative strategy-dropdown-wrapper">
          <button @click="strategyDropdownOpen = !strategyDropdownOpen; tagDropdownOpen = false"
                  class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                  :class="f.filterStrategy.value.length ? 'bg-tv-blue/20 text-tv-blue border-tv-blue/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            Strategy
            <span v-if="f.filterStrategy.value.length" class="bg-tv-blue text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterStrategy.value.length }}</span>
            <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
          </button>
          <div v-if="strategyDropdownOpen"
               class="fixed mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 min-w-[200px] max-h-64 overflow-y-auto">
            <button v-if="f.filterStrategy.value.length"
                    @click="f.filterStrategy.value = []; h.saveState(); h.applyFilters()"
                    class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
              Clear all
            </button>
            <button v-for="s in uniqueStrategies" :key="s"
                    @click="h.toggleStrategyFilter(s)"
                    class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
              <i class="fas text-[10px]" :class="f.filterStrategy.value.includes(s) ? 'fa-check-square text-tv-blue' : 'fa-square text-tv-muted'"></i>
              <span :class="f.filterStrategy.value.includes(s) ? 'text-tv-text' : 'text-tv-muted'">{{ s }}</span>
            </button>
            <div v-if="uniqueStrategies.length === 0" class="px-3 py-2 text-sm text-tv-muted">No strategies</div>
          </div>
        </div>

        <div v-if="availableTags.length" class="relative tag-dropdown-wrapper">
          <button @click="tagDropdownOpen = !tagDropdownOpen; strategyDropdownOpen = false"
                  class="px-3 py-1.5 text-sm border rounded transition-colors flex items-center gap-1.5"
                  :class="f.filterTagIds.value.length ? 'bg-tv-purple/20 text-tv-purple border-tv-purple/50' : 'bg-tv-bg text-tv-muted border-tv-border hover:text-tv-text'">
            Tags
            <span v-if="f.filterTagIds.value.length" class="bg-tv-purple text-white text-xs rounded-full w-4 h-4 flex items-center justify-center leading-none">{{ f.filterTagIds.value.length }}</span>
            <i class="fas fa-chevron-down text-[10px] ml-0.5"></i>
          </button>
          <div v-if="tagDropdownOpen"
               class="fixed mt-1 bg-tv-panel border border-tv-border rounded shadow-lg z-[9999] py-1 min-w-[180px] max-h-64 overflow-y-auto">
            <button v-if="f.filterTagIds.value.length"
                    @click="f.filterTagIds.value = []; h.saveState(); h.applyFilters()"
                    class="w-full text-left px-3 py-1.5 text-sm text-tv-muted hover:bg-tv-bg border-b border-tv-border/50 mb-1">
              Clear all
            </button>
            <button v-for="tag in availableTags" :key="tag.id"
                    @click="h.toggleTagFilter(tag.id)"
                    class="w-full text-left px-3 py-1.5 text-sm hover:bg-tv-bg flex items-center gap-2">
              <i class="fas text-[10px]" :class="f.filterTagIds.value.includes(tag.id) ? 'fa-check-square text-tv-purple' : 'fa-square text-tv-muted'"></i>
              <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: tag.color || DEFAULT_TAG_COLOR }"></span>
              <span :class="f.filterTagIds.value.includes(tag.id) ? 'text-tv-text' : 'text-tv-muted'">{{ tag.name }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
