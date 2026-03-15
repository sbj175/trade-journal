<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { formatNumber } from '@/lib/formatters'

const Auth = useAuth()

const props = defineProps({
  isLoading: { type: Boolean, default: false },
  liveQuotesActive: { type: Boolean, default: false },
  lastQuoteUpdate: { type: String, default: null },
  syncSummary: { type: String, default: null },
  selectedAccount: { type: String, default: '' },
  symbolFilter: { type: String, default: '' },
})

const emit = defineEmits(['sync', 'update:syncSummary', 'update:symbolFilter', 'symbolCommit'])

const accountBalances = ref({})
const privacyMode = ref('off')

// Market status
const marketStatus = ref(null)
const marketExpanded = ref(false)
let marketPollTimer = null

const overallStatus = computed(() => marketStatus.value?.overall_status || null)

const statusLabel = computed(() => {
  if (!props.liveQuotesActive) return 'Disconnected'
  const s = overallStatus.value
  if (s === 'Open') return 'Market Open'
  if (s === 'Pre-market') return 'Pre-Market'
  if (s === 'Extended') return 'Extended Hours'
  if (s === 'Closed') return 'Market Closed'
  return 'Connected'
})

const statusColor = computed(() => {
  if (!props.liveQuotesActive) return 'text-tv-red'
  const s = overallStatus.value
  if (s === 'Open') return 'text-tv-green'
  if (s === 'Pre-market' || s === 'Extended') return 'text-tv-amber'
  if (s === 'Closed') return 'text-tv-muted'
  return 'text-tv-green'
})

const dotColor = computed(() => {
  if (!props.liveQuotesActive) return 'bg-tv-red'
  const s = overallStatus.value
  if (s === 'Open') return 'bg-tv-green'
  if (s === 'Pre-market' || s === 'Extended') return 'bg-tv-amber'
  if (s === 'Closed') return 'bg-tv-muted'
  return 'bg-tv-green'
})

