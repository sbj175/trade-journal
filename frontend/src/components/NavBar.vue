<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import BaseButton from '@/components/BaseButton.vue'
import BaseIcon from '@/components/BaseIcon.vue'

const route = useRoute()
const authStore = useAuthStore()

const allNavLinks = [
  {
    to: '/positions',
    label: 'Positions',
    children: [
      { to: '/positions/options', label: 'Options' },
      { to: '/positions/equities', label: 'Equities' },
    ],
  },
  { to: '/ledger', label: 'Ledger' },
  { to: '/reports', label: 'Reports' },
  { to: '/risk', label: 'Risk', enabled: () => authStore.riskPageEnabled },
]

const navLinks = computed(() => allNavLinks.filter(l => !l.enabled || l.enabled()))

const openDropdown = ref(null)
const mobileMenuOpen = ref(false)
const isDark = ref(!document.documentElement.classList.contains('light'))

function toggleTheme() {
  document.documentElement.classList.add('theme-transitioning')
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.remove('light')
  } else {
    document.documentElement.classList.add('light')
  }
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  setTimeout(() => document.documentElement.classList.remove('theme-transitioning'), 200)
}

function isActiveParent(link) {
  if (link.children) return route.path.startsWith(link.to)
  return route.path === link.to
}

function toggleMobileMenu() {
  mobileMenuOpen.value = !mobileMenuOpen.value
}

function closeMobileMenu() {
  mobileMenuOpen.value = false
}

const currentPageLabel = computed(() => {
  for (const link of allNavLinks) {
    if (link.children) {
      const child = link.children.find(c => route.path === c.to)
      if (child) return child.label
    } else if (route.path === link.to || route.path.startsWith(link.to + '/')) {
      return link.label
    }
  }
  if (route.path === '/settings') return 'Settings'
  return route.meta.title ?? ''
})

watch(
  () => route.path,
  () => {
    openDropdown.value = null
    mobileMenuOpen.value = false
  }
)
</script>

