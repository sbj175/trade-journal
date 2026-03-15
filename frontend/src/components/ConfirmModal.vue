<script setup>
defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: 'Confirm' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: 'Continue' },
  cancelText: { type: String, default: 'Cancel' },
  variant: { type: String, default: 'default' }, // 'default' | 'danger'
})

defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="fixed inset-0 z-[100] flex items-center justify-center">
      <div class="absolute inset-0 bg-black/60" @click="$emit('cancel')"></div>
      <div class="relative bg-tv-panel border border-tv-border rounded-lg shadow-2xl w-full max-w-md mx-4">
        <div class="px-5 py-4 border-b border-tv-border/50">
          <span class="text-tv-text font-semibold text-lg">{{ title }}</span>
        </div>
        <div class="px-5 py-4">
          <p class="text-sm text-tv-muted whitespace-pre-line">{{ message }}</p>
        </div>
        <div class="px-5 py-3 border-t border-tv-border/50 flex items-center justify-end gap-3">
          <button @click="$emit('cancel')"
                  class="px-4 py-2 text-sm text-tv-muted hover:text-tv-text border border-tv-border rounded hover:bg-tv-border/30 transition-colors">
            {{ cancelText }}
          </button>
          <button @click="$emit('confirm')"
                  class="px-4 py-2 text-sm font-medium rounded transition-colors"
                  :class="variant === 'danger'
                    ? 'bg-tv-red/20 text-tv-red border border-tv-red/30 hover:bg-tv-red/30'
                    : 'bg-tv-blue/20 text-tv-blue border border-tv-blue/30 hover:bg-tv-blue/30'">
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
