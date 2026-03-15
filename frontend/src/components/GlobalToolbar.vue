<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { formatNumber } from '@/lib/formatters'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useMarketStore } from '@/stores/market'
import { useBalancesStore } from '@/stores/balances'
const route = useRoute()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()
const marketStore = useMarketStore()
const balancesStore = useBalancesStore()

// Collapsible sections — persist in localStorage
const showBalances = ref(localStorage.getItem('toolbar_showBalances') !== 'false')
const showFilters = ref(localStorage.getItem('toolbar_showFilters') !== 'false')

function toggleBalances() {
  showBalances.value = !showBalances.value
  localStorage.setItem('toolbar_showBalances', showBalances.value)
}

function toggleFilters() {
  showFilters.value = !showFilters.value
  localStorage.setItem('toolbar_showFilters', showFilters.value)
}

// Hide toolbar extras on settings/privacy/components
const showToolbarExtras = computed(() => {
  const name = route.name
  return !['settings', 'privacy', 'components'].includes(name)
})

// Account change handler — pages watch the store reactively
function onAccountChange() {
  // Store auto-persists via watch; pages react to selectedAccount changes
}

// Close market popover on outside click
onMounted(() => {
  document.addEventListener('click', marketStore.closeExpanded)
  marketStore.startPolling()
  balancesStore.loadAccountBalances()
  accountsStore.loadAccounts()
})

onUnmounted(() => {
  document.removeEventListener('click', marketStore.closeExpanded)
  marketStore.stopPolling()
})
</script>

