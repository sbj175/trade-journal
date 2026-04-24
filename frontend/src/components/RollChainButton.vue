<script setup>
// Solid blue pill button for different-expiration roll chains — clicking
// opens the RollChainModal. Renders nothing when hasChain is false.
// Compact mode shows just the icon + count ("🔗 7"); default shows
// "🔗 7 rolls". Use compact in narrow columns (e.g. Ledger Rolls col).
defineProps({
  hasChain:       { type: Boolean, default: false },
  chainRollCount: { type: [Number, null], default: null },
  size:           { type: String, default: 'md' },   // 'sm' for mobile cards, 'md' elsewhere
  compact:        { type: Boolean, default: false }, // hide "roll(s)" word in tight spaces
})
defineEmits(['click'])
</script>

<template>
  <button
    v-if="hasChain"
    type="button"
    class="rounded-full bg-tv-blue text-white hover:bg-tv-blue/80 cursor-pointer font-medium leading-4 transition-colors inline-flex items-center gap-1 whitespace-nowrap"
    :class="size === 'sm'
      ? 'text-[10px] px-2 py-0.5 gap-0.5'
      : 'text-[11px] px-2.5 py-1'"
    title="Different-expiration roll chain — click for details"
    @click.stop="$emit('click')">
    <i class="fas fa-link text-[9px]"></i>
    <span v-if="chainRollCount != null">{{ chainRollCount }}<template v-if="!compact"> roll{{ chainRollCount === 1 ? '' : 's' }}</template></span>
  </button>
</template>
