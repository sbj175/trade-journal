<script setup>
// Solid cyan pill indicating N same-expiration rolls have occurred within
// the group. Informational only (not independently clickable). Renders
// nothing when count is zero.
defineProps({
  count:   { type: Number, required: true },
  size:    { type: String, default: 'md' },  // 'sm' for mobile cards, 'md' elsewhere
})
</script>

<template>
  <span
    v-if="count > 0"
    class="rounded-full bg-tv-cyan text-tv-bg font-medium leading-4 inline-flex items-center gap-0.5"
    :class="size === 'sm'
      ? 'text-[10px] px-2 py-0.5'
      : 'text-[11px] px-2.5 py-1 gap-1'"
    :title="`${count} same-expiration roll${count === 1 ? '' : 's'} — expand to see details`">
    <i class="fas fa-rotate text-[9px]"></i>{{ count }}
  </span>
</template>
