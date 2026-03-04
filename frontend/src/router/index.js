import { createRouter, createWebHistory } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

const routes = [
  {
    path: '/',
    component: DefaultLayout,
    children: [
      { path: '', redirect: '/positions' },
      { path: 'positions', name: 'positions', component: () => import('@/pages/positions/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Positions' } },
      { path: 'ledger', name: 'ledger', component: () => import('@/pages/ledger/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Ledger' } },
      { path: 'reports', name: 'reports', component: () => import('@/pages/reports/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Reports' } },
      { path: 'risk', name: 'risk', component: () => import('@/pages/risk/App.vue'), meta: { requiresAuth: true, requiresTastytrade: true, title: 'Risk' } },
      { path: 'settings', name: 'settings', component: () => import('@/pages/settings/App.vue'), meta: { requiresAuth: true, requiresTastytrade: false, title: 'Settings' } },
      { path: 'privacy', name: 'privacy', component: () => import('@/pages/privacy/App.vue'), meta: { requiresAuth: false, title: 'Privacy' } },
      { path: 'components', name: 'components', component: () => import('@/pages/components/App.vue'), meta: { requiresAuth: false, title: 'Component Library' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Cache the tastytrade credentials check so it only runs once per session.
// Without this, every navigation to a data page makes an API call that delays
// the route transition long enough for the user to click again, causing Vue
// Router to cancel the pending navigation.
let tastytradeConfigured = null

router.beforeEach(async (to, from, next) => {
  document.title = to.meta.title ? `OptionLedger - ${to.meta.title}` : 'OptionLedger'

  if (!to.meta.requiresAuth) return next()

  const Auth = window.Auth
  if (!Auth) return next()

  await Auth.init()
  if (!Auth.isAuthEnabled()) return next()

  const token = await Auth.getAccessToken()
  if (!token) {
    window.location.href = '/login'
    return
  }

  if (to.meta.requiresTastytrade && tastytradeConfigured !== true) {
    try {
      const resp = await Auth.authFetch('/api/settings/credentials')
      if (resp.ok) {
        const data = await resp.json()
        if (!data.configured) {
          return next({ name: 'settings', query: { tab: 'connection', onboarding: '1' } })
        }
        tastytradeConfigured = true
      }
    } catch (e) {
      // If credentials check fails, continue anyway
    }
  }

  next()
})

// Reset the credentials cache when navigating to settings (user may disconnect)
router.afterEach((to) => {
  if (to.name === 'settings') tastytradeConfigured = null
})

export default router
