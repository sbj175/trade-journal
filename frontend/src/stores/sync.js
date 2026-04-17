import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'

export const useSyncStore = defineStore('sync', () => {
  const isSyncing = ref(false)
  const syncSummary = ref(null)
  const lastSyncTime = ref(null)

  async function performSync() {
    if (isSyncing.value) return
    isSyncing.value = true
    syncSummary.value = null
    try {
      const Auth = useAuth()
      const resp = await Auth.authFetch('/api/sync', { method: 'POST' })
      if (resp.ok) {
        const data = await resp.json()
        const n = data.new_transactions || 0
        const syms = data.symbols || []
        if (n > 0) {
          syncSummary.value = `Imported ${n} transaction${n === 1 ? '' : 's'} on ${syms.join(', ')}`
        } else {
          syncSummary.value = 'No new transactions'
        }
      }
      lastSyncTime.value = Date.now()
    } catch (err) {
      syncSummary.value = 'Sync failed'
    } finally {
      isSyncing.value = false
    }
  }

  function dismissSummary() {
    syncSummary.value = null
  }

  return { isSyncing, syncSummary, lastSyncTime, performSync, dismissSummary }
})
