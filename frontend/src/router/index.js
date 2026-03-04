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

  if (to.meta.requiresTastytrade) {
    try {
      const resp = await Auth.authFetch('/api/settings/credentials')
      if (resp.ok) {
        const data = await resp.json()
        if (!data.configured) {
          return next({ name: 'settings', query: { tab: 'connection', onboarding: '1' } })
        }
      }
    } catch (e) {
      // If credentials check fails, continue anyway
    }
  }

  next()
})

export default router
