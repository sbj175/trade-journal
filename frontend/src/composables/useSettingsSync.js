/**
 * Initial sync / import trades functionality.
 */
import { ref } from 'vue'
import { useConfirm } from '@/composables/useConfirm'

export function useSettingsSync(Auth, { showNotification, onboarding, router }) {
  const { confirm } = useConfirm()
  const initialSyncing = ref(false)
  const importResult = ref(null)

  function goToPositions() {
    router.push('/positions')
  }

  async function initialSync() {
    const title = onboarding.value ? 'Import Trading History' : 'Initial Sync'
    const msg = onboarding.value
      ? 'This will import your full trading history from Tastytrade.\n\nThis may take a minute.'
      : 'Initial Sync will CLEAR the existing database and rebuild from scratch.\n\nThis will fetch your full transaction history and may take several minutes.'
    const ok = await confirm({
      title,
      message: msg,
      confirmText: onboarding.value ? 'Import' : 'Rebuild',
      variant: onboarding.value ? 'default' : 'danger',
    })
    if (!ok) return

    initialSyncing.value = true
    try {
      const response = await Auth.authFetch('/api/sync/initial', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
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
    initialSyncing,
    importResult,
    goToPositions,
    initialSync,
  }
}
