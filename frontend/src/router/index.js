import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

// Eagerly import Risk and Components — their chunks consistently trigger
// Firefox NS_ERROR_CORRUPTED_CONTENT when loaded as separate dynamic chunks.
import RiskPage from '@/pages/risk/App.vue'
import ComponentsPage from '@/pages/components/App.vue'

const routes = [
  {
    path: '/',
    component: DefaultLayout,
    children: [
      { path: '', redirect: '/positions' },
      { path: 'positions', name: 'positions', component: () => import('@/pages/positions/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Positions' } },
      { path: 'ledger', name: 'ledger', component: () => import('@/pages/ledger/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Ledger' } },
      { path: 'reports', name: 'reports', component: () => import('@/pages/reports/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Reports' } },
      { path: 'risk', name: 'risk', component: RiskPage, meta: { requiresAuth: true, requiresTastytrade: true, title: 'Risk' } },
      { path: 'settings', name: 'settings', component: () => import('@/pages/settings/App.vue'), meta: { requiresAuth: true, requiresTastytrade: false, title: 'Settings' } },
      { path: 'privacy', name: 'privacy', component: () => import('@/pages/privacy/App.vue'), meta: { requiresAuth: false, title: 'Privacy' } },
      { path: 'components', name: 'components', component: ComponentsPage, meta: { requiresAuth: false, title: 'Component Library' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Cache the tastytrade credentials check so it only runs once per session.
let tastytradeConfigured = null

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

  if (to.name === 'risk') {
    const authStore = useAuthStore()
    await authStore.init()
    if (!authStore.riskPageEnabled) return { name: 'positions' }
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

router.afterEach((to) => {
  if (to.name === 'settings') tastytradeConfigured = null
})

router.onError((error, to) => {
  console.error('Navigation error:', error)
})

export default router
