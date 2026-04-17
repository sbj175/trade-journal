<script setup>
defineProps({ state: Object })
</script>

<template>
  <div>
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-tv-text mb-1">
          <i class="fas fa-bullseye mr-2 text-tv-blue"></i>Strategy Targets
        </h2>
        <p class="text-tv-muted text-sm">Configure profit and loss targets for each strategy type</p>
      </div>
      <button @click="state.resetToDefaults()"
              class="bg-tv-bg hover:bg-tv-border text-tv-muted hover:text-tv-text border border-tv-border px-4 py-2 text-sm rounded">
        <i class="fas fa-rotate-left mr-1"></i>Reset to Defaults
      </button>
    </div>

    <template v-for="category in [
      { key: 'credit', label: 'Credit Strategies', desc: 'Strategies where you collect premium upfront', icon: 'fa-arrow-down', color: 'text-tv-green', items: state.creditStrategies.value },
      { key: 'debit', label: 'Debit Strategies', desc: 'Strategies where you pay premium upfront', icon: 'fa-arrow-up', color: 'text-tv-blue', items: state.debitStrategies.value },
      { key: 'mixed', label: 'Mixed Strategies', desc: 'Strategies combining credit and debit components', icon: 'fa-exchange-alt', color: 'text-tv-muted', items: state.mixedStrategies.value },
      { key: 'equity', label: 'Equity', desc: 'Stock/share positions', icon: 'fa-chart-bar', color: 'text-tv-muted', items: state.equityStrategies.value },
    ]" :key="category.key">
      <div v-if="category.items.length > 0"
           class="bg-tv-panel border border-tv-border rounded mb-5" @input="state.debouncedSaveTargets()">
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
</template>
