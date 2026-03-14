/**
 * Strategy target loading, saving (with debounce), reset, and category filtering.
 */
import { ref, computed } from 'vue'

const CREDIT_NAMES = ['Bull Put Spread', 'Bear Call Spread', 'Iron Condor', 'Iron Butterfly',
  'Cash Secured Put', 'Covered Call', 'Short Put', 'Short Call',
  'Short Strangle', 'Short Straddle', 'Jade Lizard']

const DEBIT_NAMES = ['Bull Call Spread', 'Bear Put Spread', 'Long Call', 'Long Put',
  'Long Strangle', 'Long Straddle', 'Calendar Spread', 'Diagonal Spread', 'Diagonal Call Spread']

const MIXED_NAMES = ['Collar']
const EQUITY_NAMES = ['Shares']

export function useSettingsTargets(Auth, { showNotification }) {
  const targets = ref([])
  const saveStatus = ref(null)

  const creditStrategies = computed(() => targets.value.filter(t => CREDIT_NAMES.includes(t.strategy_name)))
  const debitStrategies = computed(() => targets.value.filter(t => DEBIT_NAMES.includes(t.strategy_name)))
  const mixedStrategies = computed(() => targets.value.filter(t => MIXED_NAMES.includes(t.strategy_name)))
  const equityStrategies = computed(() => targets.value.filter(t => EQUITY_NAMES.includes(t.strategy_name)))

  async function loadTargets() {
    try {
      const resp = await Auth.authFetch('/api/settings/targets')
      if (resp.ok) {
        targets.value = await resp.json()
      }
    } catch (e) {
      showNotification('Failed to load targets', 'error')
    }
  }

  let _saveTimer = null
  function debouncedSaveTargets() {
    if (_saveTimer) clearTimeout(_saveTimer)
    saveStatus.value = 'pending'
    _saveTimer = setTimeout(() => saveTargets(), 800)
  }

  async function saveTargets() {
    saveStatus.value = 'saving'
    try {
      const payload = targets.value.map(t => ({
        strategy_name: t.strategy_name,
        profit_target_pct: parseFloat(t.profit_target_pct),
        loss_target_pct: parseFloat(t.loss_target_pct),
      }))
      const resp = await Auth.authFetch('/api/settings/targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (resp.ok) {
        saveStatus.value = 'saved'
        setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = null }, 2000)
      } else {
        showNotification('Failed to save targets', 'error')
        saveStatus.value = null
      }
    } catch (e) {
      showNotification('Failed to save targets', 'error')
      saveStatus.value = null
    }
  }

  async function resetToDefaults() {
    try {
      const resp = await Auth.authFetch('/api/settings/targets/reset', { method: 'POST' })
      if (resp.ok) {
        await loadTargets()
        showNotification('Targets reset to defaults', 'success')
      } else {
        showNotification('Failed to reset targets', 'error')
      }
    } catch (e) {
      showNotification('Failed to reset targets', 'error')
    }
  }

  return {
    targets,
    saveStatus,
    creditStrategies,
    debitStrategies,
    mixedStrategies,
    equityStrategies,
    loadTargets,
    debouncedSaveTargets,
    resetToDefaults,
  }
}
