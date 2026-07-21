<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setupAuthInterceptor, useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const router = useRouter()
const { theme, toggle } = useTheme()
const { authEnabled, isAuthenticated, logout } = useAuth()
const navigating = ref(false)

const KEEP_ALIVE_NAMES = ['LibraryView', 'SearchView', 'ActorsView', 'FavoritesView']

const active = computed(() => {
  if (route.path.startsWith('/settings') || route.path.startsWith('/duplicates')) return 'settings'
  if (route.path.startsWith('/search')) return 'search'
  if (route.path.startsWith('/actors')) return 'actors'
  if (route.path.startsWith('/favorites')) return 'favorites'
  if (route.path.startsWith('/login')) return 'login'
  return 'library'
})

const showChrome = computed(() => route.name !== 'login')

setupAuthInterceptor(() => {
  if (route.name !== 'login') router.push({ name: 'login', query: { redirect: route.fullPath } })
})

router.beforeEach(() => {
  navigating.value = true
})

router.afterEach(() => {
  setTimeout(() => {
    navigating.value = false
  }, 250)
})

function onLogout() {
  logout()
  router.push({ name: 'login' })
}

function go(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="layout" :class="{ 'has-bottom': showChrome }">
    <div class="route-progress" :class="{ on: navigating }"><div class="bar" /></div>
    <header v-if="showChrome" class="topbar">
      <div class="brand" @click="go('/')" title="TV影院">
        <span class="brand-mark">TV</span>
        <span class="brand-sub">影院</span>
      </div>
      <nav class="nav desktop-nav" aria-label="主导航">
        <button type="button" :class="{ on: active === 'library' }" :aria-current="active === 'library' ? 'page' : undefined" @click="go('/')">媒体库</button>
        <button type="button" :class="{ on: active === 'actors' }" :aria-current="active === 'actors' ? 'page' : undefined" @click="go('/actors')">演员</button>
        <button type="button" :class="{ on: active === 'favorites' }" :aria-current="active === 'favorites' ? 'page' : undefined" @click="go('/favorites')">收藏</button>
        <button type="button" :class="{ on: active === 'search' }" :aria-current="active === 'search' ? 'page' : undefined" @click="go('/search')">搜索</button>
        <button type="button" :class="{ on: active === 'settings' }" :aria-current="active === 'settings' ? 'page' : undefined" @click="go('/settings')">设置</button>
      </nav>
      <div class="tools">
        <button class="icon-btn" type="button" :title="theme === 'dark' ? '切换白天' : '切换暗色'" @click="toggle">
          {{ theme === 'dark' ? '☀' : '☾' }}
        </button>
        <button v-if="authEnabled && isAuthenticated" class="icon-btn desktop-only" type="button" @click="onLogout">
          退出
        </button>
        <button
          v-else-if="authEnabled"
          class="icon-btn desktop-only"
          type="button"
          @click="go('/login')"
        >
          登录
        </button>
      </div>
    </header>
    <main class="main">
      <router-view v-slot="{ Component, route: r }">
        <keep-alive :include="KEEP_ALIVE_NAMES">
          <component :is="Component" :key="r.name" />
        </keep-alive>
      </router-view>
    </main>
    <nav v-if="showChrome" class="bottom-nav" aria-label="主导航">
      <button type="button" :class="{ on: active === 'library' }" :aria-current="active === 'library' ? 'page' : undefined" @click="go('/')">
        <span class="ico" aria-hidden="true">▣</span><span>库</span>
      </button>
      <button type="button" :class="{ on: active === 'actors' }" :aria-current="active === 'actors' ? 'page' : undefined" @click="go('/actors')">
        <span class="ico" aria-hidden="true">◎</span><span>演员</span>
      </button>
      <button type="button" :class="{ on: active === 'favorites' }" :aria-current="active === 'favorites' ? 'page' : undefined" @click="go('/favorites')">
        <span class="ico" aria-hidden="true">♥</span><span>收藏</span>
      </button>
      <button type="button" :class="{ on: active === 'search' }" :aria-current="active === 'search' ? 'page' : undefined" @click="go('/search')">
        <span class="ico" aria-hidden="true">⌕</span><span>搜索</span>
      </button>
      <button type="button" :class="{ on: active === 'settings' }" :aria-current="active === 'settings' ? 'page' : undefined" @click="go('/settings')">
        <span class="ico" aria-hidden="true">⚙</span><span>设置</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  padding-bottom: env(safe-area-inset-bottom);
}
.layout.has-bottom {
  padding-bottom: calc(64px + env(safe-area-inset-bottom));
}
@media (min-width: 861px) {
  .layout.has-bottom {
    padding-bottom: env(safe-area-inset-bottom);
  }
}
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  padding-top: calc(12px + env(safe-area-inset-top));
  padding-left: max(16px, env(safe-area-inset-left));
  padding-right: max(16px, env(safe-area-inset-right));
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
  font-weight: 700;
}
.brand-sub {
  font-size: 14px;
  letter-spacing: 0.12em;
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
  min-height: 40px;
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
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  min-height: 40px;
}
.icon-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.bottom-nav {
  display: none;
}
@media (max-width: 860px) {
  .desktop-nav,
  .desktop-only {
    display: none !important;
  }
  .topbar {
    padding-left: max(12px, env(safe-area-inset-left));
    padding-right: max(12px, env(safe-area-inset-right));
    gap: 10px;
  }
  .brand-mark {
    font-size: 22px;
  }
  .brand-sub {
    font-size: 13px;
    letter-spacing: 0.08em;
  }
  .bottom-nav {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    background: color-mix(in srgb, var(--panel) 94%, transparent);
    border-top: 1px solid var(--border);
    backdrop-filter: blur(12px);
    padding: 6px 4px calc(6px + env(safe-area-inset-bottom));
    padding-left: max(4px, env(safe-area-inset-left));
    padding-right: max(4px, env(safe-area-inset-right));
  }
  .bottom-nav button {
    border: 0;
    background: transparent;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    font-size: 11px;
    padding: 6px 2px;
    min-height: 48px;
    cursor: pointer;
  }
  .bottom-nav button.on {
    color: var(--accent);
    font-weight: 600;
  }
  .bottom-nav .ico {
    font-size: 16px;
    line-height: 1;
  }
}
</style>
