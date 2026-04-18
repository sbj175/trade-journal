<script setup>
defineProps({ state: Object })
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <i class="fas fa-bell mr-2 text-tv-amber"></i>Roll Suggestion Alerts
      </h2>
      <p class="text-tv-muted text-sm">Configure which roll/close suggestions appear on the Positions page for debit spreads</p>
    </div>
    <div class="bg-tv-panel border border-tv-border rounded" @change="state.saveRollAlerts()">
      <div class="p-5 space-y-3">
        <label class="flex items-center justify-between py-2 border-b border-tv-border/50 cursor-pointer">
          <div>
            <span class="text-tv-text font-medium">Enable Roll Suggestions</span>
            <span class="text-tv-muted text-xs block">Master toggle for all roll analysis badges and panels</span>
          </div>
          <div class="relative">
            <input type="checkbox" v-model="state.rollAlerts.value.enabled" class="sr-only">
            <div class="w-10 h-5 rounded-full transition-colors"
                 :class="state.rollAlerts.value.enabled ? 'bg-tv-blue' : 'bg-tv-border'"></div>
            <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform"
                 :class="state.rollAlerts.value.enabled ? 'translate-x-5' : ''"></div>
          </div>
        </label>

        <div class="space-y-2 pl-2" :class="{ 'opacity-40 pointer-events-none': !state.rollAlerts.value.enabled }">
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
              <input type="checkbox" v-model="state.rollAlerts.value[alert.key]" class="sr-only">
              <div class="w-10 h-5 rounded-full transition-colors"
                   :class="state.rollAlerts.value[alert.key] ? alert.color : 'bg-tv-border'"></div>
              <div class="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform"
                   :class="state.rollAlerts.value[alert.key] ? 'translate-x-5' : ''"></div>
            </div>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
