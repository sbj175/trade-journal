import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth'

export const useTargetsStore = defineStore('targets', () => {
  const targetsMap = ref({})
  const loaded = ref(false)

  async function load() {
    if (loaded.value) return
    try {
      const Auth = useAuth()
      const response = await Auth.authFetch('/api/settings/targets')
      if (response.ok) {
        const data = await response.json()
        const list = Array.isArray(data) ? data : (data.targets || [])
        const mapped = {}
        list.forEach(t => { if (t.strategy_name) mapped[t.strategy_name] = t })
        targetsMap.value = mapped
        loaded.value = true
      }
    } catch (e) { }
  }

  function invalidate() {
    loaded.value = false
  }

  return { targetsMap, loaded, load, invalidate }
})
