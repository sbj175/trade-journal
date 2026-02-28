<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'

const Auth = useAuth()

// --- Reactive state ---
const targets = ref([])
const saving = ref(false)
const notification = ref(null)
const saveStatus = ref(null)

// Connection state
const connectionStatus = ref(null)
const providerSecret = ref('')
const refreshToken = ref('')
const savingCredentials = ref(false)
const deletingCredentials = ref(false)

// OAuth flow state
const onboarding = ref(false)
const authEnabled = ref(false)
const connecting = ref(false)

// Initial Sync
const syncStartDate = ref(new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10))
const syncMinDate = new Date(Date.now() - 730 * 86400000).toISOString().slice(0, 10)
const syncMaxDate = new Date().toISOString().slice(0, 10)
const initialSyncing = ref(false)

// Roll alerts
const rollAlerts = ref({
  enabled: true,
  profitTarget: true,
  lossLimit: true,
  lateStage: true,
  deltaSaturation: true,
  lowRewardToRisk: true,
})

// Privacy & tabs
const privacyMode = ref('off')
const activeTab = ref('connection')

// --- Computed ---
const syncDaysBack = computed(() => {
  const start = new Date(syncStartDate.value)
  const now = new Date()
  return Math.max(1, Math.round((now - start) / 86400000))
})

const CREDIT_NAMES = ['Bull Put Spread', 'Bear Call Spread', 'Iron Condor', 'Iron Butterfly',
  'Cash Secured Put', 'Covered Call', 'Short Put', 'Short Call',
  'Short Strangle', 'Short Straddle', 'Jade Lizard']

const DEBIT_NAMES = ['Bull Call Spread', 'Bear Put Spread', 'Long Call', 'Long Put',
  'Long Strangle', 'Long Straddle', 'Calendar Spread', 'Diagonal Spread', 'PMCC']

const MIXED_NAMES = ['Collar']
const EQUITY_NAMES = ['Shares']

const creditStrategies = computed(() => targets.value.filter(t => CREDIT_NAMES.includes(t.strategy_name)))
const debitStrategies = computed(() => targets.value.filter(t => DEBIT_NAMES.includes(t.strategy_name)))
const mixedStrategies = computed(() => targets.value.filter(t => MIXED_NAMES.includes(t.strategy_name)))
const equityStrategies = computed(() => targets.value.filter(t => EQUITY_NAMES.includes(t.strategy_name)))

// --- Nav auth controls ---
const userEmail = ref('')

async function updateNavAuth() {
  if (!Auth.isAuthEnabled()) return
  const user = await Auth.getUser()
  if (user) userEmail.value = user.email || ''
}

// --- Methods ---
async function checkConnection() {
  try {
    const resp = await Auth.authFetch('/api/connection/status')
    if (resp.ok) {
      connectionStatus.value = await resp.json()
    }
  } catch (e) {
    connectionStatus.value = { connected: false, configured: false, error: 'Could not check connection status' }
  }
}

async function connectTastytrade() {
  connecting.value = true
  try {
    const resp = await Auth.authFetch('/api/auth/tastytrade/authorize', { method: 'POST' })
    if (resp.ok) {
      const data = await resp.json()
      window.location.href = data.authorization_url
      return
    }
    const err = await resp.json().catch(() => ({}))
    showNotification(err.detail || 'Failed to start Tastytrade connection', 'error')
  } catch (e) {
    showNotification('Error: ' + e.message, 'error')
  }
  connecting.value = false
}

async function disconnectTastytrade() {
  if (!confirm('Disconnect your Tastytrade account? You will need to reconnect to sync trades.')) return
  deletingCredentials.value = true
  try {
    const resp = await Auth.authFetch('/api/auth/tastytrade/disconnect', { method: 'POST' })
    if (resp.ok) {
      showNotification('Tastytrade disconnected', 'success')
      await checkConnection()
    } else {
      const data = await resp.json().catch(() => ({}))
      showNotification(data.detail || 'Failed to disconnect', 'error')
    }
  } catch (e) {
    showNotification('Error: ' + e.message, 'error')
  }
  deletingCredentials.value = false
}

