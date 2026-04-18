<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useConfirm } from '@/composables/useConfirm'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { useSettingsConnection } from '@/composables/useSettingsConnection'
import { useSettingsAccounts } from '@/composables/useSettingsAccounts'
import { useSettingsTargets } from '@/composables/useSettingsTargets'
import { useSettingsTags } from '@/composables/useSettingsTags'
import { useSettingsSync } from '@/composables/useSettingsSync'
import { useSettingsPreferences } from '@/composables/useSettingsPreferences'
import SettingsConnection from '@/components/SettingsConnection.vue'
import SettingsAccounts from '@/components/SettingsAccounts.vue'
import SettingsImport from '@/components/SettingsImport.vue'
import SettingsPrivacy from '@/components/SettingsPrivacy.vue'
import SettingsTargets from '@/components/SettingsTargets.vue'
import SettingsAlerts from '@/components/SettingsAlerts.vue'
import SettingsTags from '@/components/SettingsTags.vue'

const Auth = useAuth()
const { show: confirmShow, title: confirmTitle, message: confirmMessage, confirmText: confirmBtnText, cancelText: confirmCancelText, variant: confirmVariant, onConfirm, onCancel } = useConfirm()
const route = useRoute()
const router = useRouter()

const notification = ref(null)
const activeTab = ref('connection')

function showNotification(message, type) {
  notification.value = { message, type }
  setTimeout(() => { notification.value = null }, 3000)
}

const connectionState = useSettingsConnection(Auth, { showNotification })
const { onboarding } = connectionState

const accountsState = useSettingsAccounts(Auth, { showNotification, onboarding })
const targetsState = useSettingsTargets(Auth, { showNotification })
const tagsState = useSettingsTags(Auth, { showNotification })
const syncState = useSettingsSync(Auth, { showNotification, onboarding, router })
const prefsState = useSettingsPreferences({ saveStatus: targetsState.saveStatus })

onMounted(async () => {
  if (route.query.tab) activeTab.value = route.query.tab
  onboarding.value = route.query.onboarding === '1'
  connectionState.authEnabled.value = Auth.isAuthEnabled()

  const errorParam = route.query.error
  if (errorParam) showNotification(decodeURIComponent(errorParam), 'error')

  await connectionState.checkConnection()
  await accountsState.loadAllAccounts()
  await targetsState.loadTargets()
  await tagsState.loadTags()
  prefsState.loadRollAlerts()
  prefsState.loadPrivacyMode()
  connectionState.consentAcknowledged.value = localStorage.getItem('dataConsentAcknowledged') === 'true'
})
</script>

