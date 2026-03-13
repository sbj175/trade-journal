<script setup>
import { ref, computed, onMounted } from 'vue'
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
})
</script>

<template>
  <div class="bg-tv-panel border-b border-tv-border px-4 py-3 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <button @click="$emit('sync')"
              :disabled="isLoading"
              class="bg-tv-green/20 hover:bg-tv-green/30 text-tv-green border border-tv-green/30 px-4 py-2 text-base disabled:opacity-50">
        <i class="fas fa-sync-alt mr-2" :class="{'animate-spin': isLoading}"></i>
        <span>{{ isLoading ? 'Syncing...' : 'Sync' }}</span>
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

      <span class="text-sm text-tv-muted ml-4" v-show="lastQuoteUpdate">
        Quotes: {{ lastQuoteUpdate }}
        <span v-show="liveQuotesActive" class="inline-flex items-center gap-1.5 ml-1">
          <span class="pulse-dot bg-tv-green"></span>
          <span class="text-tv-green">LIVE</span>
        </span>
      </span>
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
