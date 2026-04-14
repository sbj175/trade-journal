<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useBackDismiss } from '@/composables/useBackDismiss'

const open = ref(false)
const wrapperRef = ref(null)
const popoverStyle = ref({})

async function toggle(e) {
  e?.stopPropagation()
  if (open.value) {
    open.value = false
    return
  }
  open.value = true
  await nextTick()
  positionPopover()
}
function close() { open.value = false }

function positionPopover() {
  const btn = wrapperRef.value?.querySelector('button')
  if (!btn) return
  const r = btn.getBoundingClientRect()
  const margin = 8
  const popWidth = Math.min(280, window.innerWidth - margin * 2)
  // Default: place below the icon, horizontally aligned to the icon center
  let left = r.left + r.width / 2 - popWidth / 2
  // Clamp to viewport
  left = Math.max(margin, Math.min(left, window.innerWidth - popWidth - margin))
  const top = r.bottom + 6
  popoverStyle.value = {
    position: 'fixed',
    top: `${top}px`,
    left: `${left}px`,
    width: `${popWidth}px`,
  }
}

function onDocClick(e) {
  if (open.value && wrapperRef.value && !wrapperRef.value.contains(e.target)) {
    open.value = false
  }
}
function onResize() { if (open.value) positionPopover() }
onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('resize', onResize)
  window.addEventListener('scroll', onResize, true)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('scroll', onResize, true)
})

useBackDismiss(open, close)
</script>

<template>
  <span ref="wrapperRef" class="inline-block align-middle">
    <button @click="toggle" type="button"
            class="text-tv-muted hover:text-tv-blue active:text-tv-blue inline-flex items-center justify-center w-4 h-4 leading-none"
            aria-label="More info">
      <i class="fas fa-info-circle text-[11px]"></i>
    </button>
    <Teleport to="body">
      <div v-if="open"
           @click.stop
           :style="popoverStyle"
           class="z-[9999] bg-tv-panel border border-tv-border rounded-lg shadow-xl p-3 text-xs text-tv-text leading-snug normal-case tracking-normal font-normal whitespace-normal">
        <slot />
      </div>
    </Teleport>
  </span>
</template>
