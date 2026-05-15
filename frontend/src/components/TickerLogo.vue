<script setup>
import { ref, watch } from 'vue'
import { loadTickerLogo } from '@/composables/useTickerLogo'

const props = defineProps({
  symbol: { type: String, required: true },
  size: { type: Number, default: 28 },
  rounded: { type: Boolean, default: true },
})

const url = ref(null)

watch(() => props.symbol, async (sym) => {
  url.value = null
  if (!sym) return
  const resolved = await loadTickerLogo(sym)
  if (sym === props.symbol) url.value = resolved
}, { immediate: true })
</script>

<template>
  <img v-if="url" :src="url" alt=""
       class="flex-none"
       :class="rounded ? 'rounded' : ''"
       :style="{ width: size + 'px', height: size + 'px' }">
  <div v-else
       class="flex-none bg-tv-border/30"
       :class="rounded ? 'rounded' : ''"
       :style="{ width: size + 'px', height: size + 'px' }"></div>
</template>
