<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { formatNumber } from '@/lib/formatters'
import { accountDotColor } from '@/lib/constants'
import { useAccountsStore } from '@/stores/accounts'
import { useSyncStore } from '@/stores/sync'
import { useMarketStore } from '@/stores/market'
import { useBalancesStore } from '@/stores/balances'
import BaseButton from '@/components/BaseButton.vue'
import BaseIcon from '@/components/BaseIcon.vue'
const route = useRoute()
const accountsStore = useAccountsStore()
const syncStore = useSyncStore()
const marketStore = useMarketStore()
const balancesStore = useBalancesStore()

function getDefaultMobileToolbarOpen() {
  if (typeof window === 'undefined') return false
  return window.innerWidth >= 768
}

function getDefaultCollapsedState(key) {
  const saved = localStorage.getItem(key)
  if (saved !== null) return saved === 'true'
  return false
}

// Collapsible sections — persist in localStorage
const showMobileToolbar = ref(localStorage.getItem('toolbar_showMobileToolbar') !== null
  ? localStorage.getItem('toolbar_showMobileToolbar') === 'true'
  : getDefaultMobileToolbarOpen())
const showBalances = ref(getDefaultCollapsedState('toolbar_showBalances'))
function toggleMobileToolbar() {
  showMobileToolbar.value = !showMobileToolbar.value
  localStorage.setItem('toolbar_showMobileToolbar', showMobileToolbar.value)
}

function toggleBalances() {
  showBalances.value = !showBalances.value
  localStorage.setItem('toolbar_showBalances', showBalances.value)
}

// Hide toolbar extras on settings/privacy/components
const showToolbarExtras = computed(() => {
  const name = route.name
  return !['settings', 'privacy', 'components', 'position-detail'].includes(name)
})

// Account selector dropdown
const acctDropdownMobile = ref(false)
const acctDropdownDesktop = ref(false)
const acctDropdownMobileEl = ref(null)
const acctDropdownDesktopEl = ref(null)

function selectAccount(accountNumber, dropdown) {
  accountsStore.selectedAccount = accountNumber
  accountsStore.persistSelection()
  if (dropdown === 'mobile') acctDropdownMobile.value = false
  else acctDropdownDesktop.value = false
}

function onAcctClickOutside(e) {
  if (acctDropdownMobileEl.value && !acctDropdownMobileEl.value.contains(e.target)) acctDropdownMobile.value = false
  if (acctDropdownDesktopEl.value && !acctDropdownDesktopEl.value.contains(e.target)) acctDropdownDesktop.value = false
}

function selectedAccountLabel() {
  if (!accountsStore.selectedAccount) return 'All Accounts'
  const acct = accountsStore.accounts.find(a => a.account_number === accountsStore.selectedAccount)
  return acct?.account_name || accountsStore.selectedAccount
}

function selectedDotColor() {
  if (!accountsStore.selectedAccount) return null
  return accountDotColor(accountsStore.getAccountSymbol(accountsStore.selectedAccount))
}

