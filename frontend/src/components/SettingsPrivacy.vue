<script setup>
import BaseIcon from '@/components/BaseIcon.vue'

defineProps({ state: Object })
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <BaseIcon name="eye-slash" class="mr-2 text-tv-muted" />Privacy Mode
      </h2>
      <p class="text-tv-muted text-sm">Hide sensitive account balance information on the Positions page</p>
    </div>
    <div class="bg-tv-panel border border-tv-border rounded">
      <div class="p-5">
        <div class="flex items-center gap-4">
          <label v-for="option in [
            { value: 'off', label: 'Off', icon: 'eye', desc: 'All values visible' },
            { value: 'medium', label: 'Medium', icon: 'eye-low-vision', desc: 'Hides Net Liq' },
            { value: 'high', label: 'High', icon: 'eye-slash', desc: 'Hides all balances' },
          ]" :key="option.value" class="flex-1 cursor-pointer">
            <input type="radio" name="privacyMode" :value="option.value"
                   v-model="state.privacyMode.value" @change="state.savePrivacyMode()" class="sr-only">
            <div class="border rounded p-4 text-center transition-colors"
                 :class="state.privacyMode.value === option.value
                   ? 'border-tv-blue bg-tv-blue/10 text-tv-text'
                   : 'border-tv-border bg-tv-bg text-tv-muted hover:border-tv-muted'">
              <BaseIcon :name="option.icon" class="text-2xl mb-2 block" />
              <div class="text-sm font-medium">{{ option.label }}</div>
              <div class="text-xs mt-1 opacity-70">{{ option.desc }}</div>
            </div>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
