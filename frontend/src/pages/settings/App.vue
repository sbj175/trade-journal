<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useConfirm } from '@/composables/useConfirm'
import { useAuthStore } from '@/stores/auth'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { useSettingsConnection } from './useSettingsConnection'
import { useSettingsAccounts } from './useSettingsAccounts'
import { useSettingsTargets } from './useSettingsTargets'
import { useSettingsTags } from './useSettingsTags'
import { useSettingsSync } from './useSettingsSync'
import { useSettingsPreferences } from './useSettingsPreferences'

const Auth = useAuth()
const { show: confirmShow, title: confirmTitle, message: confirmMessage, confirmText: confirmBtnText, cancelText: confirmCancelText, variant: confirmVariant, onConfirm, onCancel } = useConfirm()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// --- Shared state ---
const notification = ref(null)
const activeTab = ref('connection')

function showNotification(message, type) {
  notification.value = { message, type }
  setTimeout(() => { notification.value = null }, 3000)
}

// --- Composables ---
const {
  connectionStatus, providerSecret, refreshToken, savingCredentials, deletingCredentials,
  onboarding, authEnabled, connecting, consentAcknowledged,
  checkConnection, connectTastytrade, disconnectTastytrade,
  saveCredentials, deleteCredentials, toggleConsent,
} = useSettingsConnection(Auth, { showNotification })

const {
  allAccounts, accountsSaving, syncingAccount,
  loadAllAccounts, toggleAccount,
} = useSettingsAccounts(Auth, { showNotification, onboarding })

const {
  targets, saveStatus,
  creditStrategies, debitStrategies, mixedStrategies, equityStrategies,
  loadTargets, debouncedSaveTargets, resetToDefaults,
} = useSettingsTargets(Auth, { showNotification })

const {
  tags, editingTag, editName, editColor, deletingTagId,
  loadTags, startEditTag, cancelEditTag, saveTag, deleteTag,
} = useSettingsTags(Auth, { showNotification })

const {
  syncStartDate, syncMinDate, syncMaxDate, initialSyncing, importResult,
  syncDaysBack, goToPositions, initialSync,
} = useSettingsSync(Auth, { showNotification, onboarding, router })

const {
  privacyMode, rollAlerts,
  loadRollAlerts, saveRollAlerts, savePrivacyMode, loadPrivacyMode,
} = useSettingsPreferences({ saveStatus })

// --- Lifecycle ---
onMounted(async () => {
  // Parse URL query params (via vue-router)
  if (route.query.tab) activeTab.value = route.query.tab
  onboarding.value = route.query.onboarding === '1'
  authEnabled.value = Auth.isAuthEnabled()

  // Show error from OAuth callback redirect
  const errorParam = route.query.error
  if (errorParam) showNotification(decodeURIComponent(errorParam), 'error')

  await checkConnection()
  await loadAllAccounts()
  await loadTargets()
  await loadTags()
  loadRollAlerts()
  loadPrivacyMode()
  consentAcknowledged.value = localStorage.getItem('dataConsentAcknowledged') === 'true'
})

</script>

