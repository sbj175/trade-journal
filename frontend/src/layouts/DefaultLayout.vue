<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import NavBar from '@/components/NavBar.vue'

const authStore = useAuthStore()

onMounted(() => {
  authStore.init()
})
</script>

<template>
  <NavBar />
  <router-view />
</template>
