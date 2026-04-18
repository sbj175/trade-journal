/**
 * Privacy mode and roll alert preferences (localStorage-backed).
 */
import { ref } from 'vue'

export function useSettingsPreferences({ saveStatus }) {
  const privacyMode = ref('off')

  const rollAlerts = ref({
    enabled: true,
    profitTarget: true,
    lossLimit: true,
    lateStage: true,
    deltaSaturation: true,
    lowRewardToRisk: true,
  })

  function loadRollAlerts() {
    try {
      const saved = localStorage.getItem('rollAlertSettings')
      if (saved) rollAlerts.value = JSON.parse(saved)
    } catch (e) { /* use defaults */ }
  }

  function saveRollAlerts() {
    localStorage.setItem('rollAlertSettings', JSON.stringify(rollAlerts.value))
    saveStatus.value = 'saved'
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = null }, 2000)
  }

  function savePrivacyMode() {
    localStorage.setItem('privacyMode', privacyMode.value)
    saveStatus.value = 'saved'
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = null }, 2000)
  }

  function loadPrivacyMode() {
    privacyMode.value = localStorage.getItem('privacyMode') || 'off'
  }

  return {
    privacyMode,
    rollAlerts,
    loadRollAlerts,
    saveRollAlerts,
    savePrivacyMode,
    loadPrivacyMode,
  }
}
