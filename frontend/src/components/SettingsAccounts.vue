<script setup>
defineProps({ state: Object, onboarding: Object })
defineEmits(['go-to-import'])
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <i class="fas fa-university mr-2 text-tv-blue"></i>Accounts
      </h2>
      <p class="text-tv-muted text-sm">Choose which Tastytrade accounts to sync. Disabled accounts will not be imported during sync.</p>
    </div>

    <div v-if="onboarding.value" class="bg-tv-green/10 border border-tv-green/30 rounded p-4 mb-5">
      <div class="flex items-start gap-3">
        <i class="fas fa-check-circle text-tv-green text-lg mt-0.5"></i>
        <div>
          <p class="text-tv-text font-medium">Your Tastytrade account is connected!</p>
          <p class="text-tv-muted text-sm mt-1">We found the accounts below. Toggle off any you don't want to sync, then continue to import your trades.</p>
        </div>
      </div>
    </div>

    <div v-if="state.allAccounts.value.length === 0" class="text-tv-muted text-sm py-8 text-center">
      <i class="fas fa-info-circle mr-1"></i>No accounts found. Connect to Tastytrade first.
    </div>

    <div v-else class="space-y-2">
      <div v-for="acct in state.allAccounts.value" :key="acct.account_number"
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
          <span v-if="state.syncingAccount.value === acct.account_number" class="text-tv-blue text-xs">
            <i class="fas fa-sync-alt animate-spin mr-1"></i>Importing...
          </span>
          <label class="relative inline-flex items-center cursor-pointer" @click.prevent="state.toggleAccount(acct)">
            <span class="w-10 h-5 rounded-full transition-colors"
                  :class="acct.is_active ? 'bg-tv-green' : 'bg-tv-border'"
                  :style="state.accountsSaving.value || state.syncingAccount.value ? 'opacity: 0.5; pointer-events: none' : ''">
              <span class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                    :class="acct.is_active ? 'translate-x-5' : ''"></span>
            </span>
          </label>
        </div>
      </div>

      <div v-if="onboarding.value" class="pt-4">
        <button @click="$emit('go-to-import')"
                class="bg-tv-blue hover:bg-tv-blue/80 text-white px-6 py-2.5 rounded text-sm font-medium transition-colors">
          Continue to Import <i class="fas fa-arrow-right ml-2"></i>
        </button>
      </div>
    </div>
  </div>
</template>