<template>
  <Transition
    enter-active-class="transition ease-out duration-200"
    leave-active-class="transition ease-in duration-150"
    enter-from-class="opacity-0 translate-y-[-8px]"
    leave-to-class="opacity-0 translate-y-[-8px]"
  >
    <div v-if="notification"
         class="fixed top-20 right-4 z-50 px-4 py-3 rounded shadow-lg text-sm"
         :class="notification.type === 'success'
           ? 'bg-tv-green/20 border border-tv-green/30 text-tv-green'
           : 'bg-tv-red/20 border border-tv-red/30 text-tv-red'">
      {{ notification.message }}
    </div>
  </Transition>

  <div class="flex" style="height: calc(100vh - 56px)">

    <!-- Left Sidebar Tabs -->
    <div class="w-56 flex-shrink-0 bg-tv-panel border-r border-tv-border py-4">
      <div class="px-3 mb-4">
        <h1 class="text-lg font-semibold text-tv-text">
          <i class="fas fa-cog mr-2 text-tv-blue"></i>Settings
        </h1>
      </div>
      <nav class="space-y-0.5 px-2">
        <button v-for="tab in [
          { id: 'connection', icon: 'fa-plug', label: 'Connection' },
          { id: 'accounts', icon: 'fa-university', label: 'Accounts' },
          { id: 'import', icon: 'fa-file-import', label: 'Import Trades' },
          { id: 'privacy', icon: 'fa-eye-slash', label: 'Privacy' },
          { id: 'targets', icon: 'fa-bullseye', label: 'Strategy Targets' },
          { id: 'alerts', icon: 'fa-bell', label: 'Roll Alerts' },
          { id: 'tags', icon: 'fa-tags', label: 'Tags' },
        ]" :key="tab.id"
          @click="activeTab = tab.id"
          class="w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm transition-colors text-left"
          :class="activeTab === tab.id
            ? 'bg-tv-blue/15 text-tv-blue border border-tv-blue/30'
            : 'text-tv-muted hover:text-tv-text hover:bg-tv-bg border border-transparent'">
          <i class="fas w-4 text-center" :class="tab.icon"></i>
          <span>{{ tab.label }}</span>
          <span v-if="tab.id === 'connection'" class="ml-auto">
            <i class="fas fa-circle text-[6px]"
               :class="connectionState.connectionStatus.value?.connected ? 'text-tv-green' : 'text-tv-red'"></i>
          </span>
        </button>
      </nav>
    </div>

    <!-- Right Content Area -->
    <div class="flex-1 overflow-y-auto tv-scrollbar p-6">
      <!-- Save status indicator -->
      <div class="flex items-center justify-end mb-4 h-5">
        <span v-if="targetsState.saveStatus.value === 'pending'" class="text-xs text-tv-muted">
          <i class="fas fa-circle text-tv-amber text-[8px] mr-1"></i>Unsaved
        </span>
        <span v-if="targetsState.saveStatus.value === 'saving'" class="text-xs text-tv-muted">
          <i class="fas fa-spinner fa-spin mr-1"></i>Saving...
        </span>
        <span v-if="targetsState.saveStatus.value === 'saved'" class="text-xs text-tv-green">
          <i class="fas fa-check mr-1"></i>Saved
        </span>
      </div>

      <SettingsConnection v-show="activeTab === 'connection'" :state="connectionState" :onboarding="onboarding" />
      <SettingsAccounts v-show="activeTab === 'accounts'" :state="accountsState" :onboarding="onboarding" @go-to-import="activeTab = 'import'" />
      <SettingsImport v-show="activeTab === 'import'" :state="syncState" :onboarding="onboarding" />
      <SettingsPrivacy v-show="activeTab === 'privacy'" :state="prefsState" />
      <SettingsTargets v-show="activeTab === 'targets'" :state="targetsState" />
      <SettingsAlerts v-show="activeTab === 'alerts'" :state="prefsState" />
      <SettingsTags v-show="activeTab === 'tags'" :state="tagsState" />
    </div>
  </div>

  <!-- Import success modal -->
  <div v-if="syncState.importResult.value" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
    <div class="bg-tv-panel border border-tv-border rounded-lg px-8 py-6 text-center shadow-2xl max-w-md">
      <i class="fas fa-check-circle text-tv-green text-4xl mb-4"></i>
      <h3 class="text-tv-text text-lg font-semibold mb-2">Import Complete!</h3>
      <p class="text-tv-muted text-sm mb-4">
        {{ syncState.importResult.value.transactions_processed || 0 }} transactions imported across
        {{ syncState.importResult.value.orders_assembled || 0 }} orders in
        {{ syncState.importResult.value.groups_processed || 0 }} groups.
      </p>
      <p class="text-tv-muted text-sm mb-6">
        Your positions are ready to view with live P&amp;L tracking. Use the Ledger page to explore trade history and roll chains.
      </p>
      <button @click="syncState.goToPositions()"
              class="bg-tv-blue hover:bg-tv-blue/80 text-white font-medium px-6 py-2 rounded transition-colors">
        Go to Positions
      </button>
    </div>
  </div>

  <ConfirmModal
    :show="confirmShow"
    :title="confirmTitle"
    :message="confirmMessage"
    :confirm-text="confirmBtnText"
    :cancel-text="confirmCancelText"
    :variant="confirmVariant"
    @confirm="onConfirm"
    @cancel="onCancel"
  />
</template>