// Close market popover on outside click
onMounted(() => {
  document.addEventListener('click', marketStore.closeExpanded)
  document.addEventListener('click', onAcctClickOutside)
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
  <div class="bg-tv-panel border-b border-tv-border">
    <div class="px-3 py-2 flex flex-col gap-2 md:hidden">
      <!-- Row 1: Sync + icon buttons -->
      <div class="flex items-center gap-1.5 relative">
        <template v-if="showToolbarExtras">
          <BaseButton variant="success" size="sm" @click="syncStore.performSync()" :disabled="syncStore.isSyncing" class="shrink-0 min-h-[44px]">
            <template #icon><BaseIcon name="sync-alt" :spin="syncStore.isSyncing" /></template>
            Sync
          </BaseButton>
        </template>

        <div class="flex items-center gap-1.5 ml-auto">
          <!-- Market Status icon -->
          <template v-if="showToolbarExtras">
            <button @click="marketStore.toggleExpanded($event)"
                    class="text-xs px-3 py-2 rounded border font-medium transition-colors min-h-[44px] min-w-[44px]"
                    :class="marketStore.marketExpanded ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border active:bg-tv-border/30'"
                    title="Market status">
              <span class="pulse-dot inline-block" :class="marketStore.dotColor" style="width:8px;height:8px;"></span>
            </button>

            <!-- Expanded Market Details (spans the mobile toolbar row width) -->
            <div v-show="marketStore.marketExpanded"
                 class="absolute inset-x-0 top-full mt-2 z-50 bg-tv-panel border border-tv-border rounded-lg shadow-2xl p-4"
                 @click.stop>
                <div class="text-xs uppercase tracking-wider text-tv-muted mb-3 font-semibold">Market Sessions</div>
                <div v-if="marketStore.marketStatus?.sessions?.length" class="space-y-3">
                  <div v-for="s in marketStore.marketStatus.sessions" :key="s.exchange"
                       class="border-b border-tv-border/30 pb-3 last:border-0 last:pb-0">
                    <div class="flex items-center justify-between mb-1.5 gap-2">
                      <span class="text-sm font-medium text-tv-text">{{ marketStore.exchangeLabel(s.exchange) }}</span>
                      <span class="text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap"
                            :class="s.status === 'Open' ? 'bg-tv-green/20 text-tv-green' : s.status === 'Pre-market' || s.status === 'Extended' ? 'bg-tv-amber/20 text-tv-amber' : s.status === 'Closed' ? 'bg-tv-red/20 text-tv-red' : 'bg-tv-muted/20 text-tv-muted'">
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
          </template>

          <!-- Overview -->
          <template v-if="showToolbarExtras">
            <button @click="toggleBalances()"
                    class="text-xs px-3 py-2 rounded border font-medium transition-colors min-h-[44px] min-w-[44px]"
                    :class="showBalances ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border active:bg-tv-border/30'"
                    title="Toggle account overview">
              <BaseIcon name="dollar-sign" class="text-[11px]" />
            </button>
            <!-- Filters -->
            <button @click="toggleFilters()"
                    class="text-xs px-3 py-2 rounded border font-medium transition-colors min-h-[44px] min-w-[44px]"
                    :class="showFilters ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border active:bg-tv-border/30'"
                    title="Toggle filters">
              <BaseIcon name="filter" class="text-[11px]" />
            </button>
            <!-- Sort (page-provided via Teleport) -->
            <div id="page-sort" class="relative"></div>
          </template>
        </div>
      </div>

      <!-- Row 2: Account Selector (always visible) -->
      <template v-if="showToolbarExtras">
        <div ref="acctDropdownMobileEl" class="relative w-full">
          <button @click="acctDropdownMobile = !acctDropdownMobile"
                  class="w-full bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-2 rounded min-h-[44px] flex items-center gap-2">
            <span v-if="selectedDotColor()" class="text-xl leading-none" :style="{ color: selectedDotColor() }">●</span>
            <span class="flex-1 text-left truncate">{{ selectedAccountLabel() }}</span>
            <BaseIcon name="chevron-down" class="text-[10px] text-tv-muted transition-transform" :class="acctDropdownMobile ? 'rotate-180' : ''" />
          </button>
          <div v-show="acctDropdownMobile" class="absolute top-full left-0 right-0 mt-1 z-50 bg-tv-panel border border-tv-border rounded shadow-xl py-1">
            <div v-if="accountsStore.accounts.length > 1" @click="selectAccount('', 'mobile')"
                 class="px-3 py-2.5 text-sm cursor-pointer active:bg-tv-border/30 flex items-center gap-2"
                 :class="!accountsStore.selectedAccount ? 'text-tv-text font-medium' : 'text-tv-muted'">
              All Accounts
            </div>
            <div v-for="account in accountsStore.accounts" :key="account.account_number"
                 @click="selectAccount(account.account_number, 'mobile')"
                 class="px-3 py-2.5 text-sm cursor-pointer active:bg-tv-border/30 flex items-center gap-2"
                 :class="accountsStore.selectedAccount === account.account_number ? 'text-tv-text font-medium' : 'text-tv-muted'">
              <span class="text-xl leading-none" :style="{ color: accountDotColor(accountsStore.getAccountSymbol(account.account_number)) }">●</span>
              <span>{{ account.account_name || account.account_number }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div class="hidden md:flex px-4 py-2.5 items-center justify-between">
      <div class="flex items-center gap-4">
        <!-- Sync Button -->
        <template v-if="showToolbarExtras">
          <BaseButton variant="success" size="md" @click="syncStore.performSync()" :disabled="syncStore.isSyncing">
            <template #icon><BaseIcon name="sync-alt" :spin="syncStore.isSyncing" /></template>
            Sync
          </BaseButton>
        </template>

        <!-- Market Status -->
        <template v-if="showToolbarExtras">
          <div class="relative">
            <button @click="marketStore.toggleExpanded($event)"
                    class="flex items-center gap-1.5 text-sm cursor-pointer hover:opacity-80 transition-opacity">
              <span class="inline-flex items-center gap-1.5">
                <span class="pulse-dot" :class="marketStore.dotColor"></span>
                <span :class="marketStore.statusColor" class="font-medium">{{ marketStore.statusLabel }}</span>
                <BaseIcon name="chevron-down" class="text-[8px] text-tv-muted transition-transform" :class="{ 'rotate-180': marketStore.marketExpanded }" />
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
                          :class="s.status === 'Open' ? 'bg-tv-green/20 text-tv-green' : s.status === 'Pre-market' || s.status === 'Extended' ? 'bg-tv-amber/20 text-tv-amber' : s.status === 'Closed' ? 'bg-tv-red/20 text-tv-red' : 'bg-tv-muted/20 text-tv-muted'">
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
          <div ref="acctDropdownDesktopEl" class="relative">
            <button @click="acctDropdownDesktop = !acctDropdownDesktop"
                    class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded flex items-center gap-2 min-w-[180px]">
              <span v-if="selectedDotColor()" class="text-xl leading-none" :style="{ color: selectedDotColor() }">●</span>
              <span class="flex-1 text-left truncate">{{ selectedAccountLabel() }}</span>
              <BaseIcon name="chevron-down" class="text-[10px] text-tv-muted transition-transform" :class="acctDropdownDesktop ? 'rotate-180' : ''" />
            </button>
            <div v-show="acctDropdownDesktop" class="absolute top-full right-0 mt-1 z-50 bg-tv-panel border border-tv-border rounded shadow-xl py-1 min-w-full">
              <div v-if="accountsStore.accounts.length > 1" @click="selectAccount('', 'desktop')"
                   class="px-3 py-2 text-sm cursor-pointer hover:bg-tv-border/30 flex items-center gap-2"
                   :class="!accountsStore.selectedAccount ? 'text-tv-text font-medium' : 'text-tv-muted'">
                All Accounts
              </div>
              <div v-for="account in accountsStore.accounts" :key="account.account_number"
                   @click="selectAccount(account.account_number, 'desktop')"
                   class="px-3 py-2 text-sm cursor-pointer hover:bg-tv-border/30 flex items-center gap-2"
                   :class="accountsStore.selectedAccount === account.account_number ? 'text-tv-text font-medium' : 'text-tv-muted'">
                <span class="text-xl leading-none" :style="{ color: accountDotColor(accountsStore.getAccountSymbol(account.account_number)) }">●</span>
                <span>{{ account.account_name || account.account_number }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- Section toggles -->
        <template v-if="showToolbarExtras">
          <div class="flex items-center gap-2 border-l border-tv-border pl-4">
            <button @click="toggleBalances()"
                    class="text-xs px-3 py-1.5 rounded border font-medium transition-colors"
                    :class="showBalances ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border hover:bg-tv-border/30'"
                    title="Toggle account overview">
              <BaseIcon name="dollar-sign" class="text-[10px] mr-1" />Overview
            </button>
            <button @click="toggleFilters()"
                    class="text-xs px-3 py-1.5 rounded border font-medium transition-colors"
                    :class="showFilters ? 'text-white bg-tv-blue border-tv-blue' : 'text-tv-text bg-tv-bg border-tv-border hover:bg-tv-border/30'"
                    title="Toggle filters">
              <BaseIcon name="filter" class="text-[10px] mr-1" />Filters
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- Mobile: Account Balances (shown directly when Overview toggled) -->
    <div v-if="showToolbarExtras && showBalances"
         class="md:hidden px-4 py-2.5 border-t border-tv-border/50">
      <div v-if="balancesStore.currentAccountBalance"
           class="bg-tv-panel border border-tv-border rounded px-4 py-3">
        <div class="flex flex-col gap-2 text-sm">
          <div class="flex items-center justify-between gap-3">
            <span class="text-tv-muted">Net Liq:</span>
            <span class="font-medium text-right">{{ balancesStore.privacyMode !== 'off' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.net_liquidating_value) }}</span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-tv-muted">Cash:</span>
            <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.cash_balance) }}</span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-tv-muted">Option BP:</span>
            <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.derivative_buying_power) }}</span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-tv-muted">Stock BP:</span>
            <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.equity_buying_power) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showToolbarExtras"
         class="md:hidden grid transition-[grid-template-rows] duration-200 ease-in-out grid-rows-[0fr]">
      <div class="overflow-hidden">
        <div class="px-4 pb-2.5 space-y-3">
          <!-- Section 2: Account Balances (desktop collapsible — keep for md+ only) (collapsible, animated) -->
          <div v-if="balancesStore.currentAccountBalance"
               class="grid transition-[grid-template-rows] duration-200 ease-in-out"
               :class="showBalances ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
            <div class="overflow-hidden">
              <div class="bg-tv-panel border border-tv-border rounded px-4 py-3">
                <div class="flex flex-col gap-2 text-sm">
                  <div class="flex items-center justify-between gap-3">
                    <span class="text-tv-muted">Net Liq:</span>
                    <span class="font-medium text-right">{{ balancesStore.privacyMode !== 'off' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.net_liquidating_value) }}</span>
                  </div>
                  <div class="flex items-center justify-between gap-3">
                    <span class="text-tv-muted">Cash:</span>
                    <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.cash_balance) }}</span>
                  </div>
                  <div class="flex items-center justify-between gap-3">
                    <span class="text-tv-muted">Option BP:</span>
                    <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.derivative_buying_power) }}</span>
                  </div>
                  <div class="flex items-center justify-between gap-3">
                    <span class="text-tv-muted">Stock BP:</span>
                    <span class="font-medium text-right">{{ balancesStore.privacyMode === 'high' ? '••••••' : '$' + formatNumber(balancesStore.currentAccountBalance.equity_buying_power) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Sync Summary Banner -->
  <div v-if="syncStore.syncSummary && !syncStore.isSyncing" class="mx-2 mt-2">
    <div class="px-4 py-2 rounded text-sm flex items-center justify-between bg-tv-blue/10 border border-tv-blue/30 text-tv-blue">
      <span>
        <BaseIcon name="sync-alt" class="mr-1" />
        {{ syncStore.syncSummary }}
      </span>
      <BaseButton variant="ghost" size="sm" icon="times" @click="syncStore.dismissSummary()" class="ml-4" />
    </div>
  </div>

  <!-- Section 2: Account Balances (collapsible, animated) -->
  <div v-if="showToolbarExtras && balancesStore.currentAccountBalance"
       class="hidden md:grid transition-[grid-template-rows] duration-200 ease-in-out"
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

            <!-- Section 3: Page-specific filters (via Teleport target) -->
          <div id="page-filters"></div>
</template>