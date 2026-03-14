/**
 * Connection status, OAuth flow, and manual credential management.
 */
import { ref } from 'vue'

export function useSettingsConnection(Auth, { showNotification }) {
  // Connection state
  const connectionStatus = ref(null)
  const providerSecret = ref('')
  const refreshToken = ref('')
  const savingCredentials = ref(false)
  const deletingCredentials = ref(false)

  // OAuth flow state
  const onboarding = ref(false)
  const authEnabled = ref(false)
  const connecting = ref(false)

  // Data consent
  const consentAcknowledged = ref(false)

  async function checkConnection() {
    try {
      const resp = await Auth.authFetch('/api/connection/status')
      if (resp.ok) {
        connectionStatus.value = await resp.json()
      }
    } catch (e) {
      connectionStatus.value = { connected: false, configured: false, error: 'Could not check connection status' }
    }
  }

  async function connectTastytrade() {
    connecting.value = true
    try {
      const resp = await Auth.authFetch('/api/auth/tastytrade/authorize', { method: 'POST' })
      if (resp.ok) {
        const data = await resp.json()
        window.location.href = data.authorization_url
        return
      }
      const err = await resp.json().catch(() => ({}))
      showNotification(err.detail || 'Failed to start Tastytrade connection', 'error')
    } catch (e) {
      showNotification('Error: ' + e.message, 'error')
    }
    connecting.value = false
  }

  async function disconnectTastytrade() {
    if (!confirm('Disconnect your Tastytrade account? You will need to reconnect to sync trades.')) return
    deletingCredentials.value = true
    try {
      const resp = await Auth.authFetch('/api/auth/tastytrade/disconnect', { method: 'POST' })
      if (resp.ok) {
        showNotification('Tastytrade disconnected', 'success')
        await checkConnection()
      } else {
        const data = await resp.json().catch(() => ({}))
        showNotification(data.detail || 'Failed to disconnect', 'error')
      }
    } catch (e) {
      showNotification('Error: ' + e.message, 'error')
    }
    deletingCredentials.value = false
  }

  async function saveCredentials() {
    if (!providerSecret.value || !refreshToken.value) {
      showNotification('Please fill in both fields', 'error')
      return
    }
    savingCredentials.value = true
    try {
      const saveResp = await Auth.authFetch('/api/settings/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_secret: providerSecret.value,
          refresh_token: refreshToken.value,
        }),
      })
      if (!saveResp.ok) {
        showNotification('Failed to save credentials', 'error')
        savingCredentials.value = false
        return
      }

      const reconnResp = await Auth.authFetch('/api/connection/reconnect', { method: 'POST' })
      if (reconnResp.ok) {
        connectionStatus.value = await reconnResp.json()
        if (connectionStatus.value.connected) {
          showNotification('Connected to Tastytrade successfully!', 'success')
          providerSecret.value = ''
          refreshToken.value = ''
        } else {
          showNotification('Credentials saved but connection failed: ' + (connectionStatus.value.error || 'Unknown error'), 'error')
        }
      } else {
        showNotification('Failed to reconnect', 'error')
      }
    } catch (e) {
      showNotification('Error saving credentials: ' + e.message, 'error')
    }
    savingCredentials.value = false
  }

  async function deleteCredentials() {
    if (!confirm('Remove your Tastytrade credentials? You will need to re-enter them to sync.')) return
    deletingCredentials.value = true
    try {
      const resp = await Auth.authFetch('/api/settings/credentials', { method: 'DELETE' })
      if (resp.ok) {
        showNotification('Credentials removed', 'success')
        await checkConnection()
      } else {
        const data = await resp.json().catch(() => ({}))
        showNotification(data.detail || 'Failed to remove credentials', 'error')
      }
    } catch (e) {
      showNotification('Error removing credentials: ' + e.message, 'error')
    }
    deletingCredentials.value = false
  }

  function toggleConsent() {
    consentAcknowledged.value = !consentAcknowledged.value
    if (consentAcknowledged.value) {
      localStorage.setItem('dataConsentAcknowledged', 'true')
    } else {
      localStorage.removeItem('dataConsentAcknowledged')
    }
  }

  return {
    // State
    connectionStatus,
    providerSecret,
    refreshToken,
    savingCredentials,
    deletingCredentials,
    onboarding,
    authEnabled,
    connecting,
    consentAcknowledged,
    // Methods
    checkConnection,
    connectTastytrade,
    disconnectTastytrade,
    saveCredentials,
    deleteCredentials,
    toggleConsent,
  }
}