async function saveCredentials() {
  if (!providerSecret.value || !refreshToken.value) {
    showNotification('Please fill in both fields', 'error')
    return
  }
  savingCredentials.value = true
  try {
    const saveResp = await Auth.authFetch('/api/settings/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider_secret: providerSecret.value,
        refresh_token: refreshToken.value,
      }),
    })
    if (!saveResp.ok) {
      showNotification('Failed to save credentials', 'error')
      savingCredentials.value = false
      return
    }

    const reconnResp = await Auth.authFetch('/api/connection/reconnect', { method: 'POST' })
    if (reconnResp.ok) {
      connectionStatus.value = await reconnResp.json()
      if (connectionStatus.value.connected) {
        showNotification('Connected to Tastytrade successfully!', 'success')
        providerSecret.value = ''
        refreshToken.value = ''
      } else {
        showNotification('Credentials saved but connection failed: ' + (connectionStatus.value.error || 'Unknown error'), 'error')
      }
    } else {
      showNotification('Failed to reconnect', 'error')
    }
  } catch (e) {
    showNotification('Error saving credentials: ' + e.message, 'error')
  }
  savingCredentials.value = false
}

async function deleteCredentials() {
  if (!confirm('Remove your Tastytrade credentials? You will need to re-enter them to sync.')) return
  deletingCredentials.value = true
  try {
    const resp = await Auth.authFetch('/api/settings/credentials', { method: 'DELETE' })
    if (resp.ok) {
      showNotification('Credentials removed', 'success')
      await checkConnection()
    } else {
      const data = await resp.json().catch(() => ({}))
      showNotification(data.detail || 'Failed to remove credentials', 'error')
    }
  } catch (e) {
    showNotification('Error removing credentials: ' + e.message, 'error')
  }
  deletingCredentials.value = false
}

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

function loadRollAlerts() {
  try {
    const saved = localStorage.getItem('rollAlertSettings')
    if (saved) rollAlerts.value = JSON.parse(saved)
  } catch (e) { /* use defaults */ }
}

function saveRollAlerts() {
  localStorage.setItem('rollAlertSettings', JSON.stringify(rollAlerts.value))
  saveStatus.value = 'saved'
  setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = null }, 2000)
}

function savePrivacyMode() {
  localStorage.setItem('privacyMode', privacyMode.value)
  saveStatus.value = 'saved'
  setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = null }, 2000)
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
      window.location.href = '/positions'
      return
    }
    showNotification(
      `Initial sync completed! ${result.transactions_processed || 0} transactions, ` +
      `${result.orders_saved || 0} orders in ${result.chains_saved || 0} chains`,
      'success',
    )
  } catch (error) {
    showNotification('Initial sync failed: ' + error.message, 'error')
  } finally {
    initialSyncing.value = false
  }
}

function showNotification(message, type) {
  notification.value = { message, type }
  setTimeout(() => { notification.value = null }, 3000)
}

// --- Lifecycle ---
onMounted(async () => {
  await Auth.requireAuth()

  // Parse URL query params
  const params = new URLSearchParams(window.location.search)
  if (params.get('tab')) activeTab.value = params.get('tab')
  onboarding.value = params.get('onboarding') === '1'
  authEnabled.value = Auth.isAuthEnabled()

  // Show error from OAuth callback redirect
  const errorParam = params.get('error')
  if (errorParam) showNotification(decodeURIComponent(errorParam), 'error')

  await updateNavAuth()
  await checkConnection()
  await loadTargets()
  loadRollAlerts()
  privacyMode.value = localStorage.getItem('privacyMode') || 'off'
})

// Nav links (matches pages.py NAV_LINKS)
const navLinks = [
  { href: '/positions', label: 'Positions' },
  { href: '/ledger', label: 'Ledger' },
  { href: '/reports', label: 'Reports' },
  { href: '/risk', label: 'Risk' },
]
</script>

