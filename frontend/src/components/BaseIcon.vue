<script setup>
defineProps({
  name:       { type: String,  required: true },
  size:       { type: String,  default: null },   // xs | sm | md | lg | xl — null inherits from parent
  spin:       { type: Boolean, default: false },
  fixedWidth: { type: Boolean, default: false },  // fa-fw for list alignment
})

const sizeMap = {
  xs: 'text-xs',
  sm: 'text-sm',
  md: 'text-base',
  lg: 'text-lg',
  xl: 'text-xl',
}
</script>

<template>
  <i
    :class="[
      'fas',
      'fa-' + name,
      size ? sizeMap[size] : null,
      spin       && 'animate-spin',
      fixedWidth && 'fa-fw',
    ]"
  />
</template>
