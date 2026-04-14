<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import NavBar from '@/components/NavBar.vue'
import GlobalToolbar from '@/components/GlobalToolbar.vue'

const authStore = useAuthStore()

onMounted(() => {
  authStore.init()
})
</script>

<template>
  <div class="md:sticky top-0 z-50">
    <NavBar />
    <GlobalToolbar />
  </div>
  <div class="w-full md:overflow-x-auto">
    <div class="md:min-w-max">
      <router-view />
    </div>
  </div>
</template>
