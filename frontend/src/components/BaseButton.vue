<script setup>
import BaseIcon from '@/components/BaseIcon.vue'

defineProps({
  variant:  { type: String,  default: 'secondary' }, // primary | secondary | ghost | danger | success
  size:     { type: String,  default: 'md' },         // sm | md | lg
  type:     { type: String,  default: 'button' },
  disabled: { type: Boolean, default: false },
  loading:  { type: Boolean, default: false },
  icon:     { type: String,  default: null },          // FA icon name (shorthand — no slot needed)
  tag:      { type: String,  default: 'button' },      // override element (e.g. 'a')
})

const sizes = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-3 py-1.5 text-sm',
  lg: 'px-4 py-2 text-base',
}

const variants = {
  primary:   'bg-tv-blue hover:bg-tv-blue/80 text-white border border-tv-blue',
  secondary: 'bg-tv-bg border border-tv-border text-tv-text hover:bg-tv-border/30',
  ghost:     'text-tv-muted hover:text-tv-text border border-transparent',
  danger:    'bg-tv-red/20 text-tv-red border border-tv-red/30 hover:bg-tv-red/30',
  success:   'bg-tv-green hover:bg-tv-green/80 text-tv-bg border border-tv-green font-bold',
}
</script>

<template>
  <component
    :is="tag"
    :type="tag === 'button' ? type : undefined"
    :disabled="disabled || loading"
    class="inline-flex items-center gap-1.5 rounded font-medium transition-colors
           disabled:opacity-50 disabled:cursor-not-allowed"
    :class="[sizes[size], variants[variant]]"
  >
    <!--
      Icon slot — renders to the left of label content.
      Priority: loading spinner > #icon slot > icon prop.
    -->
    <template v-if="loading">
      <BaseIcon name="spinner" :spin="true" />
    </template>
    <template v-else>
      <slot name="icon">
        <BaseIcon v-if="icon" :name="icon" />
      </slot>
    </template>

    <!-- Label / default content -->
    <slot />
  </component>
</template>
