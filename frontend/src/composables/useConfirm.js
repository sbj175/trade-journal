import { ref } from 'vue'

const show = ref(false)
const title = ref('Confirm')
const message = ref('')
const confirmText = ref('Continue')
const cancelText = ref('Cancel')
const variant = ref('default')

let resolvePromise = null

function confirm(options = {}) {
  title.value = options.title || 'Confirm'
  message.value = options.message || ''
  confirmText.value = options.confirmText || 'Continue'
  cancelText.value = options.cancelText || 'Cancel'
  variant.value = options.variant || 'default'
  show.value = true

  return new Promise((resolve) => {
    resolvePromise = resolve
  })
}

function onConfirm() {
  show.value = false
  if (resolvePromise) resolvePromise(true)
  resolvePromise = null
}

function onCancel() {
  show.value = false
  if (resolvePromise) resolvePromise(false)
  resolvePromise = null
}

export function useConfirm() {
  return {
    show, title, message, confirmText, cancelText, variant,
    confirm, onConfirm, onCancel,
  }
}
