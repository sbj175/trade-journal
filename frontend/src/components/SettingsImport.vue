<script setup>
import BaseButton from '@/components/BaseButton.vue'
import BaseIcon from '@/components/BaseIcon.vue'

defineProps({ state: Object, onboarding: Object })
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <BaseIcon name="file-import" class="mr-2 text-tv-blue" />Import Trades
      </h2>
      <p class="text-tv-muted text-sm">Rebuild or reprocess your trade data from Tastytrade</p>
    </div>

    <div v-if="onboarding.value" class="bg-tv-green/10 border border-tv-green/30 rounded p-4 mb-5">
      <div class="flex items-start gap-3">
        <BaseIcon name="check-circle" class="text-tv-green text-lg mt-0.5" />
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
                <BaseIcon name="database" class="mr-2 text-tv-muted" />Import Transactions
              </h3>
              <p class="text-tv-muted text-sm">Clears the existing database and rebuilds it from scratch. Imports your full account history automatically.</p>
            </div>
            <BaseButton :variant="onboarding.value ? 'primary' : 'danger'" size="lg" @click="state.initialSync()" :disabled="state.initialSyncing.value" :loading="state.initialSyncing.value" class="flex-shrink-0 ml-6 whitespace-nowrap">
              <template #icon><BaseIcon name="database" /></template>
              Import Transactions
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

    <div v-if="state.initialSyncing.value" class="mt-4 mx-1 p-4 rounded-lg border border-tv-blue/30 bg-tv-blue/10">
      <div class="flex items-center gap-3">
        <BaseIcon name="spinner" :spin="true" class="text-tv-blue text-lg" />
        <div>
          <p class="text-tv-text font-medium">Importing transactions...</p>
          <p class="text-tv-muted text-sm mt-1">This may take a minute depending on how much history you're importing. You can continue browsing while it runs — your data will appear when the import completes.</p>
        </div>
      </div>
    </div>
  </div>
</template>
