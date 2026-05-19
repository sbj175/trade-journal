<script setup>
import { ref, watch, onMounted } from 'vue'
import BaseIcon from '@/components/BaseIcon.vue'

const colorblindPalette = ref(false)

onMounted(() => {
  colorblindPalette.value = localStorage.getItem('colorblindPalette') === 'true'
})

watch(colorblindPalette, (on) => {
  localStorage.setItem('colorblindPalette', on ? 'true' : 'false')
  document.documentElement.classList.toggle('cvd', on)
})
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <BaseIcon name="cog" class="mr-2 text-tv-muted" />General
      </h2>
      <p class="text-tv-muted text-sm">Display preferences that affect the whole app.</p>
    </div>

    <div class="bg-tv-panel border border-tv-border rounded">
      <div class="p-5 space-y-5">
        <div>
          <div class="text-sm font-semibold text-tv-text mb-1">Color vision</div>
          <p class="text-tv-muted text-xs mb-3 max-w-prose">
            Standard palette uses a saturated green / red. The colorblind-friendly option
            uses the Okabe-Ito palette, which shifts green toward cyan and red toward
            orange so up/down indicators remain distinguishable for red-green color
            vision deficiencies. Green = up and red = down semantics are preserved.
          </p>

          <label class="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              v-model="colorblindPalette"
              class="mt-1 h-4 w-4 accent-tv-blue cursor-pointer"
            />
            <span class="text-sm">
              <span class="text-tv-text font-medium">Use colorblind-friendly palette (Okabe-Ito)</span>
              <span class="block text-tv-muted text-xs mt-0.5">
                Applies to both light and dark themes. Other accent colors are unchanged.
              </span>
            </span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