<template>
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
  <div class="flex" style="height: calc(100vh - 56px)">

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
          { id: 'accounts', icon: 'fa-university', label: 'Accounts' },
          { id: 'import', icon: 'fa-file-import', label: 'Import Trades' },
          { id: 'privacy', icon: 'fa-eye-slash', label: 'Privacy' },
          { id: 'targets', icon: 'fa-bullseye', label: 'Strategy Targets' },
          { id: 'alerts', icon: 'fa-bell', label: 'Roll Alerts' },
          { id: 'tags', icon: 'fa-tags', label: 'Tags' },
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
          <i class="fas fa-circle text-tv-amber text-[8px] mr-1"></i>Unsaved
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
                  class="bg-tv-amber/20 text-tv-amber border border-tv-amber/30 px-3 py-1 rounded text-xs font-medium">
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
              <!-- Data disclosure consent -->
              <div class="bg-tv-bg border border-tv-border rounded p-4 text-left max-w-lg mx-auto mb-5">
                <p class="text-tv-text text-sm font-medium mb-2">
                  <i class="fas fa-shield-halved mr-1 text-tv-blue"></i>Data disclosure
                </p>
                <p class="text-tv-muted text-xs mb-2">
                  OptionLedger will access your account info, transaction history, positions, and real-time quotes (read-only).
                  Your OAuth token is encrypted at rest. Your data is never shared with third parties.
                </p>
                <a href="/privacy" target="_blank" class="text-tv-blue hover:underline text-xs">
                  <i class="fas fa-external-link-alt mr-1"></i>Full privacy & data practices
                </a>
                <label class="flex items-center gap-2 mt-3 cursor-pointer">
                  <input type="checkbox" :checked="consentAcknowledged" @change="toggleConsent()"
                         class="w-4 h-4 rounded border-tv-border bg-tv-bg text-tv-blue focus:ring-tv-blue">
                  <span class="text-tv-text text-sm">I understand what data OptionLedger will access and store</span>
                </label>
              </div>
              <button @click="connectTastytrade()" :disabled="connecting || !consentAcknowledged"
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
              <!-- Data consent (shown when not yet connected) -->
              <div v-if="!connectionStatus?.configured" class="bg-tv-bg border border-tv-border rounded p-3 text-sm">
                <p class="text-tv-muted text-xs mb-2">
                  <i class="fas fa-shield-halved mr-1 text-tv-blue"></i>
                  OptionLedger will access your account info, transactions, positions, and quotes (read-only).
                  Your token is encrypted at rest. Data is never shared with third parties.
                  <a href="/privacy" target="_blank" class="text-tv-blue hover:underline ml-1">Learn more</a>
                </p>
                <label class="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" :checked="consentAcknowledged" @change="toggleConsent()"
                         class="w-4 h-4 rounded border-tv-border bg-tv-bg text-tv-blue focus:ring-tv-blue">
                  <span class="text-tv-text text-sm">I understand what data OptionLedger will access and store</span>
                </label>
              </div>
              <div class="flex items-center gap-3">
                <button @click="connectTastytrade()" :disabled="connecting || (!connectionStatus?.configured && !consentAcknowledged)"
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
              <!-- Privacy link (always visible) -->
              <div class="mt-2">
                <a href="/privacy" target="_blank" class="text-tv-muted hover:text-tv-blue text-xs">
                  <i class="fas fa-shield-halved mr-1"></i>Privacy & Data Practices
                </a>
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

      <!-- ==================== Accounts Tab ==================== -->
      <div v-show="activeTab === 'accounts'">
        <div class="mb-6">
          <h2 class="text-xl font-semibold text-tv-text mb-1">
            <i class="fas fa-university mr-2 text-tv-blue"></i>Accounts
          </h2>
          <p class="text-tv-muted text-sm">Choose which Tastytrade accounts to sync. Disabled accounts will not be imported during sync.</p>
        </div>

        <!-- Onboarding banner -->
        <div v-if="onboarding" class="bg-tv-green/10 border border-tv-green/30 rounded p-4 mb-5">
          <div class="flex items-start gap-3">
            <i class="fas fa-check-circle text-tv-green text-lg mt-0.5"></i>
            <div>
              <p class="text-tv-text font-medium">Your Tastytrade account is connected!</p>
              <p class="text-tv-muted text-sm mt-1">We found the accounts below. Toggle off any you don't want to sync, then continue to import your trades.</p>
            </div>
          </div>
        </div>

        <div v-if="allAccounts.length === 0" class="text-tv-muted text-sm py-8 text-center">
          <i class="fas fa-info-circle mr-1"></i>No accounts found. Connect to Tastytrade first.
        </div>

        <div v-else class="space-y-2">
          <div v-for="acct in allAccounts" :key="acct.account_number"
               class="flex items-center justify-between bg-tv-bg border border-tv-border rounded px-4 py-3">
            <div class="flex items-center gap-3">
              <span class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold"
                    :class="acct.is_active ? 'bg-tv-blue/20 text-tv-blue' : 'bg-tv-muted/20 text-tv-muted'">
                {{ (acct.account_name || '').charAt(0).toUpperCase() || '?' }}
              </span>
              <div>
                <div class="text-tv-text font-medium">{{ acct.account_name || acct.account_number }}</div>
                <div class="text-tv-muted text-xs">{{ acct.account_number }}<template v-if="acct.account_type && acct.account_type !== 'Unknown'"> · {{ acct.account_type }}</template></div>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <span v-if="syncingAccount === acct.account_number" class="text-tv-blue text-xs">
                <i class="fas fa-sync-alt animate-spin mr-1"></i>Importing...
              </span>
              <label class="relative inline-flex items-center cursor-pointer" @click.prevent="toggleAccount(acct)">
                <span class="w-10 h-5 rounded-full transition-colors"
                      :class="acct.is_active ? 'bg-tv-green' : 'bg-tv-border'"
                      :style="accountsSaving || syncingAccount ? 'opacity: 0.5; pointer-events: none' : ''">
                  <span class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                        :class="acct.is_active ? 'translate-x-5' : ''"></span>
                </span>
              </label>
            </div>
          </div>

          <!-- Continue button (onboarding) -->
          <div v-if="onboarding" class="pt-4">
            <button @click="activeTab = 'import'"
                    class="bg-tv-blue hover:bg-tv-blue/80 text-white px-6 py-2.5 rounded text-sm font-medium transition-colors">
              Continue to Import <i class="fas fa-arrow-right ml-2"></i>
            </button>
          </div>
        </div>
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
                    <i class="fas fa-database mr-2 text-tv-muted"></i>Import Transactions
                  </h3>
                  <p class="text-tv-muted text-sm">Clears the existing database and rebuilds it from scratch. Fetches all transactions from the selected start date.</p>
                </div>
                <button @click="initialSync()" :disabled="initialSyncing"
                        class="flex-shrink-0 ml-6 px-5 py-2.5 rounded text-sm disabled:opacity-50 whitespace-nowrap"
                        :class="onboarding
                          ? 'bg-tv-blue hover:bg-tv-blue/80 text-white'
                          : 'bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30'">
                  <i class="fas fa-database mr-2" :class="{ 'animate-spin': initialSyncing }"></i>
                  Import Transactions
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

        <!-- Sync in progress banner -->
        <div v-if="initialSyncing" class="mt-4 mx-1 p-4 rounded-lg border border-tv-blue/30 bg-tv-blue/10">
          <div class="flex items-center gap-3">
            <i class="fas fa-spinner animate-spin text-tv-blue text-lg"></i>
            <div>
              <p class="text-tv-text font-medium">Importing transactions...</p>
              <p class="text-tv-muted text-sm mt-1">This may take a minute depending on how much history you're importing. You can continue browsing while it runs — your data will appear when the import completes.</p>
            </div>
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
            <i class="fas fa-bell mr-2 text-tv-amber"></i>Roll Suggestion Alerts
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
                { key: 'lateStage', label: 'Late-Stage', desc: 'Alert when multiple maturing indicators converge (low DTE, high delta, etc.)', color: 'bg-tv-amber' },
                { key: 'deltaSaturation', label: 'Delta Saturation', desc: 'Alert when spread delta exceeds 65% (diminishing convexity)', color: 'bg-tv-orange' },
                { key: 'lowRewardToRisk', label: 'Low Reward-to-Risk', desc: 'Alert when remaining reward-to-risk ratio falls below 0.6', color: 'bg-tv-orange' },
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

      <!-- ==================== Tags Tab ==================== -->
      <div v-show="activeTab === 'tags'">
        <div class="mb-6">
          <h2 class="text-xl font-semibold text-tv-text mb-1">
            <i class="fas fa-tags mr-2 text-tv-blue"></i>Tags
          </h2>
          <p class="text-tv-muted text-sm">Manage tags used to organize your position groups</p>
        </div>

        <div class="bg-tv-bg border border-tv-border rounded p-3 text-sm text-tv-muted mb-5">
          <i class="fas fa-info-circle mr-1 text-tv-blue"></i>
          Tags are created from the Ledger or Positions page. Use this section to rename, recolor, or delete existing tags.
        </div>

        <!-- Tag list -->
        <div v-if="tags.length > 0" class="bg-tv-panel border border-tv-border rounded">
          <div v-for="tag in tags" :key="tag.id"
               class="flex items-center gap-3 px-4 py-3 border-b border-tv-border/50 last:border-b-0">

            <!-- View mode -->
            <template v-if="editingTag !== tag.id">
              <span class="w-5 h-5 rounded-full flex-shrink-0 border border-tv-border"
                    :style="{ backgroundColor: tag.color }"></span>
              <span class="text-tv-text text-sm font-medium flex-1">{{ tag.name }}</span>
              <span class="text-tv-muted text-xs bg-tv-bg border border-tv-border rounded px-2 py-0.5">
                {{ tag.group_count }} {{ tag.group_count === 1 ? 'position' : 'positions' }}
              </span>
              <button @click="startEditTag(tag)"
                      class="text-tv-muted hover:text-tv-blue text-sm p-1" title="Edit tag">
                <i class="fas fa-pen"></i>
              </button>
              <button @click="deleteTag(tag)" :disabled="deletingTagId === tag.id"
                      class="text-tv-muted hover:text-tv-red text-sm p-1 disabled:opacity-50" title="Delete tag">
                <i :class="deletingTagId === tag.id ? 'fas fa-spinner fa-spin' : 'fas fa-trash-alt'"></i>
              </button>
            </template>

            <!-- Edit mode -->
            <template v-else>
              <input type="color" v-model="editColor"
                     class="w-7 h-7 rounded cursor-pointer border border-tv-border bg-transparent flex-shrink-0"
                     title="Pick color">
              <input type="text" v-model="editName"
                     class="flex-1 bg-tv-bg border border-tv-border text-tv-text px-3 py-1.5 rounded text-sm focus:outline-none focus:border-tv-blue"
                     @keyup.enter="saveTag()" @keyup.escape="cancelEditTag()">
              <button @click="saveTag()"
                      class="bg-tv-blue hover:bg-tv-blue/80 text-white px-3 py-1.5 rounded text-sm">
                <i class="fas fa-check mr-1"></i>Save
              </button>
              <button @click="cancelEditTag()"
                      class="text-tv-muted hover:text-tv-text border border-tv-border px-3 py-1.5 rounded text-sm">
                Cancel
              </button>
            </template>
          </div>
        </div>

        <!-- Empty state -->
        <div v-else class="bg-tv-panel border border-tv-border rounded p-8 text-center">
          <i class="fas fa-tags text-tv-muted text-3xl mb-3"></i>
          <p class="text-tv-muted text-sm">No tags yet. Create tags from the Ledger or Positions page.</p>
        </div>
      </div>

    </div>
  </div>

  <!-- Import success modal (outside tab wrappers so v-show doesn't hide it) -->
  <div v-if="importResult" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
    <div class="bg-tv-panel border border-tv-border rounded-lg px-8 py-6 text-center shadow-2xl max-w-md">
      <i class="fas fa-check-circle text-tv-green text-4xl mb-4"></i>
      <h3 class="text-tv-text text-lg font-semibold mb-2">Import Complete!</h3>
      <p class="text-tv-muted text-sm mb-4">
        {{ importResult.transactions_processed || 0 }} transactions imported across
        {{ importResult.orders_assembled || 0 }} orders in
        {{ importResult.groups_processed || 0 }} groups.
      </p>
      <p class="text-tv-muted text-sm mb-6">
        Your positions are ready to view with live P&amp;L tracking. Use the Ledger page to explore trade history and roll chains.
      </p>
      <button @click="goToPositions"
              class="bg-tv-blue hover:bg-tv-blue/80 text-white font-medium px-6 py-2 rounded transition-colors">
        Go to Positions
      </button>
    </div>
  </div>

  <ConfirmModal
    :show="confirmShow"
    :title="confirmTitle"
    :message="confirmMessage"
    :confirm-text="confirmBtnText"
    :cancel-text="confirmCancelText"
    :variant="confirmVariant"
    @confirm="onConfirm"
    @cancel="onCancel"
  />
</template>
