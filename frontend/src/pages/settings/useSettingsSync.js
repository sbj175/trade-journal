/**
 * Initial sync / import trades functionality.
 */
import { ref, computed } from 'vue'

export function useSettingsSync(Auth, { showNotification, onboarding, router }) {
  const syncStartDate = ref(new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10))
  const syncMinDate = new Date(Date.now() - 730 * 86400000).toISOString().slice(0, 10)
  const syncMaxDate = new Date().toISOString().slice(0, 10)
  const initialSyncing = ref(false)
  const importResult = ref(null)

  const syncDaysBack = computed(() => {
    const start = new Date(syncStartDate.value)
    const now = new Date()
    return Math.max(1, Math.round((now - start) / 86400000))
  })

  function goToPositions() {
    router.push('/positions')
  }

  async function initialSync() {
    const days = syncDaysBack.value
    const msg = onboarding.value
      ? `This will import ${days} days of trading history from Tastytrade.\n\nThis may take a minute. Continue?`
      : `Initial Sync will CLEAR the existing database and rebuild from scratch.\n\nThis will fetch ${days} days of transactions and may take several minutes.\n\nAre you sure you want to continue?`
    if (!confirm(msg)) return

    initialSyncing.value = true
    try {
      const response = await Auth.authFetch('/api/sync/initial', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_date: syncStartDate.value }),
      })
      if (!response.ok) throw new Error(`Initial sync failed: ${response.statusText}`)
      const result = await response.json()

      if (onboarding.value) {
        importResult.value = result
        return
      }
      showNotification(
        `Initial sync completed! ${result.transactions_processed || 0} transactions, ` +
        `${result.orders_assembled || 0} orders in ${result.groups_processed || 0} groups`,
        'success',
      )
    } catch (error) {
      showNotification('Initial sync failed: ' + error.message, 'error')
    } finally {
      initialSyncing.value = false
    }
  }

  return {
    syncStartDate,
    syncMinDate,
    syncMaxDate,
    initialSyncing,
    importResult,
    syncDaysBack,
    goToPositions,
    initialSync,
  }
}
