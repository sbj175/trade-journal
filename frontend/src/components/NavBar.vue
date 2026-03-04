<script setup>
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()

const navLinks = [
  { to: '/positions', label: 'Positions' },
  { to: '/ledger', label: 'Ledger' },
  { to: '/reports', label: 'Reports' },
  { to: '/risk', label: 'Risk' },
]
</script>

<template>
  <nav class="bg-tv-panel border-b border-tv-border sticky top-0 z-50">
    <div class="h-[2px] bg-tv-blue"></div>
    <div class="flex items-center justify-between h-14 px-5">
      <div class="flex items-center h-full gap-8">
        <router-link to="/positions" class="flex items-center gap-2.5">
          <span class="w-8 h-8 rounded-lg bg-tv-blue flex items-center justify-center shadow-lg shadow-tv-blue/25">
            <i class="fas fa-chart-line text-white text-sm"></i>
          </span>
          <span class="text-lg font-bold tracking-tight">Option<span class="text-tv-blue">Ledger</span></span>
        </router-link>
        <div class="flex items-center h-full gap-1">
          <router-link v-for="link in navLinks" :key="link.to" :to="link.to"
             class="h-full flex items-center px-3.5 text-sm font-semibold tracking-wide border-b-2 transition-colors"
             :class="route.path === link.to
               ? 'text-tv-text border-tv-blue'
               : 'text-tv-muted border-transparent hover:text-tv-text'">
            {{ link.label }}
          </router-link>
        </div>
      </div>
      <div class="flex items-center gap-5 text-sm">
        <div id="nav-right"></div>
        <div v-if="authStore.authEnabled && authStore.userEmail" class="flex items-center gap-3 border-l border-tv-border pl-5">
          <span class="text-tv-muted text-xs truncate max-w-[150px]" :title="authStore.userEmail">{{ authStore.userEmail }}</span>
          <button @click="authStore.signOut()" class="text-tv-muted hover:text-tv-red transition-colors" title="Sign out">
            <i class="fas fa-sign-out-alt text-xs"></i>
          </button>
        </div>
        <router-link v-if="route.path !== '/settings'" to="/settings"
                     class="border-l border-tv-border pl-5 text-tv-muted hover:text-tv-text transition-colors">
          <i class="fas fa-cog text-sm"></i>
        </router-link>
        <span v-else class="border-l border-tv-border pl-5 text-tv-blue flex items-center gap-1.5">
          <i class="fas fa-cog text-sm"></i>
          <span class="text-sm font-medium">Settings</span>
        </span>
      </div>
    </div>
  </nav>
</template>
