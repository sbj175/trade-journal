import { createRouter, createWebHistory } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

/**
 * Wrap a dynamic import with retry logic. On first failure (e.g., Firefox
 * NS_ERROR_CORRUPTED_CONTENT from stale cache), adds a cache-busting
 * timestamp query parameter and retries once.
 */
function lazyLoad(importFn) {
  return async () => {
    try {
      return await importFn()
    } catch (err) {
      // Dynamic import failed — likely a stale/corrupted cached chunk.
      // Hard-navigate to force a fresh load of all assets.
      window.location.reload()
      return new Promise(() => {}) // halt while reload happens
    }
  }
}

const routes = [
  {
    path: '/',
    component: DefaultLayout,
    children: [
      { path: '', redirect: '/positions' },
      { path: 'positions', name: 'positions', component: lazyLoad(() => import('@/pages/positions/App.vue')), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Positions' } },
      { path: 'ledger', name: 'ledger', component: lazyLoad(() => import('@/pages/ledger/App.vue')), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Ledger' } },
      { path: 'reports', name: 'reports', component: lazyLoad(() => import('@/pages/reports/App.vue')), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Reports' } },
      { path: 'risk', name: 'risk', component: lazyLoad(() => import('@/pages/risk/App.vue')), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Risk' } },
      { path: 'settings', name: 'settings', component: lazyLoad(() => import('@/pages/settings/App.vue')), meta: { requiresAuth: true, requiresTastytrade: false, title: 'Settings' } },
      { path: 'privacy', name: 'privacy', component: lazyLoad(() => import('@/pages/privacy/App.vue')), meta: { requiresAuth: false, title: 'Privacy' } },
      { path: 'components', name: 'components', component: lazyLoad(() => import('@/pages/components/App.vue')), meta: { requiresAuth: false, title: 'Component Library' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Cache the tastytrade credentials check so it only runs once per session.
let tastytradeConfigured = null

// Modern return-style guard (no next() callback — avoids known Vue Router 4 quirks)
router.beforeEach(async (to, from) => {
  document.title = to.meta.title ? `OptionLedger - ${to.meta.title}` : 'OptionLedger'

  if (!to.meta.requiresAuth) return true

  const Auth = window.Auth
  if (!Auth) return true

  await Auth.init()
  if (!Auth.isAuthEnabled()) return true

  const token = await Auth.getAccessToken()
  if (!token) {
    window.location.href = '/login'
    return false
  }

  if (to.meta.requiresTastytrade && tastytradeConfigured !== true) {
    try {
      const resp = await Auth.authFetch('/api/settings/credentials')
      if (resp.ok) {
        const data = await resp.json()
        if (!data.configured) {
          return { name: 'settings', query: { tab: 'connection', onboarding: '1' } }
        }
        tastytradeConfigured = true
      }
    } catch (e) {
      // If credentials check fails, continue anyway
    }
  }

  return true
})

// Reset the credentials cache when navigating to settings (user may disconnect)
router.afterEach((to) => {
  if (to.name === 'settings') tastytradeConfigured = null
})

// Catch-all: any navigation error triggers a hard reload to recover
router.onError((error, to) => {
  console.error('Navigation error:', error)
  window.location.href = to.fullPath
})

export default router
