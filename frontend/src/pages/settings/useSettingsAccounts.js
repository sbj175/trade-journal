import { ref } from 'vue'

function sortAccounts(accounts) {
  return [...accounts].sort((a, b) => (a.account_name || '').localeCompare(b.account_name || ''))
}

export function useSettingsAccounts(Auth, { showNotification }) {
  const allAccounts = ref([])
  const accountsSaving = ref(false)
  const syncingAccount = ref(null)

  async function loadAllAccounts() {
    try {
      const resp = await Auth.authFetch('/api/settings/accounts')
      if (resp.ok) {
        const data = await resp.json()
        allAccounts.value = sortAccounts(data.accounts || [])
      }
    } catch (err) {
      console.error('Failed to load accounts:', err)
    }
  }

  async function toggleAccount(acct) {
    const newActive = !acct.is_active

    // Prevent disabling the last active account
    const activeCount = allAccounts.value.filter(a => a.is_active).length
    if (!newActive && activeCount <= 1) {
      showNotification('At least one account must remain active', 'error')
      return
    }

    accountsSaving.value = true
    try {
      const resp = await Auth.authFetch('/api/settings/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([{ account_number: acct.account_number, is_active: newActive }]),
      })
      if (resp.ok) {
        const data = await resp.json()
        allAccounts.value = sortAccounts(data.accounts || [])

        if (newActive) {
          // Enabling an account — import its historical data
          showNotification(`${acct.account_name || acct.account_number} enabled — importing transactions...`, 'success')
          await syncAccount(acct.account_number, acct.account_name)
        } else {
          showNotification(`${acct.account_name || acct.account_number} disabled`, 'success')
        }
      } else {
        const err = await resp.json()
        showNotification(err.detail || 'Failed to update account', 'error')
      }
    } catch (err) {
      showNotification('Failed to update account', 'error')
    } finally {
      accountsSaving.value = false
    }
  }

  async function syncAccount(accountNumber, accountName) {
    syncingAccount.value = accountNumber
    try {
      const resp = await Auth.authFetch(`/api/sync/account/${accountNumber}`, { method: 'POST' })
      if (resp.ok) {
        const data = await resp.json()
        const n = data.new_transactions || 0
        showNotification(
          n > 0
            ? `Imported ${n} transactions for ${accountName || accountNumber}`
            : `No new transactions for ${accountName || accountNumber}`,
          'success',
        )
      } else {
        showNotification(`Failed to import ${accountName || accountNumber}`, 'error')
      }
    } catch (err) {
      showNotification(`Failed to import ${accountName || accountNumber}`, 'error')
    } finally {
      syncingAccount.value = null
    }
  }

  return { allAccounts, accountsSaving, syncingAccount, loadAllAccounts, toggleAccount }
}
