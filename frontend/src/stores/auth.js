import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const authEnabled = ref(false)
  const userEmail = ref('')
  const riskPageEnabled = ref(true)
  const initialized = ref(false)

  async function init() {
    if (initialized.value) return

    const Auth = window.Auth
    if (!Auth) return

    authEnabled.value = Auth.isAuthEnabled()
    if (authEnabled.value) {
      const user = await Auth.getUser()
      if (user) userEmail.value = user.email || ''
    }

    try {
      const resp = await fetch('/api/auth/config')
      if (resp.ok) {
        const config = await resp.json()
        if (config.risk_page_enabled !== undefined) {
          riskPageEnabled.value = config.risk_page_enabled
        }
      }
    } catch (_) { /* use default */ }

    initialized.value = true
  }

  function signOut() {
    window.Auth?.signOut()
  }

  return { authEnabled, userEmail, riskPageEnabled, initialized, init, signOut }
})
