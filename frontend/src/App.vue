<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setupAuthInterceptor, useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const router = useRouter()
const { theme, toggle } = useTheme()
const { authEnabled, isAuthenticated, logout, refreshStatus, ready } = useAuth()
const navigating = ref(false)

const active = computed(() => {
  if (route.path.startsWith('/settings')) return 'settings'
  if (route.path.startsWith('/search')) return 'search'
  if (route.path.startsWith('/actors')) return 'actors'
  if (route.path.startsWith('/favorites')) return 'favorites'
  if (route.path.startsWith('/login')) return 'login'
  return 'library'
})

setupAuthInterceptor(() => {
  if (route.name !== 'login') router.push({ name: 'login', query: { redirect: route.fullPath } })
})

router.beforeEach((to, _from, next) => {
  navigating.value = true
  if (ready.value && authEnabled.value && !isAuthenticated.value && to.name !== 'login') {
    next({ name: 'login', query: { redirect: to.fullPath } })
    return
  }
  next()
})

router.afterEach(() => {
  setTimeout(() => {
    navigating.value = false
  }, 250)
})

onMounted(() => {
  void refreshStatus()
})

function onLogout() {
  logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="layout">
    <div class="route-progress" :class="{ on: navigating }"><div class="bar" /></div>
    <header class="topbar">
      <div class="brand" @click="router.push('/')">
        <span class="brand-mark">TV</span>
        <span class="brand-sub">CINEMA</span>
      </div>
      <nav class="nav">
        <button :class="{ on: active === 'library' }" @click="router.push('/')">媒体库</button>
        <button :class="{ on: active === 'actors' }" @click="router.push('/actors')">演员</button>
        <button :class="{ on: active === 'favorites' }" @click="router.push('/favorites')">收藏</button>
        <button :class="{ on: active === 'search' }" @click="router.push('/search')">搜索</button>
        <button :class="{ on: active === 'settings' }" @click="router.push('/settings')">设置</button>
      </nav>
      <div class="tools">
        <button class="icon-btn" type="button" :title="theme === 'dark' ? '切换白天' : '切换暗色'" @click="toggle">
          {{ theme === 'dark' ? '☀' : '☾' }}
        </button>
        <button v-if="authEnabled && isAuthenticated" class="icon-btn" type="button" @click="onLogout">退出</button>
        <button v-else-if="authEnabled" class="icon-btn" type="button" @click="router.push('/login')">登录</button>
      </div>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  position: sticky;
  top: 0;
  z-index: 20;
  backdrop-filter: blur(14px) saturate(1.2);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
}
.brand-mark {
  font-family: var(--font-display);
  font-size: 28px;
  letter-spacing: 0.12em;
  color: var(--accent);
  text-shadow: 0 0 24px var(--accent-glow);
  line-height: 1;
}
.brand-sub {
  font-size: 11px;
  letter-spacing: 0.28em;
  color: var(--muted);
  font-weight: 600;
}
.nav {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  flex: 1;
}
.nav button {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: 8px 12px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.15s ease, color 0.15s ease;
}
.nav button.on {
  color: #1a1205;
  background: var(--accent);
  font-weight: 600;
}
.nav button:not(.on):hover {
  color: var(--text);
  background: var(--accent-soft);
}
.tools {
  display: flex;
  gap: 6px;
  align-items: center;
}
.icon-btn {
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}
.icon-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
</style>