<template>
  <!-- Section 1: Always visible — Sync, Market, Account, Quotes -->
  <div class="bg-tv-panel border-b border-tv-border px-4 py-2.5 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <!-- Sync Button -->
      <template v-if="showToolbarExtras">
        <button @click="syncStore.performSync()"
                :disabled="syncStore.isSyncing"
                class="bg-tv-green/20 hover:bg-tv-green/30 text-tv-green border border-tv-green/30 px-4 py-1.5 text-sm disabled:opacity-50 transition-colors">
          <i class="fas fa-sync-alt" :class="{'animate-spin': syncStore.isSyncing}" style="margin-right: 0.5rem"></i>
          <span>Sync</span>
        </button>
      </template>

      <!-- Market Status -->
      <template v-if="showToolbarExtras">
        <div class="relative">
          <button @click="marketStore.toggleExpanded($event)"
                  class="flex items-center gap-1.5 text-sm cursor-pointer hover:opacity-80 transition-opacity">
            <span class="inline-flex items-center gap-1.5">
              <span class="pulse-dot" :class="marketStore.dotColor"></span>
              <span :class="marketStore.statusColor" class="font-medium">{{ marketStore.statusLabel }}</span>
              <i class="fas fa-chevron-down text-[8px] text-tv-muted transition-transform"
                 :class="{ 'rotate-180': marketStore.marketExpanded }"></i>
            </span>
          </button>

          <!-- Expanded Market Details -->
          <div v-show="marketStore.marketExpanded"
               class="absolute left-0 top-full mt-2 z-50 bg-tv-panel border border-tv-border rounded-lg shadow-2xl p-4 w-80"
               @click.stop>
            <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-semibold">Market Sessions</div>
            <div v-if="marketStore.marketStatus?.sessions?.length" class="space-y-3">
              <div v-for="s in marketStore.marketStatus.sessions" :key="s.exchange"
                   class="border-b border-tv-border/30 pb-3 last:border-0 last:pb-0">
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-sm font-medium text-tv-text">{{ marketStore.exchangeLabel(s.exchange) }}</span>
                  <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                        :class="s.status === 'Open' ? 'bg-tv-green/20 text-tv-green' : s.status === 'Pre-market' || s.status === 'Extended' ? 'bg-tv-amber/20 text-tv-amber' : 'bg-tv-muted/20 text-tv-muted'">
                    {{ s.status }}
                  </span>
                </div>
                <div class="grid grid-cols-2 gap-1 text-xs">
                  <template v-if="s.status === 'Open' || s.status === 'Pre-market' || s.status === 'Extended'">
                    <span class="text-tv-muted">Opens:</span>
                    <span class="text-tv-text">{{ marketStore.formatSessionTime(s.open_at) }}</span>
                    <span class="text-tv-muted">Closes:</span>
                    <span class="text-tv-text">{{ marketStore.formatSessionTime(s.close_at) }}</span>
                    <template v-if="s.close_at_ext">
                      <span class="text-tv-muted">Extended:</span>
                      <span class="text-tv-text">{{ marketStore.formatSessionTime(s.close_at_ext) }}</span>
                    </template>
                  </template>
                  <template v-else>
                    <template v-if="s.next_session">
                      <span class="text-tv-muted">Next Open:</span>
                      <span class="text-tv-text">{{ marketStore.formatSessionDate(s.next_session.session_date) }}</span>
                      <span class="text-tv-muted">Opens At:</span>
                      <span class="text-tv-text">{{ marketStore.formatSessionTime(s.next_session.open_at) }}</span>
                    </template>
                  </template>
                </div>
              </div>
            </div>
            <div v-else class="text-sm text-tv-muted">
              {{ marketStore.marketStatus?.connected === false ? 'Not connected to Tastytrade' : 'No session data available' }}
            </div>
          </div>
        </div>
      </template>
    </div>

    <div class="flex items-center gap-4">
      <!-- Account Selector -->
      <template v-if="showToolbarExtras">
        <select v-model="accountsStore.selectedAccount" @change="onAccountChange()"
                class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded">
          <option value="">All Accounts</option>
          <option v-for="account in accountsStore.accounts" :key="account.account_number"
                  :value="account.account_number">
            ({{ accountsStore.getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
          </option>
        </select>
      </template>

      <!-- Section toggles -->
      <template v-if="showToolbarExtras">
        <div class="flex items-center gap-2 border-l border-tv-border pl-4">
          <button @click="toggleBalances()"
                  class="text-xs px-2 py-1 rounded transition-colors"
                  :class="showBalances ? 'text-tv-text bg-tv-border/30' : 'text-tv-muted hover:text-tv-text'"
                  title="Toggle account overview">
            <i class="fas fa-dollar-sign text-[10px] mr-1"></i>Overview
          </button>
          <button @click="toggleFilters()"
                  class="text-xs px-2 py-1 rounded transition-colors"
                  :class="showFilters ? 'text-tv-text bg-tv-border/30' : 'text-tv-muted hover:text-tv-text'"
                  title="Toggle filters">
            <i class="fas fa-filter text-[10px] mr-1"></i>Filters
          </button>
        </div>
      </template>
    </div>
  </div>

  <!-- Sync Summary Banner -->
  <div v-if="syncStore.syncSummary && !syncStore.isSyncing" class="mx-2 mt-2">
    <div class="px-4 py-2 rounded text-sm flex items-center justify-between bg-tv-blue/10 border border-tv-blue/30 text-tv-blue">
      <span>
        <i class="fas fa-sync-alt mr-1"></i>
        {{ syncStore.syncSummary }}
      </span>
      <button @click="syncStore.dismissSummary()" class="text-tv-muted hover:text-tv-text text-xs ml-4">
        <i class="fas fa-times"></i>
      </button>
    </div>
  </div>

  <!-- Section 2: Account Balances (collapsible, animated) -->
  <div v-if="showToolbarExtras && balancesStore.currentAccountBalance"
       class="grid transition-[grid-template-rows] duration-200 ease-in-out"
       :class="showBalances ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
    <div class="overflow-hidden">
      <div class="bg-tv-panel border-b border-tv-border px-4 py-2 flex items-center gap-6 text-base">
        <div>
          <span class="text-tv-muted text-sm">Net Liq:</span>
          <span class="font-medium ml-1">{{ balancesStore.privacyMode !== 'off' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.net_liquidating_value) }}</span>
        </div>
        <div>
          <span class="text-tv-muted text-sm">Cash:</span>
          <span class="font-medium ml-1">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.cash_balance) }}</span>
        </div>
        <div>
          <span class="text-tv-muted text-sm">Option BP:</span>
          <span class="font-medium ml-1">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.derivative_buying_power) }}</span>
        </div>
        <div>
          <span class="text-tv-muted text-sm">Stock BP:</span>
          <span class="font-medium ml-1">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.equity_buying_power) }}</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Section 3: Page-specific filters (collapsible, animated, via Teleport target) -->
  <div class="grid transition-[grid-template-rows] duration-200 ease-in-out"
       :class="showFilters ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
    <div class="overflow-hidden">
      <div id="page-filters"></div>
    </div>
  </div>
</template>
