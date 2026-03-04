<script setup>
import { onMounted } from 'vue'
import { useAccountsStore } from '@/stores/accounts'

const emit = defineEmits(['change'])
const accountsStore = useAccountsStore()

function onAccountChange() {
  accountsStore.persistSelection()
  emit('change')
}

onMounted(async () => {
  await accountsStore.loadAccounts()
  accountsStore.restoreSelection()
})
</script>

<template>
  <select v-model="accountsStore.selectedAccount" @change="onAccountChange()"
          class="bg-tv-bg border border-tv-border text-tv-text text-sm px-3 py-1.5 rounded">
    <option value="">All Accounts</option>
    <option v-for="account in accountsStore.accounts" :key="account.account_number"
            :value="account.account_number">
      ({{ accountsStore.getAccountSymbol(account.account_number) }}) {{ account.account_name || account.account_number }}
    </option>
  </select>
</template>
