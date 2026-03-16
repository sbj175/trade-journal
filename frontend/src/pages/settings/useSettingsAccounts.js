import { ref } from 'vue'
import { useAccountsStore } from '@/stores/accounts'
import { useConfirm } from '@/composables/useConfirm'

function sortAccounts(accounts) {
  return [...accounts].sort((a, b) => (a.account_name || '').localeCompare(b.account_name || ''))
}

export function useSettingsAccounts(Auth, { showNotification, onboarding }) {
  const accountsStore = useAccountsStore()
  const { confirm } = useConfirm()
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
    const name = acct.account_name || acct.account_number

    // Prevent disabling the last active account
    const activeCount = allAccounts.value.filter(a => a.is_active).length
    if (!newActive && activeCount <= 1) {
      showNotification('At least one account must remain active', 'error')
      return
    }

    // During onboarding, no confirmations needed (no data exists yet)
    if (!onboarding.value) {
      if (newActive) {
        const ok = await confirm({
          title: 'Enable Account',
          message: `Enable "${name}" and import its transaction history? This may take a moment.`,
          confirmText: 'Enable & Import',
          variant: 'default',
        })
        if (!ok) return
      } else {
        const ok = await confirm({
          title: 'Disable Account',
          message: `Disable "${name}" and delete its local data? This removes all imported transactions, positions, and groups for this account. Your brokerage account is not affected.`,
          confirmText: 'Disable & Delete',
          variant: 'danger',
        })
        if (!ok) return
      }
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

        // Update the global accounts store directly with active accounts
        const activeAccounts = (data.accounts || []).filter(a => a.is_active)
        accountsStore.accounts = activeAccounts.sort((a, b) => {
          const order = (name) => {
            const u = (name || '').toUpperCase()
            if (u.includes('ROTH')) return 1
            if (u.includes('INDIVIDUAL')) return 2
            if (u.includes('TRADITIONAL')) return 3
            return 4
          }
          return order(a.account_name) - order(b.account_name)
        })
        // Reset selection if current account was disabled
        if (accountsStore.selectedAccount && !activeAccounts.find(a => a.account_number === accountsStore.selectedAccount)) {
          accountsStore.selectedAccount = activeAccounts.length === 1 ? activeAccounts[0].account_number : ''
        }

        if (onboarding.value) {
          // During onboarding: just toggle, no import/delete
          showNotification(`${name} ${newActive ? 'enabled' : 'disabled'}`, 'success')
        } else if (newActive) {
          showNotification(`${name} enabled — importing transactions...`, 'success')
          await syncAccount(acct.account_number, name)
        } else {
          // Delete local data for the disabled account
          await deleteAccountData(acct.account_number, name)
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

  async function deleteAccountData(accountNumber, accountName) {
    try {
      const resp = await Auth.authFetch(`/api/settings/accounts/${accountNumber}/data`, { method: 'DELETE' })
      if (resp.ok) {
        showNotification(`${accountName || accountNumber} disabled — local data deleted`, 'success')
      } else {
        showNotification(`Failed to delete data for ${accountName || accountNumber}`, 'error')
      }
    } catch (err) {
      showNotification(`Failed to delete data for ${accountName || accountNumber}`, 'error')
    }
  }

  return { allAccounts, accountsSaving, syncingAccount, loadAllAccounts, toggleAccount }
}
