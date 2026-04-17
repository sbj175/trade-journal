<script setup>
defineProps({ state: Object, onboarding: Object })
</script>

<template>
  <div>
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-tv-text mb-1">
          <i class="fas fa-plug mr-2 text-tv-blue"></i>Tastytrade Connection
        </h2>
        <p class="text-tv-muted text-sm">
          {{ state.authEnabled.value ? 'Connect your Tastytrade account with one click' : 'Connect to Tastytrade using OAuth2 credentials' }}
        </p>
      </div>
      <div v-if="state.connectionStatus.value && !onboarding.value" class="flex items-center gap-2">
        <span v-if="state.connectionStatus.value.connected"
              class="bg-tv-green/20 text-tv-green border border-tv-green/30 px-3 py-1 rounded text-xs font-medium">
          <i class="fas fa-check-circle mr-1"></i>Connected
        </span>
        <span v-else-if="state.connectionStatus.value.configured"
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
    <template v-if="state.authEnabled.value">
      <!-- Onboarding welcome panel -->
      <div v-if="onboarding.value && !state.connectionStatus.value?.configured" class="bg-tv-panel border border-tv-blue/30 rounded mb-5">
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
              <input type="checkbox" :checked="state.consentAcknowledged.value" @change="state.toggleConsent()"
                     class="w-4 h-4 rounded border-tv-border bg-tv-bg text-tv-blue focus:ring-tv-blue">
              <span class="text-tv-text text-sm">I understand what data OptionLedger will access and store</span>
            </label>
          </div>
          <button @click="state.connectTastytrade()" :disabled="state.connecting.value || !state.consentAcknowledged.value"
                  class="bg-tv-blue hover:bg-tv-blue/80 text-white px-8 py-3 rounded-lg text-base font-medium disabled:opacity-50 transition-colors">
            <i v-if="!state.connecting.value" class="fas fa-right-to-bracket mr-2"></i>
            <i v-if="state.connecting.value" class="fas fa-spinner fa-spin mr-2"></i>
            {{ state.connecting.value ? 'Redirecting...' : 'Connect to Tastytrade' }}
          </button>
        </div>
      </div>

      <!-- Normal connection panel (returning user or post-onboarding) -->
      <div v-if="!onboarding.value || state.connectionStatus.value?.configured" class="bg-tv-panel border border-tv-border rounded">
        <div class="p-5 space-y-4">
          <div v-if="state.connectionStatus.value?.error" class="bg-tv-red/10 border border-tv-red/20 rounded p-3 text-sm text-tv-red">
            <i class="fas fa-exclamation-triangle mr-1"></i>
            {{ state.connectionStatus.value.error }}
          </div>
          <div v-if="state.connectionStatus.value?.connected && state.connectionStatus.value?.accounts?.length" class="text-sm flex flex-col items-start gap-1.5">
            <span class="text-tv-muted">Accounts:</span>
            <div v-for="acct in state.connectionStatus.value.accounts" :key="acct.account_number"
                 class="inline-flex items-center gap-2 bg-tv-bg border border-tv-border rounded px-3 py-1.5 ml-4">
              <span class="text-tv-text font-medium">{{ acct.account_number }}</span>
              <span class="text-tv-muted">&mdash;</span>
              <span class="text-tv-muted">{{ acct.account_name }}</span>
            </div>
          </div>
          <div v-if="!state.connectionStatus.value?.configured" class="bg-tv-bg border border-tv-border rounded p-3 text-sm">
            <p class="text-tv-muted text-xs mb-2">
              <i class="fas fa-shield-halved mr-1 text-tv-blue"></i>
              OptionLedger will access your account info, transactions, positions, and quotes (read-only).
              Your token is encrypted at rest. Data is never shared with third parties.
              <a href="/privacy" target="_blank" class="text-tv-blue hover:underline ml-1">Learn more</a>
            </p>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" :checked="state.consentAcknowledged.value" @change="state.toggleConsent()"
                     class="w-4 h-4 rounded border-tv-border bg-tv-bg text-tv-blue focus:ring-tv-blue">
              <span class="text-tv-text text-sm">I understand what data OptionLedger will access and store</span>
            </label>
          </div>
          <div class="flex items-center gap-3">
            <button @click="state.connectTastytrade()" :disabled="state.connecting.value || (!state.connectionStatus.value?.configured && !state.consentAcknowledged.value)"
                    class="bg-tv-blue hover:bg-tv-blue/80 text-white px-5 py-2 rounded text-sm disabled:opacity-50">
              <i v-if="!state.connecting.value" class="fas fa-right-to-bracket mr-1"></i>
              <i v-if="state.connecting.value" class="fas fa-spinner fa-spin mr-1"></i>
              {{ state.connecting.value ? 'Redirecting...' : (state.connectionStatus.value?.configured ? 'Reconnect to Tastytrade' : 'Connect to Tastytrade') }}
            </button>
            <button v-if="state.connectionStatus.value?.configured"
                    @click="state.disconnectTastytrade()" :disabled="state.deletingCredentials.value"
                    class="bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30 px-4 py-2 rounded text-sm disabled:opacity-50">
              <i v-if="!state.deletingCredentials.value" class="fas fa-unlink mr-1"></i>
              <i v-if="state.deletingCredentials.value" class="fas fa-spinner fa-spin mr-1"></i>
              {{ state.deletingCredentials.value ? 'Disconnecting...' : 'Disconnect' }}
            </button>
          </div>
          <div class="mt-2">
            <a href="/privacy" target="_blank" class="text-tv-muted hover:text-tv-blue text-xs">
              <i class="fas fa-shield-halved mr-1"></i>Privacy & Data Practices
            </a>
          </div>
        </div>
      </div>
    </template>

    <!-- Auth-disabled mode: manual credential form -->
    <template v-if="!state.authEnabled.value">
      <div class="bg-tv-panel border border-tv-border rounded">
        <div class="p-5 space-y-4">
          <div v-if="state.connectionStatus.value?.error" class="bg-tv-red/10 border border-tv-red/20 rounded p-3 text-sm text-tv-red">
            <i class="fas fa-exclamation-triangle mr-1"></i>
            {{ state.connectionStatus.value.error }}
          </div>
          <div v-if="state.connectionStatus.value?.connected && state.connectionStatus.value?.accounts?.length" class="text-sm flex flex-col items-start gap-1.5">
            <span class="text-tv-muted">Accounts:</span>
            <div v-for="acct in state.connectionStatus.value.accounts" :key="acct.account_number"
                 class="inline-flex items-center gap-2 bg-tv-bg border border-tv-border rounded px-3 py-1.5 ml-4">
              <span class="text-tv-text font-medium">{{ acct.account_number }}</span>
              <span class="text-tv-muted">&mdash;</span>
              <span class="text-tv-muted">{{ acct.account_name }}</span>
            </div>
          </div>
          <div class="space-y-3">
            <div>
              <label class="block text-tv-muted text-sm mb-1">Client Secret <span class="text-tv-muted/50">(saved as provider_secret)</span></label>
              <input type="password" v-model="state.providerSecret.value" placeholder="Enter your Client Secret from Tastytrade"
                     class="ml-4 w-[calc(100%-1rem)] bg-tv-bg border border-tv-border text-tv-text px-3 py-2 rounded text-sm focus:outline-none focus:border-tv-blue">
            </div>
            <div>
              <label class="block text-tv-muted text-sm mb-1">Refresh Token</label>
              <input type="password" v-model="state.refreshToken.value" placeholder="Enter your Refresh Token from Tastytrade"
                     class="ml-4 w-[calc(100%-1rem)] bg-tv-bg border border-tv-border text-tv-text px-3 py-2 rounded text-sm focus:outline-none focus:border-tv-blue">
            </div>
            <div class="flex items-center gap-3 ml-4">
              <button @click="state.saveCredentials()" :disabled="state.savingCredentials.value"
                      class="bg-tv-blue hover:bg-tv-blue/80 text-white px-4 py-2 rounded text-sm disabled:opacity-50">
                <i v-if="!state.savingCredentials.value" class="fas fa-save mr-1"></i>
                <i v-if="state.savingCredentials.value" class="fas fa-spinner fa-spin mr-1"></i>
                {{ state.savingCredentials.value ? 'Connecting...' : 'Save &amp; Connect' }}
              </button>
              <button v-if="state.connectionStatus.value?.configured"
                      @click="state.deleteCredentials()" :disabled="state.deletingCredentials.value"
                      class="bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30 px-4 py-2 rounded text-sm disabled:opacity-50">
                <i v-if="!state.deletingCredentials.value" class="fas fa-trash-alt mr-1"></i>
                <i v-if="state.deletingCredentials.value" class="fas fa-spinner fa-spin mr-1"></i>
                {{ state.deletingCredentials.value ? 'Removing...' : 'Remove Credentials' }}
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
</template>
