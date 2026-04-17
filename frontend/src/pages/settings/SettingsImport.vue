<script setup>
defineProps({ state: Object, onboarding: Object })
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <i class="fas fa-file-import mr-2 text-tv-blue"></i>Import Trades
      </h2>
      <p class="text-tv-muted text-sm">Rebuild or reprocess your trade data from Tastytrade</p>
    </div>

    <div v-if="onboarding.value" class="bg-tv-green/10 border border-tv-green/30 rounded p-4 mb-5">
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
              <p class="text-tv-muted text-sm">Clears the existing database and rebuilds it from scratch. Imports your full account history automatically.</p>
            </div>
            <button @click="state.initialSync()" :disabled="state.initialSyncing.value"
                    class="flex-shrink-0 ml-6 px-5 py-2.5 rounded text-sm disabled:opacity-50 whitespace-nowrap"
                    :class="onboarding.value
                      ? 'bg-tv-blue hover:bg-tv-blue/80 text-white'
                      : 'bg-tv-red/20 hover:bg-tv-red/30 text-tv-red border border-tv-red/30'">
              <i class="fas fa-database mr-2" :class="{ 'animate-spin': state.initialSyncing.value }"></i>
              Import Transactions
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="state.initialSyncing.value" class="mt-4 mx-1 p-4 rounded-lg border border-tv-blue/30 bg-tv-blue/10">
      <div class="flex items-center gap-3">
        <i class="fas fa-spinner animate-spin text-tv-blue text-lg"></i>
        <div>
          <p class="text-tv-text font-medium">Importing transactions...</p>
          <p class="text-tv-muted text-sm mt-1">This may take a minute depending on how much history you're importing. You can continue browsing while it runs — your data will appear when the import completes.</p>
        </div>
      </div>
    </div>
  </div>
</template>
