/**
 * Strategy category filtering, explicit strategy picks, and localStorage persistence.
 */
import { ref, computed } from 'vue'
import { STRATEGY_CATEGORIES } from '@/lib/constants'

export function useReportsFilters({ onFilterChange }) {
  // --- State ---
  const filterDirection = ref([])   // 'bullish', 'bearish', 'neutral'
  const filterType = ref([])        // 'credit', 'debit'
  const filterShares = ref(false)
  const filterStrategies = ref([])   // explicit strategy picks (overrides direction/type)
  const strategyDropdownOpen = ref(false)

  // --- Computed ---
  const allStrategyNames = computed(() => Object.keys(STRATEGY_CATEGORIES).sort())
  const activeStrategyCount = computed(() => getActiveStrategies().length)
  const totalStrategyCount = computed(() => Object.keys(STRATEGY_CATEGORIES).length)

  // --- Methods ---
  function getActiveStrategies() {
    // If explicit strategy picks are set, use those directly
    if (filterStrategies.value.length > 0) return [...filterStrategies.value]

    const noDir = filterDirection.value.length === 0
    const noType = filterType.value.length === 0

    // No filters active — return empty to include all groups (including Custom, Shares, etc.)
    if (noDir && noType && !filterShares.value) return []

    const strategies = []
    for (const [strategy, cat] of Object.entries(STRATEGY_CATEGORIES)) {
      if (cat.isShares) {
        if (filterShares.value) strategies.push(strategy)
        continue
      }
      const dirMatch = noDir || filterDirection.value.includes(cat.direction)
      const typeMatch = noType || filterType.value.includes(cat.type)
      if (dirMatch && typeMatch) strategies.push(strategy)
    }
    return strategies
  }

  function toggleFilter(category, value) {
    filterStrategies.value = []  // clear explicit picks when using category filters
    if (category === 'direction') {
      const idx = filterDirection.value.indexOf(value)
      if (idx >= 0) filterDirection.value.splice(idx, 1)
      else filterDirection.value.push(value)
    } else if (category === 'type') {
      const idx = filterType.value.indexOf(value)
      if (idx >= 0) filterType.value.splice(idx, 1)
      else filterType.value = [value]
    }
    saveFilters()
    onFilterChange()
  }

  function toggleShares() {
    filterStrategies.value = []  // clear explicit picks when using category filters
    filterShares.value = !filterShares.value
    saveFilters()
    onFilterChange()
  }

  function toggleStrategyPick(strategy) {
    const idx = filterStrategies.value.indexOf(strategy)
    if (idx >= 0) filterStrategies.value.splice(idx, 1)
    else filterStrategies.value.push(strategy)
    // Clear direction/type/shares when using explicit picks
    if (filterStrategies.value.length > 0) {
      filterDirection.value = []
      filterType.value = []
      filterShares.value = false
    }
    saveFilters()
    onFilterChange()
  }

  function clearStrategyPicks() {
    filterStrategies.value = []
    saveFilters()
    onFilterChange()
  }

  function saveFilters() {
    localStorage.setItem('reports_category_filters', JSON.stringify({
      direction: filterDirection.value,
      type: filterType.value,
      shares: filterShares.value,
      strategies: filterStrategies.value,
    }))
  }

  function loadSavedFilters() {
    const savedFilters = localStorage.getItem('reports_category_filters')
    if (savedFilters) {
      try {
        const parsed = JSON.parse(savedFilters)
        filterDirection.value = parsed.direction || []
        filterType.value = parsed.type || []
        filterShares.value = parsed.shares || false
        filterStrategies.value = parsed.strategies || []
      } catch (e) { /* default: no filters */ }
    }
  }

  return {
    // State
    filterDirection, filterType, filterShares, filterStrategies,
    strategyDropdownOpen,
    // Computed
    allStrategyNames, activeStrategyCount, totalStrategyCount,
    // Methods
    getActiveStrategies,
    toggleFilter, toggleShares, toggleStrategyPick, clearStrategyPicks,
    saveFilters, loadSavedFilters,
  }
}