<template>
  <nav class="bg-tv-panel border-b border-tv-border">
    <div class="h-[2px] bg-tv-blue"></div>

    <!-- Top bar -->
    <div class="h-14 px-4 sm:px-5">
      <div class="flex items-center justify-between h-full gap-3">
        <!-- Left -->
        <div class="flex items-center min-w-0 gap-3 sm:gap-8 h-full">
          <router-link
            to="/positions/options"
            class="flex items-center min-w-0 gap-2.5"
            @click="closeMobileMenu"
          >
            <img :src="'/static/logos/logo_mark_mono_transparent.png'" alt="OptionLedger" class="logo-mark w-9 h-9 shrink-0" />
            <span class="text-base sm:text-lg font-bold tracking-tight truncate">
              Option<span class="text-tv-blue">Ledger</span>
            </span>
          </router-link>

          <!-- Mobile page title -->
          <span
            v-if="currentPageLabel"
            class="md:hidden border-l border-tv-border pl-3 text-sm font-medium text-tv-muted truncate"
          >{{ currentPageLabel }}</span>

          <!-- Desktop nav -->
          <div class="hidden md:flex items-center h-full gap-1">
            <template v-for="link in navLinks" :key="link.to">
              <div
                v-if="link.children"
                class="relative h-full flex items-center"
                @mouseenter="openDropdown = link.to"
                @mouseleave="openDropdown = null"
              >
                <span
                  class="h-full flex items-center px-3.5 text-sm font-semibold tracking-wide border-b-2 transition-colors cursor-default"
                  :class="isActiveParent(link)
                    ? 'text-tv-text border-tv-blue'
                    : 'text-tv-muted border-transparent hover:text-tv-text'"
                >
                  {{ link.label }}
                  <BaseIcon name="chevron-down" class="text-[9px] ml-1.5 opacity-50" />
                </span>

                <div
                  v-show="openDropdown === link.to"
                  class="absolute top-full left-0 mt-0 bg-tv-panel border border-tv-border rounded shadow-lg py-1 min-w-[140px] z-50"
                >
                  <router-link
                    v-for="child in link.children"
                    :key="child.to"
                    :to="child.to"
                    @click="openDropdown = null"
                    class="block px-4 py-2 text-sm transition-colors"
                    :class="route.path === child.to
                      ? 'text-tv-blue bg-tv-blue/10'
                      : 'text-tv-muted hover:text-tv-text hover:bg-tv-border/20'"
                  >
                    {{ child.label }}
                  </router-link>
                </div>
              </div>

              <router-link
                v-else
                :to="link.to"
                class="h-full flex items-center px-3.5 text-sm font-semibold tracking-wide border-b-2 transition-colors"
                :class="isActiveParent(link)
                  ? 'text-tv-text border-tv-blue'
                  : 'text-tv-muted border-transparent hover:text-tv-text'"
              >
                {{ link.label }}
              </router-link>
            </template>
          </div>
        </div>

        <!-- Right -->
        <div class="flex items-center shrink-0 gap-2 sm:gap-5 text-sm">
          <!-- Desktop auth/settings -->
          <div
            v-if="authStore.authEnabled && authStore.userEmail"
            class="hidden md:flex items-center gap-3 border-l border-tv-border pl-5"
          >
            <span
              class="text-tv-muted text-xs truncate max-w-[150px]"
              :title="authStore.userEmail"
            >
              {{ authStore.userEmail }}
            </span>
            <BaseButton variant="ghost" size="sm" icon="sign-out-alt" @click="authStore.signOut()" title="Sign out" class="hover:text-tv-red" />
          </div>

          <router-link
            v-if="route.path !== '/settings'"
            to="/settings"
            class="hidden md:flex border-l border-tv-border pl-5 text-tv-muted hover:text-tv-text transition-colors"
          >
            <BaseIcon name="cog" size="sm" />
          </router-link>

          <span
            v-else
            class="hidden md:flex border-l border-tv-border pl-5 text-tv-blue items-center gap-1.5"
          >
            <BaseIcon name="cog" size="sm" />
            <span class="text-sm font-medium">Settings</span>
          </span>

          <!-- Theme toggle (desktop) -->
          <button
            type="button"
            class="hidden md:flex border-l border-tv-border pl-5 text-tv-muted hover:text-tv-text transition-colors"
            :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
            @click="toggleTheme"
          >
            <BaseIcon :name="isDark ? 'sun' : 'moon'" size="sm" />
          </button>

          <!-- Theme toggle (mobile) -->
          <button
            type="button"
            class="md:hidden inline-flex items-center justify-center w-10 h-10 rounded-lg text-tv-muted hover:text-tv-text hover:bg-tv-border/30 transition-colors"
            :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
            @click="toggleTheme"
          >
            <BaseIcon :name="isDark ? 'sun' : 'moon'" size="md" />
          </button>

          <!-- Mobile menu button -->
          <button
            type="button"
            class="md:hidden inline-flex items-center justify-center w-10 h-10 rounded-lg text-tv-muted hover:text-tv-text hover:bg-tv-border/30 transition-colors"
            :aria-expanded="mobileMenuOpen ? 'true' : 'false'"
            aria-label="Toggle navigation menu"
            @click="toggleMobileMenu"
          >
            <BaseIcon :name="mobileMenuOpen ? 'times' : 'bars'" size="md" />
          </button>
        </div>
      </div>
    </div>

    <!-- Mobile menu -->
    <div
      v-if="mobileMenuOpen"
      class="md:hidden border-t border-tv-border px-4 py-3 space-y-2 bg-tv-panel"
    >
      <template v-for="link in navLinks" :key="link.to">
        <!-- Flatten links with children directly -->
        <template v-if="link.children">
          <router-link
            v-for="child in link.children"
            :key="child.to"
            :to="child.to"
            class="block rounded-lg px-4 py-3 text-sm font-semibold transition-colors"
            :class="route.path === child.to
              ? 'text-tv-text bg-tv-blue/10 border border-tv-blue/30'
              : 'text-tv-muted hover:text-tv-text hover:bg-tv-border/20 border border-transparent'"
            @click="closeMobileMenu"
          >
            {{ child.label }}
          </router-link>
        </template>

        <!-- Simple link -->
        <router-link
          v-else
          :to="link.to"
          class="block rounded-lg px-4 py-3 text-sm font-semibold transition-colors"
          :class="isActiveParent(link)
            ? 'text-tv-text bg-tv-blue/10 border border-tv-blue/30'
            : 'text-tv-muted hover:text-tv-text hover:bg-tv-border/20 border border-transparent'"
          @click="closeMobileMenu"
        >
          {{ link.label }}
        </router-link>
      </template>

      <!-- Settings -->
      <router-link
        to="/settings"
        class="block rounded-lg px-4 py-3 text-sm font-semibold transition-colors"
        :class="route.path === '/settings'
          ? 'text-tv-text bg-tv-blue/10 border border-tv-blue/30'
          : 'text-tv-muted hover:text-tv-text hover:bg-tv-border/20 border border-transparent'"
        @click="closeMobileMenu"
      >
        Settings
      </router-link>

      <div
        v-if="authStore.authEnabled && authStore.userEmail"
        class="pt-3 mt-3 border-t border-tv-border space-y-3"
      >
        <div class="px-1">
          <div class="text-[11px] uppercase tracking-wide text-tv-muted/80 mb-1">Signed in as</div>
          <div class="text-sm text-tv-text break-all">{{ authStore.userEmail }}</div>
        </div>

        <BaseButton variant="ghost" @click="authStore.signOut()" class="w-full justify-center hover:text-tv-red border border-tv-border/70 min-h-[44px]">
          <template #icon><BaseIcon name="sign-out-alt" size="xs" /></template>
          Sign out
        </BaseButton>
      </div>
    </div>
  </nav>
</template>