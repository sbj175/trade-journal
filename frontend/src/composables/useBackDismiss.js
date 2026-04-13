import { watch, onUnmounted } from 'vue'

/**
 * Dismiss a popup/modal when the user presses the mobile back button/gesture
 * instead of navigating the router.
 *
 * Pushes a temporary history entry when `isOpen` becomes true, listens for
 * popstate to call `close()`, and cleans up the pushed entry when the popup
 * is closed by other means (click outside, escape, selecting an option).
 */
export function useBackDismiss(isOpen, close) {
  let pushed = false
  let dismissingViaPop = false

  function onPopState() {
    if (pushed && isOpen.value) {
      dismissingViaPop = true
      pushed = false
      window.removeEventListener('popstate', onPopState)
      close()
    }
  }

  watch(isOpen, (open) => {
    if (open && !pushed) {
      history.pushState({ __dismiss: true }, '')
      pushed = true
      window.addEventListener('popstate', onPopState)
    } else if (!open && pushed) {
      window.removeEventListener('popstate', onPopState)
      pushed = false
      if (!dismissingViaPop) {
        history.back()
      }
      dismissingViaPop = false
    }
  })

  onUnmounted(() => {
    if (pushed) {
      window.removeEventListener('popstate', onPopState)
      pushed = false
      if (!dismissingViaPop) history.back()
    }
  })
}
