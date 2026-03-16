import { defineStore } from 'pinia'
import { ref, computed, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'

export const useMarketStore = defineStore('market', () => {
  const marketStatus = ref(null)
  const marketExpanded = ref(false)
  let pollTimer = null

  const overallStatus = computed(() => marketStatus.value?.overall_status || null)

  // Use NYSE (Equity) session status for the toolbar indicator
  const nyseStatus = computed(() => {
    const sessions = marketStatus.value?.sessions
    if (!sessions) return null
    const nyse = sessions.find(s => s.exchange === 'Equity')
    return nyse?.status || null
  })

  const statusLabel = computed(() => {
    return 'Market Status'
  })

  const statusColor = computed(() => {
    const s = nyseStatus.value
    if (s === 'Open') return 'text-tv-green'
    if (s === 'Pre-market' || s === 'Extended') return 'text-tv-amber'
    if (s === 'Closed') return 'text-tv-red'
    return 'text-tv-muted'
  })

  const dotColor = computed(() => {
    const s = nyseStatus.value
    if (s === 'Open') return 'bg-tv-green'
    if (s === 'Pre-market' || s === 'Extended') return 'bg-tv-amber'
    if (s === 'Closed') return 'bg-tv-red'
    return 'bg-tv-muted'
  })

  async function loadMarketStatus() {
    try {
      const Auth = useAuth()
      const resp = await Auth.authFetch('/api/market-status')
      if (resp.ok) marketStatus.value = await resp.json()
    } catch (e) { /* silent */ }
  }

  function startPolling() {
    if (pollTimer) return
    loadMarketStatus()
    pollTimer = setInterval(loadMarketStatus, 60000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function toggleExpanded(event) {
    if (event) event.stopPropagation()
    marketExpanded.value = !marketExpanded.value
  }

  function closeExpanded() {
    marketExpanded.value = false
  }

  function formatSessionTime(isoStr) {
    if (!isoStr) return '—'
    const d = new Date(isoStr)
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
  }

  function formatSessionDate(isoStr) {
    if (!isoStr) return '—'
    // Date-only strings like "2026-03-16" are parsed as UTC by JS,
    // which shifts back a day in US timezones. Append T00:00:00 to force local.
    const d = new Date(isoStr.length === 10 ? isoStr + 'T00:00:00' : isoStr)
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }

  function exchangeLabel(collection) {
    if (collection === 'Equity') return 'Equities (NYSE)'
    if (collection === 'CFE') return 'Options (CFE)'
    return collection
  }

  function sessionStatusClass(status) {
    if (status === 'Open') return 'text-tv-green'
    if (status === 'Pre-market' || status === 'Extended') return 'text-tv-amber'
    if (status === 'Closed') return 'text-tv-red'
    return 'text-tv-muted'
  }

  return {
    marketStatus, marketExpanded,
    overallStatus, statusLabel, statusColor, dotColor,
    loadMarketStatus, startPolling, stopPolling,
    toggleExpanded, closeExpanded,
    formatSessionTime, formatSessionDate, exchangeLabel, sessionStatusClass,
  }
})
