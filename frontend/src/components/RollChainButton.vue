<script setup>
// Solid blue pill button for different-expiration roll chains — clicking
// opens the RollChainModal. Renders nothing when hasChain is false.
// When chainRollCount is provided, displays "🔗 N rolls"; otherwise icon-only.
defineProps({
  hasChain:       { type: Boolean, default: false },
  chainRollCount: { type: [Number, null], default: null },
  size:           { type: String, default: 'md' },  // 'sm' for mobile cards, 'md' elsewhere
})
defineEmits(['click'])
</script>

<template>
  <button
    v-if="hasChain"
    type="button"
    class="rounded-full bg-tv-blue text-white hover:bg-tv-blue/80 cursor-pointer font-medium leading-4 transition-colors inline-flex items-center gap-1"
    :class="size === 'sm'
      ? 'text-[10px] px-2 py-0.5 gap-0.5'
      : 'text-[11px] px-2.5 py-1'"
    title="Different-expiration roll chain — click for details"
    @click.stop="$emit('click')">
    <i class="fas fa-link text-[9px]"></i><span v-if="chainRollCount != null">{{ chainRollCount }} roll{{ chainRollCount === 1 ? '' : 's' }}</span>
  </button>
</template>