<template>
  <!-- Navigation -->
  <nav class="bg-tv-panel border-b border-tv-border sticky top-0 z-50">
    <div class="flex items-center justify-between h-16 px-4">
      <div class="flex items-center gap-8">
        <span class="text-tv-blue font-semibold text-2xl">
          <i class="fas fa-chart-line mr-2"></i>OptionLedger
        </span>
        <div class="flex items-center border-l border-tv-border pl-8 gap-4">
          <a v-for="link in navLinks" :key="link.href" :href="link.href"
             class="text-tv-muted hover:text-tv-text px-4 py-2 text-lg">
            {{ link.label }}
          </a>
        </div>
      </div>
      <div class="flex items-center gap-4 text-base">
        <div v-if="connectionStatus" class="flex items-center gap-2 text-sm">
          <span v-if="connectionStatus.connected" class="text-tv-green">
            <i class="fas fa-circle text-[8px] mr-1"></i>Connected
          </span>
          <span v-else class="text-tv-red">
            <i class="fas fa-circle text-[8px] mr-1"></i>Disconnected
          </span>
        </div>
        <div v-if="authEnabled && userEmail" class="flex items-center gap-3">
          <span class="text-tv-muted text-sm">{{ userEmail }}</span>
          <button @click="Auth.signOut()" class="text-tv-muted hover:text-tv-red text-sm" title="Sign out">
            <i class="fas fa-sign-out-alt"></i>
          </button>
        </div>
        <a href="/settings" class="text-tv-blue hover:text-tv-text px-3 py-1 border border-tv-blue rounded text-sm">
          <i class="fas fa-cog mr-1"></i>Settings
        </a>
      </div>
    </div>
  </nav>

  <!-- Notification Toast -->
  <Transition
    enter-active-class="transition ease-out duration-200"
    leave-active-class="transition ease-in duration-150"
    enter-from-class="opacity-0 translate-y-[-8px]"
    leave-to-class="opacity-0 translate-y-[-8px]"
  >
    <div v-if="notification"
         class="fixed top-20 right-4 z-50 px-4 py-3 rounded shadow-lg text-sm"
         :class="notification.type === 'success'
           ? 'bg-tv-green/20 border border-tv-green/30 text-tv-green'
           : 'bg-tv-red/20 border border-tv-red/30 text-tv-red'">
      {{ notification.message }}
    </div>
  </Transition>

  <!-- Main Content -->
  <div class="flex" style="height: calc(100vh - 64px)">

    <!-- Left Sidebar Tabs -->
    <div class="w-56 flex-shrink-0 bg-tv-panel border-r border-tv-border py-4">
      <div class="px-3 mb-4">
        <h1 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-cog mr-2 text-tv-blue"></i>Settings
        </h1>
      </div>
      <nav class="space-y-0.5 px-2">
        <button v-for="tab in [
          { id: 'connection', icon: 'fa-plug', label: 'Connection' },
          { id: 'import', icon: 'fa-file-import', label: 'Import Trades' },
          { id: 'privacy', icon: 'fa-eye-slash', label: 'Privacy' },
          { id: 'targets', icon: 'fa-bullseye', label: 'Strategy Targets' },
          { id: 'alerts', icon: 'fa-bell', label: 'Roll Alerts' },
        ]" :key="tab.id"
          @click="activeTab = tab.id"
          class="w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm transition-colors text-left"
          :class="activeTab === tab.id
            ? 'bg-tv-blue/15 text-tv-blue border border-tv-blue/30'
            : 'text-tv-muted hover:text-tv-text hover:bg-tv-bg border border-transparent'">
          <i class="fas w-4 text-center" :class="tab.icon"></i>
          <span>{{ tab.label }}</span>
          <span v-if="tab.id === 'connection'" class="ml-auto">
            <i class="fas fa-circle text-[6px]"
               :class="connectionStatus?.connected ? 'text-tv-green' : 'text-tv-red'"></i>
          </span>
        </button>
      </nav>
    </div>

    <!-- Right Content Area -->
    <div class="flex-1 overflow-y-auto tv-scrollbar p-6">
      <!-- Save status indicator -->
      <div class="flex items-center justify-end mb-4 h-5">
        <span v-if="saveStatus === 'pending'" class="text-xs text-tv-muted">
          <i class="fas fa-circle text-yellow-500 text-[8px] mr-1"></i>Unsaved
        </span>
        <span v-if="saveStatus === 'saving'" class="text-xs text-tv-muted">
          <i class="fas fa-spinner fa-spin mr-1"></i>Saving...
        </span>
        <span v-if="saveStatus === 'saved'" class="text-xs text-tv-green">
          <i class="fas fa-check mr-1"></i>Saved
        </span>
      </div>

      <!-- ==================== Connection Tab ==================== -->
      <div v-show="activeTab === 'connection'">
        <div class="mb-6 flex items-start justify-between">
          <div>
            <h2 class="text-xl font-semibold text-tv-text mb-1">
              <i class="fas fa-plug mr-2 text-tv-blue"></i>Tastytrade Connection
            </h2>
            <p class="text-tv-muted text-sm">
              {{ authEnabled ? 'Connect your Tastytrade account with one click' : 'Connect to Tastytrade using OAuth2 credentials' }}
            </p>
          </div>
          <div v-if="connectionStatus && !onboarding" class="flex items-center gap-2">
            <span v-if="connectionStatus.connected"
                  class="bg-tv-green/20 text-tv-green border border-tv-green/30 px-3 py-1 rounded text-xs font-medium">
              <i class="fas fa-check-circle mr-1"></i>Connected
            </span>
            <span v-else-if="connectionStatus.configured"
                  class="bg-tv-red/20 text-tv-red border border-tv-red/30 px-3 py-1 rounded text-xs font-medium">
              <i class="fas fa-exclamation-circle mr-1"></i>Connection Failed
            </span>
            <span v-else
                  class="bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 px-3 py-1 rounded text-xs font-medium">
              <i class="fas fa-info-circle mr-1"></i>Not Configured
            </span>
          </div>
        </div>

        <!-- Auth-enabled mode: OAuth Authorization Code flow -->
        <template v-if="authEnabled">
          <!-- Onboarding welcome panel -->
          <div v-if="onboarding && !connectionStatus?.configured" class="bg-tv-panel border border-tv-blue/30 rounded mb-5">
            <div class="p-6 text-center">
              <div class="text-4xl mb-4"><i class="fas fa-handshake text-tv-blue"></i></div>
              <h3 class="text-xl font-semibold text-tv-text mb-2">Welcome! Let's connect your Tastytrade account.</h3>
              <p class="text-tv-muted text-sm mb-5 max-w-lg mx-auto">
                OptionLedger needs read-only access to your Tastytrade account to import your trades and positions.
              </p>
              <div class="flex flex-col items-center gap-3 mb-5">
                <div class="flex items-center gap-2 text-sm text-tv-muted">
                  <i class="fas fa-shield-halved text-tv-green w-5 text-center"></i>
                  <span>Read-only scope &mdash; we cannot place trades or modify your account</span>
                </div>
                <div class="flex items-center gap-2 text-sm text-tv-muted">
                  <i class="fas fa-lock text-tv-green w-5 text-center"></i>
                  <span>Not your password &mdash; you authorize directly on Tastytrade's website</span>
                </div>
                <div class="flex items-center gap-2 text-sm text-tv-muted">
                  <i class="fas fa-database text-tv-green w-5 text-center"></i>
                  <span>Encrypted at rest &mdash; your credentials are encrypted in our database</span>
                </div>
                <div class="flex items-center gap-2 text-sm text-tv-muted">
                  <i class="fas fa-rotate-left text-tv-green w-5 text-center"></i>
                  <span>Revoke anytime &mdash; disconnect here or revoke access on Tastytrade</span>
                </div>
              </div>
              <button @click="connectTastytrade()" :disabled="connecting"
                      class="bg-tv-blue hover:bg-tv-blue/80 text-white px-8 py-3 rounded-lg text-base font-medium disabled:opacity-50 transition-colors">
                <i v-if="!connecting" class="fas fa-right-to-bracket mr-2"></i>
                <i v-if="connecting" class="fas fa-spinner fa-spin mr-2"></i>
                {{ connecting ? 'Redirecting...' : 'Connect to Tastytrade' }}
              </button>
            </div>
          </div>

          <!-- Normal connection panel (returning user or post-onboarding) -->
          <div v-if="!onboarding || connectionStatus?.configured" class="bg-tv-panel border border-tv-border rounded">
            <div class="p-5 space-y-4">
              <div v-if="connectionStatus?.error" class="bg-tv-red/10 border border-tv-red/20 rounded p-3 text-sm text-tv-red">
                <i class="fas fa-exclamation-triangle mr-1"></i>
                {{ connectionStatus.error }}
              </div>
              <div v-if="connectionStatus?.connected && connectionStatus?.accounts?.length" class="text-sm flex flex-col items-start gap-1.5">
                <span class="text-tv-muted">Accounts:</span>
                <div v-for="acct in connectionStatus.accounts" :key="acct.account_number"
                     class="inline-flex items-center gap-2 bg-tv-bg border border-tv-border rounded px-3 py-1.5 ml-4">
                  <span class="text-tv-text font-medium">{{ acct.account_number }}</span>
                  <span class="text-tv-muted">&mdash;</span>
                  <span class="text-tv-muted">{{ acct.account_name }}</span>
                </div>
              </div>
              <div class="flex items-center gap-3">
                <button @click="connectTastytrade()" :disabled="connecting"
                        class="bg-tv-blue hover:bg-tv-blue/80 text-white px-5 py-2 rounded text-sm disabled:opacity-50">
                  <i v-if="!connecting" class="fas fa-right-to-bracket mr-1"></i>
                  <i v-if="connecting" class="fas fa-spinner fa-spin mr-1"></i>
                  {{ connecting ? 'Redirecting...' : (connectionStatus?.configured ? 'Reconnect to Tastytrade' : 'Connect to Tastytrade') }}
                </button>
                <button v-if="connectionStatus?.configured"
                        @click="disconnectTastytrade()" :disabled="deletingCredentials"
                        class="bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30 px-4 py-2 rounded text-sm disabled:opacity-50">
                  <i v-if="!deletingCredentials" class="fas fa-unlink mr-1"></i>
                  <i v-if="deletingCredentials" class="fas fa-spinner fa-spin mr-1"></i>
                  {{ deletingCredentials ? 'Disconnecting...' : 'Disconnect' }}
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- Auth-disabled mode: manual credential form -->
        <template v-if="!authEnabled">
          <div class="bg-tv-panel border border-tv-border rounded">
            <div class="p-5 space-y-4">
              <div v-if="connectionStatus?.error" class="bg-tv-red/10 border border-tv-red/20 rounded p-3 text-sm text-tv-red">
                <i class="fas fa-exclamation-triangle mr-1"></i>
                {{ connectionStatus.error }}
              </div>
              <div v-if="connectionStatus?.connected && connectionStatus?.accounts?.length" class="text-sm flex flex-col items-start gap-1.5">
                <span class="text-tv-muted">Accounts:</span>
                <div v-for="acct in connectionStatus.accounts" :key="acct.account_number"
                     class="inline-flex items-center gap-2 bg-tv-bg border border-tv-border rounded px-3 py-1.5 ml-4">
                  <span class="text-tv-text font-medium">{{ acct.account_number }}</span>
                  <span class="text-tv-muted">&mdash;</span>
                  <span class="text-tv-muted">{{ acct.account_name }}</span>
                </div>
              </div>
              <div class="space-y-3">
                <div>
                  <label class="block text-tv-muted text-sm mb-1">Client Secret <span class="text-tv-muted/50">(saved as provider_secret)</span></label>
                  <input type="password" v-model="providerSecret" placeholder="Enter your Client Secret from Tastytrade"
                         class="ml-4 w-[calc(100%-1rem)] bg-tv-bg border border-tv-border text-tv-text px-3 py-2 rounded text-sm focus:outline-none focus:border-tv-blue">
                </div>
                <div>
                  <label class="block text-tv-muted text-sm mb-1">Refresh Token</label>
                  <input type="password" v-model="refreshToken" placeholder="Enter your Refresh Token from Tastytrade"
                         class="ml-4 w-[calc(100%-1rem)] bg-tv-bg border border-tv-border text-tv-text px-3 py-2 rounded text-sm focus:outline-none focus:border-tv-blue">
                </div>
                <div class="flex items-center gap-3 ml-4">
                  <button @click="saveCredentials()" :disabled="savingCredentials"
                          class="bg-tv-blue hover:bg-tv-blue/80 text-white px-4 py-2 rounded text-sm disabled:opacity-50">
                    <i v-if="!savingCredentials" class="fas fa-save mr-1"></i>
                    <i v-if="savingCredentials" class="fas fa-spinner fa-spin mr-1"></i>
                    {{ savingCredentials ? 'Connecting...' : 'Save &amp; Connect' }}
                  </button>
                  <button v-if="connectionStatus?.configured"
                          @click="deleteCredentials()" :disabled="deletingCredentials"
                          class="bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30 px-4 py-2 rounded text-sm disabled:opacity-50">
                    <i v-if="!deletingCredentials" class="fas fa-trash-alt mr-1"></i>
                    <i v-if="deletingCredentials" class="fas fa-spinner fa-spin mr-1"></i>
                    {{ deletingCredentials ? 'Removing...' : 'Remove Credentials' }}
                  </button>
                </div>
              </div>
              <div class="bg-tv-bg border border-tv-border rounded p-3 text-xs text-tv-muted space-y-2 ml-4">
                <p class="font-medium text-tv-text"><i class="fas fa-info-circle mr-1 text-tv-blue"></i>How to get OAuth credentials</p>
                <ol class="list-decimal list-inside space-y-1 ml-1">
                  <li>Log in to <strong class="text-tv-text">my.tastytrade.com</strong></li>
                  <li>Go to <strong class="text-tv-text">Manage &rarr; My Profile &rarr; API</strong></li>
                  <li>Under <strong class="text-tv-text">OAuth Applications</strong>, create a new app (or view existing)</li>
                  <li>Copy the <strong class="text-tv-text">Client Secret</strong> (this is the first field above)</li>
                  <li>Create a <strong class="text-tv-text">Grant</strong> for the app to generate a <strong class="text-tv-text">Refresh Token</strong></li>
                  <li>Copy the <strong class="text-tv-text">Refresh Token</strong> (this is the second field above)</li>
                </ol>
                <p class="text-tv-muted/70 italic">Note: The Client ID shown by Tastytrade is not needed. Only Client Secret and Refresh Token are required.</p>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- ==================== Import Trades Tab ==================== -->
      <div v-show="activeTab === 'import'">
        <div class="mb-6">
          <h2 class="text-xl font-semibold text-tv-text mb-1">
            <i class="fas fa-file-import mr-2 text-tv-blue"></i>Import Trades
          </h2>
          <p class="text-tv-muted text-sm">Rebuild or reprocess your trade data from Tastytrade</p>
        </div>

        <!-- Onboarding welcome banner -->
        <div v-if="onboarding" class="bg-tv-green/10 border border-tv-green/30 rounded p-4 mb-5">
          <div class="flex items-start gap-3">
            <i class="fas fa-check-circle text-tv-green text-lg mt-0.5"></i>
            <div>
              <p class="text-tv-text font-medium">Your Tastytrade account is connected!</p>
              <p class="text-tv-muted text-sm mt-1">Run an Initial Sync below to import your trading history. Choose a start date for how far back you'd like to import.</p>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div class="bg-tv-panel border border-tv-border rounded">
            <div class="p-5">
              <div class="flex items-start justify-between">
                <div>
                  <h3 class="text-tv-text font-medium mb-1">
                    <i class="fas fa-database mr-2 text-tv-muted"></i>Initial Sync
                  </h3>
                  <p class="text-tv-muted text-sm">Clears the existing database and rebuilds it from scratch. Fetches all transactions from the selected start date.</p>
                </div>
                <button @click="initialSync()" :disabled="initialSyncing"
                        class="flex-shrink-0 ml-6 px-5 py-2.5 rounded text-sm disabled:opacity-50 whitespace-nowrap"
                        :class="onboarding
                          ? 'bg-tv-blue hover:bg-tv-blue/80 text-white'
                          : 'bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30'">
                  <i class="fas fa-database mr-2" :class="{ 'animate-spin': initialSyncing }"></i>
                  {{ initialSyncing ? 'Importing...' : (onboarding ? 'Import Trades' : 'Initial Sync') }}
                </button>
              </div>
              <div class="mt-4 flex items-center gap-3 ml-7">
                <label class="text-tv-muted text-sm whitespace-nowrap">Import from:</label>
                <input type="date" v-model="syncStartDate"
                       :min="syncMinDate" :max="syncMaxDate"
                       class="bg-tv-bg border border-tv-border text-tv-text px-3 py-1.5 rounded text-sm focus:outline-none focus:border-tv-blue">
                <span class="text-tv-muted text-xs">{{ syncDaysBack }} days of history</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Progress overlay -->
        <div v-if="initialSyncing" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div class="bg-tv-panel border border-tv-border rounded-lg px-8 py-6 text-center shadow-2xl">
            <i class="fas fa-spinner animate-spin text-tv-blue text-3xl mb-4"></i>
            <p class="text-tv-text text-lg font-medium">Rebuilding database...</p>
            <p class="text-tv-muted text-sm mt-2">This may take a few seconds</p>
          </div>
        </div>
      </div>

      <!-- ==================== Privacy Mode Tab ==================== -->
      <div v-show="activeTab === 'privacy'">
        <div class="mb-6">
          <h2 class="text-xl font-semibold text-tv-text mb-1">
            <i class="fas fa-eye-slash mr-2 text-tv-muted"></i>Privacy Mode
          </h2>
          <p class="text-tv-muted text-sm">Hide sensitive account balance information on the Positions page</p>
        </div>
        <div class="bg-tv-panel border border-tv-border rounded">
          <div class="p-5">
            <div class="flex items-center gap-4">
              <label v-for="option in [
                { value: 'off', label: 'Off', icon: 'fa-eye', desc: 'All values visible' },
                { value: 'medium', label: 'Medium', icon: 'fa-eye-low-vision', desc: 'Hides Net Liq' },
                { value: 'high', label: 'High', icon: 'fa-eye-slash', desc: 'Hides all balances' },
              ]" :key="option.value" class="flex-1 cursor-pointer">
                <input type="radio" name="privacyMode" :value="option.value"
                       v-model="privacyMode" @change="savePrivacyMode()" class="sr-only">
                <div class="border rounded p-4 text-center transition-colors"
                     :class="privacyMode === option.value
                       ? 'border-tv-blue bg-tv-blue/10 text-tv-text'
                       : 'border-tv-border bg-tv-bg text-tv-muted hover:border-tv-muted'">
                  <i class="fas text-2xl mb-2" :class="option.icon"></i>
                  <div class="text-sm font-medium">{{ option.label }}</div>
                  <div class="text-xs mt-1 opacity-70">{{ option.desc }}</div>
                </div>
              </label>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== Strategy Targets Tab ==================== -->
      <div v-show="activeTab === 'targets'">
        <div class="mb-6 flex items-start justify-between">
          <div>
            <h2 class="text-xl font-semibold text-tv-text mb-1">
              <i class="fas fa-bullseye mr-2 text-tv-blue"></i>Strategy Targets
            </h2>
            <p class="text-tv-muted text-sm">Configure profit and loss targets for each strategy type</p>
          </div>
          <button @click="resetToDefaults()"
                  class="bg-tv-bg hover:bg-tv-border text-tv-muted hover:text-tv-text border border-tv-border px-4 py-2 text-sm rounded">
            <i class="fas fa-rotate-left mr-1"></i>Reset to Defaults
          </button>
        </div>

        <!-- Strategy table for each category -->
        <template v-for="category in [
          { key: 'credit', label: 'Credit Strategies', desc: 'Strategies where you collect premium upfront', icon: 'fa-arrow-down', color: 'text-tv-green', items: creditStrategies },
          { key: 'debit', label: 'Debit Strategies', desc: 'Strategies where you pay premium upfront', icon: 'fa-arrow-up', color: 'text-tv-blue', items: debitStrategies },
          { key: 'mixed', label: 'Mixed Strategies', desc: 'Strategies combining credit and debit components', icon: 'fa-exchange-alt', color: 'text-tv-muted', items: mixedStrategies },
          { key: 'equity', label: 'Equity', desc: 'Stock/share positions', icon: 'fa-chart-bar', color: 'text-tv-muted', items: equityStrategies },
        ]" :key="category.key">
          <div v-if="category.items.length > 0"
               class="bg-tv-panel border border-tv-border rounded mb-5" @input="debouncedSaveTargets()">
            <div class="px-4 py-3 border-b border-tv-border">
              <h3 class="text-sm font-semibold text-tv-text">
                <i class="fas mr-2" :class="[category.icon, category.color]"></i>{{ category.label }}
              </h3>
              <p class="text-tv-muted text-xs mt-0.5">{{ category.desc }}</p>
            </div>
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-tv-border text-tv-muted text-left">
                  <th class="px-4 py-2 font-medium">Strategy</th>
                  <th class="px-4 py-2 font-medium text-center w-40">Profit Target %</th>
                  <th class="px-4 py-2 font-medium text-center w-40">Loss Limit %</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="target in category.items" :key="target.strategy_name"
                    class="border-b border-tv-border/50 hover:bg-tv-bg/50">
                  <td class="px-4 py-2 text-tv-text">{{ target.strategy_name }}</td>
                  <td class="px-4 py-2 text-center">
                    <input type="number" v-model.number="target.profit_target_pct" min="0" max="500" step="5"
                           class="w-20 bg-tv-bg border border-tv-border text-tv-green text-center px-2 py-1 rounded focus:outline-none focus:border-tv-blue">
                  </td>
                  <td class="px-4 py-2 text-center">
                    <input type="number" v-model.number="target.loss_target_pct" min="0" max="500" step="5"
                           class="w-20 bg-tv-bg border border-tv-border text-tv-red text-center px-2 py-1 rounded focus:outline-none focus:border-tv-blue">
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <!-- How targets work -->
        <div class="bg-tv-panel border border-tv-border rounded p-4 text-sm text-tv-muted">
          <p class="font-medium text-tv-text mb-2"><i class="fas fa-info-circle mr-1 text-tv-blue"></i>How targets work</p>
          <ul class="list-disc list-inside space-y-1">
            <li><strong class="text-tv-green">Profit Target %</strong> — Percentage of max profit at which to consider closing for a win</li>
            <li><strong class="text-tv-red">Loss Limit %</strong> — Percentage of max loss at which to consider closing to limit damage</li>
            <li>For credit strategies, a 50% profit target means close when you've captured 50% of the premium collected</li>
            <li>For debit strategies, a 100% profit target means close when the position has doubled in value</li>
          </ul>
        </div>
      </div>

      <!-- ==================== Roll Alerts Tab ==================== -->
      <div v-show="activeTab === 'alerts'">
        <div class="mb-6">
          <h2 class="text-xl font-semibold text-tv-text mb-1">
            <i class="fas fa-bell mr-2 text-yellow-400"></i>Roll Suggestion Alerts
          </h2>
          <p class="text-tv-muted text-sm">Configure which roll/close suggestions appear on the Positions page for debit spreads</p>
        </div>
        <div class="bg-tv-panel border border-tv-border rounded" @change="saveRollAlerts()">
          <div class="p-5 space-y-3">
            <!-- Master toggle -->
            <label class="flex items-center justify-between py-2 border-b border-tv-border/50 cursor-pointer">
              <div>
                <span class="text-tv-text font-medium">Enable Roll Suggestions</span>
                <span class="text-tv-muted text-xs block">Master toggle for all roll analysis badges and panels</span>
              </div>
              <div class="relative">
                <input type="checkbox" v-model="rollAlerts.enabled" class="sr-only">
                <div class="w-10 h-5 rounded-full transition-colors"
                     :class="rollAlerts.enabled ? 'bg-tv-blue' : 'bg-tv-border'"></div>
                <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform"
                     :class="rollAlerts.enabled ? 'translate-x-5' : ''"></div>
              </div>
            </label>

            <!-- Individual toggles -->
            <div class="space-y-2 pl-2" :class="{ 'opacity-40 pointer-events-none': !rollAlerts.enabled }">
              <label v-for="alert in [
                { key: 'profitTarget', label: 'Profit Target', desc: 'Alert when position reaches your configured profit target', color: 'bg-tv-green' },
                { key: 'lossLimit', label: 'Loss Limit', desc: 'Alert when position reaches your configured loss threshold', color: 'bg-tv-red' },
                { key: 'lateStage', label: 'Late-Stage', desc: 'Alert when multiple maturing indicators converge (low DTE, high delta, etc.)', color: 'bg-yellow-500' },
                { key: 'deltaSaturation', label: 'Delta Saturation', desc: 'Alert when spread delta exceeds 65% (diminishing convexity)', color: 'bg-orange-500' },
                { key: 'lowRewardToRisk', label: 'Low Reward-to-Risk', desc: 'Alert when remaining reward-to-risk ratio falls below 0.6', color: 'bg-orange-500' },
              ]" :key="alert.key"
                class="flex items-center justify-between py-1.5 cursor-pointer">
                <div>
                  <span class="text-tv-text text-sm">{{ alert.label }}</span>
                  <span class="text-tv-muted text-xs block">{{ alert.desc }}</span>
                </div>
                <div class="relative">
                  <input type="checkbox" v-model="rollAlerts[alert.key]" class="sr-only">
                  <div class="w-10 h-5 rounded-full transition-colors"
                       :class="rollAlerts[alert.key] ? alert.color : 'bg-tv-border'"></div>
                  <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform"
                       :class="rollAlerts[alert.key] ? 'translate-x-5' : ''"></div>
                </div>
              </label>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>