function formatSessionTime(isoStr) {
  if (!isoStr) return '—'
  const d = new Date(isoStr)
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

function formatSessionDate(isoStr) {
  if (!isoStr) return '—'
  const d = new Date(isoStr)
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
  return 'text-tv-muted'
}

async function loadMarketStatus() {
  try {
    const resp = await Auth.authFetch('/api/market-status')
    if (resp.ok) marketStatus.value = await resp.json()
  } catch (e) { /* silent */ }
}

function toggleMarketExpanded(event) {
  event.stopPropagation()
  marketExpanded.value = !marketExpanded.value
}

function closeMarketExpanded() {
  marketExpanded.value = false
}

const currentAccountBalance = computed(() => {
  if (!props.selectedAccount || props.selectedAccount === '') {
    const values = Object.values(accountBalances.value)
    if (values.length === 0) return null
    return values.reduce((acc, balance) => ({
      cash_balance: (acc.cash_balance || 0) + (balance.cash_balance || 0),
      derivative_buying_power: (acc.derivative_buying_power || 0) + (balance.derivative_buying_power || 0),
      equity_buying_power: (acc.equity_buying_power || 0) + (balance.equity_buying_power || 0),
      net_liquidating_value: (acc.net_liquidating_value || 0) + (balance.net_liquidating_value || 0)
    }), { cash_balance: 0, derivative_buying_power: 0, equity_buying_power: 0, net_liquidating_value: 0 })
  }
  return accountBalances.value[props.selectedAccount] || null
})

async function loadAccountBalances() {
  try {
    const response = await Auth.authFetch('/api/account-balances')
    const data = await response.json()
    const balances = data.balances || data
    const newBalances = {}
    if (Array.isArray(balances)) {
      balances.forEach(balance => { newBalances[balance.account_number] = balance })
    }
    accountBalances.value = newBalances
  } catch (err) { console.error('Failed to load account balances:', err) }
}

function onSymbolInput(event) {
  emit('update:symbolFilter', event.target.value.toUpperCase())
  emit('symbolCommit')
}

function onSymbolEnterOrBlur() {
  emit('update:symbolFilter', props.symbolFilter.trim())
  emit('symbolCommit')
}

function clearSymbolFilter() {
  emit('update:symbolFilter', '')
  emit('symbolCommit')
}

onMounted(() => {
  privacyMode.value = localStorage.getItem('privacyMode') || 'off'
  loadAccountBalances()
  loadMarketStatus()
  marketPollTimer = setInterval(loadMarketStatus, 60000)
  document.addEventListener('click', closeMarketExpanded)
})

onUnmounted(() => {
  if (marketPollTimer) clearInterval(marketPollTimer)
  document.removeEventListener('click', closeMarketExpanded)
})
</script>

<template>
  <div class="bg-tv-panel border-b border-tv-border px-4 py-3 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <button @click="$emit('sync')"
              :disabled="isLoading"
              class="bg-tv-green/20 hover:bg-tv-green/30 text-tv-green border border-tv-green/30 px-4 py-2 text-base disabled:opacity-50">
        <i class="fas fa-sync-alt" :class="{'animate-spin': isLoading}" style="margin-right: 0.5rem"></i>
        <span>Sync</span>
      </button>

      <!-- Symbol Filter -->
      <div class="relative">
        <input type="text"
               :value="symbolFilter"
               @input="onSymbolInput($event)"
               @focus="$event.target.select()"
               @keyup.enter="onSymbolEnterOrBlur()"
               @blur="onSymbolEnterOrBlur()"
               placeholder="Symbol"
               maxlength="5"
               class="bg-tv-bg border border-tv-border text-tv-text text-base px-3 py-2 w-28 uppercase placeholder:normal-case placeholder:text-tv-muted"
               :class="symbolFilter ? 'pr-8' : ''">
        <button v-show="symbolFilter"
                @click="clearSymbolFilter()"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-tv-muted hover:text-tv-text"
                title="Clear symbol filter">
          <i class="fas fa-times-circle"></i>
        </button>
      </div>

      <!-- Account Balances -->
      <template v-if="currentAccountBalance">
        <div class="flex items-center gap-6 ml-6 text-base">
          <div>
            <span class="text-tv-muted text-sm">Net Liq:</span>
            <span class="font-medium ml-1">{{ privacyMode !== 'off' ? '••••••' : '$' + formatNumber(currentAccountBalance.net_liquidating_value) }}</span>
          </div>
          <div class="flex-grow"></div>
          <div>
            <span class="text-tv-muted text-sm">Cash:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.cash_balance) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-sm">Option BP:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.derivative_buying_power) }}</span>
          </div>
          <div>
            <span class="text-tv-muted text-sm">Stock BP:</span>
            <span class="font-medium ml-1">{{ privacyMode === 'high' ? '••••••' : '$' + formatNumber(currentAccountBalance.equity_buying_power) }}</span>
          </div>
        </div>
      </template>

      <!-- Market Status -->
      <div class="relative ml-4">
        <button @click="toggleMarketExpanded($event)"
                class="flex items-center gap-1.5 text-sm cursor-pointer hover:opacity-80 transition-opacity">
          <span v-show="lastQuoteUpdate" class="text-tv-muted">{{ lastQuoteUpdate }}</span>
          <span class="inline-flex items-center gap-1.5 ml-1">
            <span class="pulse-dot" :class="dotColor"></span>
            <span :class="statusColor" class="font-medium">{{ statusLabel }}</span>
            <i class="fas fa-chevron-down text-[8px] text-tv-muted transition-transform"
               :class="{ 'rotate-180': marketExpanded }"></i>
          </span>
        </button>

        <!-- Expanded Market Details -->
        <div v-show="marketExpanded"
             class="absolute right-0 top-full mt-2 z-50 bg-tv-panel border border-tv-border rounded-lg shadow-2xl p-4 w-80"
             @click.stop>
          <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-semibold">Market Sessions</div>
          <div v-if="marketStatus?.sessions?.length" class="space-y-3">
            <div v-for="s in marketStatus.sessions" :key="s.exchange"
                 class="border-b border-tv-border/30 pb-3 last:border-0 last:pb-0">
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-sm font-medium text-tv-text">{{ exchangeLabel(s.exchange) }}</span>
                <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                      :class="s.status === 'Open' ? 'bg-tv-green/20 text-tv-green' : s.status === 'Pre-market' || s.status === 'Extended' ? 'bg-tv-amber/20 text-tv-amber' : 'bg-tv-muted/20 text-tv-muted'">
                  {{ s.status }}
                </span>
              </div>
              <div class="grid grid-cols-2 gap-1 text-xs">
                <template v-if="s.status === 'Open' || s.status === 'Pre-market' || s.status === 'Extended'">
                  <span class="text-tv-muted">Opens:</span>
                  <span class="text-tv-text">{{ formatSessionTime(s.open_at) }}</span>
                  <span class="text-tv-muted">Closes:</span>
                  <span class="text-tv-text">{{ formatSessionTime(s.close_at) }}</span>
                  <template v-if="s.close_at_ext">
                    <span class="text-tv-muted">Extended:</span>
                    <span class="text-tv-text">{{ formatSessionTime(s.close_at_ext) }}</span>
                  </template>
                </template>
                <template v-else>
                  <template v-if="s.next_session">
                    <span class="text-tv-muted">Next Open:</span>
                    <span class="text-tv-text">{{ formatSessionDate(s.next_session.session_date) }}</span>
                    <span class="text-tv-muted">Opens At:</span>
                    <span class="text-tv-text">{{ formatSessionTime(s.next_session.open_at) }}</span>
                  </template>
                </template>
              </div>
            </div>
          </div>
          <div v-else class="text-sm text-tv-muted">
            {{ marketStatus?.connected === false ? 'Not connected to Tastytrade' : 'No session data available' }}
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Sync Summary Banner -->
  <div v-show="syncSummary && !isLoading" class="mx-2 mt-2">
    <div class="px-4 py-2 rounded text-sm flex items-center justify-between bg-tv-blue/10 border border-tv-blue/30 text-tv-blue">
      <span>
        <i class="fas fa-sync-alt mr-1"></i>
        {{ syncSummary }}
      </span>
      <button @click="$emit('update:syncSummary', null)" class="text-tv-muted hover:text-tv-text text-xs ml-4">
        <i class="fas fa-times"></i>
      </button>
    </div>
  </div>
</template>
