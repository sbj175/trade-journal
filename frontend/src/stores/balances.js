import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useAccountsStore } from './accounts'

export const useBalancesStore = defineStore('balances', () => {
  const accountBalances = ref({})
  const privacyMode = ref(localStorage.getItem('privacyMode') || 'off')

  const currentAccountBalance = computed(() => {
    const accountsStore = useAccountsStore()
    const selected = accountsStore.selectedAccount
    if (!selected || selected === '') {
      const values = Object.values(accountBalances.value)
      if (values.length === 0) return null
      return values.reduce((acc, balance) => ({
        cash_balance: (acc.cash_balance || 0) + (balance.cash_balance || 0),
        derivative_buying_power: (acc.derivative_buying_power || 0) + (balance.derivative_buying_power || 0),
        equity_buying_power: (acc.equity_buying_power || 0) + (balance.equity_buying_power || 0),
        net_liquidating_value: (acc.net_liquidating_value || 0) + (balance.net_liquidating_value || 0),
      }), { cash_balance: 0, derivative_buying_power: 0, equity_buying_power: 0, net_liquidating_value: 0 })
    }
    return accountBalances.value[selected] || null
  })

  async function loadAccountBalances() {
    try {
      const Auth = useAuth()
      const response = await Auth.authFetch('/api/account-balances')
      const data = await response.json()
      const balances = data.balances || data
      const newBalances = {}
      if (Array.isArray(balances)) {
        balances.forEach(balance => { newBalances[balance.account_number] = balance })
      }
      accountBalances.value = newBalances
    } catch (err) {
      console.error('Failed to load account balances:', err)
    }
  }

  return { accountBalances, privacyMode, currentAccountBalance, loadAccountBalances }
})
