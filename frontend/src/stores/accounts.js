import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'

export const useAccountsStore = defineStore('accounts', () => {
  const accounts = ref([])
  const selectedAccount = ref('')
  const loaded = ref(false)

  // Auto-persist selectedAccount to localStorage
  watch(selectedAccount, (val) => {
    localStorage.setItem('trade_journal_selected_account', val)
  })

  // Restore on creation
  const saved = localStorage.getItem('trade_journal_selected_account')
  if (saved !== null) selectedAccount.value = saved

  function getAccountSymbol(accountNumber) {
    const account = accounts.value.find(a => a.account_number === accountNumber)
    if (!account) return '?'
    const name = (account.account_name || '').toUpperCase()
    if (name.includes('ROTH')) return 'R'
    if (name.includes('INDIVIDUAL')) return 'I'
    if (name.includes('TRADITIONAL')) return 'T'
    return name.charAt(0) || '?'
  }

  async function loadAccounts() {
    if (loaded.value) return
    try {
      const Auth = useAuth()
      const response = await Auth.authFetch('/api/accounts')
      const data = await response.json()
      accounts.value = (data.accounts || []).sort((a, b) => {
        const order = (name) => {
          const u = (name || '').toUpperCase()
          if (u.includes('ROTH')) return 1
          if (u.includes('INDIVIDUAL')) return 2
          if (u.includes('TRADITIONAL')) return 3
          return 4
        }
        return order(a.account_name) - order(b.account_name)
      })
      loaded.value = true
    } catch (error) {
      console.error('Error loading accounts:', error)
    }
  }

  return { accounts, selectedAccount, loaded, getAccountSymbol, loadAccounts }
})
