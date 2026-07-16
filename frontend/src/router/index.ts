import { createRouter, createWebHistory } from 'vue-router'
import { ensureAuthReady, useAuth } from '@/composables/useAuth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'library',
      component: () => import('@/views/LibraryView.vue'),
      meta: { keepAlive: true },
    },
    {
      path: '/search',
      name: 'search',
      component: () => import('@/views/SearchView.vue'),
      meta: { keepAlive: true },
    },
    {
      path: '/media/:id',
      name: 'detail',
      component: () => import('@/views/DetailView.vue'),
      props: true,
    },
    {
      path: '/actors',
      name: 'actors',
      component: () => import('@/views/ActorsView.vue'),
      meta: { keepAlive: true },
    },
    {
      path: '/actors/:id',
      name: 'actor-detail',
      component: () => import('@/views/ActorDetailView.vue'),
      props: true,
    },
    {
      path: '/favorites',
      name: 'favorites',
      component: () => import('@/views/FavoritesView.vue'),
      meta: { keepAlive: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash }
    if (to.path !== from.path) return { top: 0 }
    return undefined
  },
})

router.beforeEach(async (to) => {
  await ensureAuthReady()
  const { authEnabled, isAuthenticated } = useAuth()
  if (authEnabled.value && !isAuthenticated.value && to.name !== 'login') {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authEnabled.value && isAuthenticated.value) {
    const redirect = typeof to.query.redirect === 'string' ? to.query.redirect : '/'
    return redirect || '/'
  }
  return true
})

export default router
