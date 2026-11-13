<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { setupAuthInterceptor, useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { APP_VERSION } from '@/utils/version'

const route = useRoute()
const router = useRouter()
const { theme, toggle } = useTheme()
const { authEnabled, isAuthenticated, logout } = useAuth()
const navigating = ref(false)
const searchQuery = ref(typeof route.query.q === 'string' ? route.query.q : '')
const KEEP_ALIVE_NAMES = ['LibraryView', 'SearchView', 'ActorsView', 'FavoritesView']
const navigation = [
  { key: 'library', label: '媒体库', path: '/', icon: 'grid' },
  { key: 'actors', label: '演员', path: '/actors', icon: 'users' },
  { key: 'favorites', label: '收藏', path: '/favorites', icon: 'heart' },
  { key: 'search', label: '搜索', path: '/search', icon: 'search' },
  { key: 'settings', label: '设置', path: '/settings', icon: 'settings' },
] as const
const active = computed(() => {
  if (route.path.startsWith('/settings') || route.path.startsWith('/duplicates')) return 'settings'
  if (route.path.startsWith('/search')) return 'search'
  if (route.path.startsWith('/actors')) return 'actors'
  if (route.path.startsWith('/favorites')) return 'favorites'
  return 'library'
})
const pageLabel = computed(() => {
  if (route.name === 'detail') return '影片详情'
  if (route.name === 'actor-detail') return '演员详情'
  if (route.name === 'duplicates') return '重复影片'
  return navigation.find((item) => item.key === active.value)?.label || '媒体库'
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
  }, 200)
})
watch(
  () => route.query.q,
  (value) => {
    if (route.name === 'search') searchQuery.value = typeof value === 'string' ? value : ''
  },
)

function onSearch() {
  const q = searchQuery.value.trim()
  router.push({ name: 'search', query: q ? { q } : {} })
}
function onLogout() {
  logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell" :class="{ 'with-navigation': showChrome }">
    <div class="route-progress" :class="{ on: navigating }" aria-hidden="true">
      <div class="bar" />
    </div>
    <aside v-if="showChrome" class="sidebar">
      <router-link to="/" class="brand" aria-label="TV 媒体库首页">
        <span class="brand-mark">tv<span>·</span></span>
        <span class="brand-text">私人影音库<small>YOUR PRIVATE COLLECTION</small></span>
      </router-link>
      <p class="nav-label">我的空间</p>
      <nav class="side-navigation" aria-label="主导航">
        <router-link
          v-for="item in navigation.slice(0, 4)"
          :key="item.key"
          :to="item.path"
          class="nav-item"
          :class="{ active: active === item.key }"
          :aria-current="active === item.key ? 'page' : undefined"
        >
          <AppIcon :name="item.icon" :size="19" /><span>{{ item.label }}</span>
          <span v-if="active === item.key" class="active-indicator" />
        </router-link>
      </nav>
      <div class="sidebar-bottom">
        <router-link
          to="/settings"
          class="nav-item"
          :class="{ active: active === 'settings' }"
          :aria-current="active === 'settings' ? 'page' : undefined"
        >
          <AppIcon name="settings" :size="19" /><span>设置</span>
        </router-link>
        <div class="sidebar-note">
          <AppIcon name="server" :size="16" /><span
            >自托管影音<span class="version">{{ APP_VERSION }}</span></span
          >
        </div>
      </div>
    </aside>

    <div class="app-content">
      <header v-if="showChrome" class="topbar">
        <router-link to="/" class="mobile-brand" aria-label="媒体库首页"
          >tv<span>·</span></router-link
        >
        <div class="breadcrumb">
          <span>我的空间</span><AppIcon name="chevron" :size="13" /><span>{{ pageLabel }}</span>
        </div>
        <form class="global-search" role="search" @submit.prevent="onSearch">
          <AppIcon name="search" :size="18" />
          <input
            v-model="searchQuery"
            type="search"
            aria-label="全局搜索"
            placeholder="搜索番号、标题或文件名"
          />
          <button type="submit" aria-label="开始搜索" class="search-submit">
            <AppIcon name="chevron" :size="16" />
          </button>
        </form>
        <div class="header-tools">
          <button
            class="icon-button"
            type="button"
            :aria-label="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
            :title="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
            @click="toggle"
          >
            <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" :size="19" />
          </button>
          <button
            v-if="authEnabled && isAuthenticated"
            class="icon-button"
            type="button"
            aria-label="退出登录"
            title="退出登录"
            @click="onLogout"
          >
            <AppIcon name="logout" :size="19" />
          </button>
          <router-link v-else-if="authEnabled" to="/login" class="login-link">登录</router-link>
        </div>
      </header>
      <main id="main-content" class="main">
        <router-view v-slot="{ Component, route: current }">
          <keep-alive :include="KEEP_ALIVE_NAMES"
            ><component :is="Component" :key="current.name"
          /></keep-alive>
        </router-view>
      </main>
    </div>

    <nav v-if="showChrome" class="bottom-nav" aria-label="手机主导航">
      <router-link
        v-for="item in navigation"
        :key="item.key"
        :to="item.path"
        :class="{ active: active === item.key }"
        :aria-current="active === item.key ? 'page' : undefined"
      >
        <AppIcon :name="item.icon" :size="20" /><span>{{ item.label }}</span>
      </router-link>
    </nav>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100dvh;
}
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: 220px;
  display: flex;
  flex-direction: column;
  padding: 32px 18px 22px;
  background: var(--bg-elevated);
  border-right: 1px solid var(--border-subtle);
  z-index: var(--z-nav);
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 10px;
  margin-bottom: 53px;
}
.brand-mark,
.mobile-brand {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 37px;
  letter-spacing: -0.075em;
  line-height: 1;
  color: var(--text);
}
.brand-mark > span,
.mobile-brand > span {
  color: var(--accent);
}
.brand-text {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.brand-text small {
  display: block;
  font-size: 7px;
  letter-spacing: 0.09em;
  color: var(--faint);
  margin-top: 5px;
  font-weight: 400;
  white-space: nowrap;
}
.nav-label {
  margin: 0 14px 12px;
  color: var(--faint);
  font-size: 11px;
  letter-spacing: 0.08em;
}
.side-navigation {
  display: grid;
  gap: 7px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 45px;
  padding: 0 14px;
  border-radius: 8px;
  color: var(--muted);
  font-size: 13px;
  transition:
    background-color var(--dur-2),
    color var(--dur-2);
}
.nav-item:hover {
  color: var(--text);
  background: var(--panel-hover);
}
.nav-item.active {
  color: var(--accent);
  background: var(--accent-soft);
  font-weight: 600;
}
.active-indicator {
  margin-left: auto;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
}
.sidebar-bottom {
  margin-top: auto;
  display: grid;
  gap: 22px;
}
.sidebar-note {
  border-top: 1px solid var(--border-subtle);
  padding: 20px 14px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--faint);
  font-size: 11px;
}
.version {
  display: block;
  font-family: var(--font-mono);
  font-size: 10px;
  margin-top: 2px;
}
.with-navigation .app-content {
  margin-left: 220px;
}
.topbar {
  height: 78px;
  padding: 0 var(--gutter);
  display: flex;
  align-items: center;
  gap: 26px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 11px;
  font-size: 12px;
  color: var(--faint);
  white-space: nowrap;
}
.breadcrumb > span:last-child {
  color: var(--text-soft);
}
.global-search {
  margin-left: auto;
  width: min(380px, 42vw);
  min-width: 0;
  height: 38px;
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 0 10px 0 13px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--faint);
}
.global-search:focus-within {
  border-color: var(--accent-line);
}
.global-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: none;
  padding: 0;
  color: var(--text);
  font-size: 12px;
  background: transparent;
}
.global-search input::placeholder {
  color: var(--faint);
}
.global-search input:focus-visible {
  outline: none;
}
.search-submit {
  border: 0;
  background: transparent;
  color: var(--muted);
  display: grid;
  place-items: center;
  height: 28px;
  width: 28px;
  cursor: pointer;
  border-radius: 5px;
  flex-shrink: 0;
}
.search-submit:hover {
  color: var(--accent);
  background: var(--accent-soft);
}
.header-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-button {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.icon-button:hover {
  background: var(--panel-hover);
  color: var(--text);
}
.login-link {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.main {
  min-width: 0;
}
.bottom-nav,
.mobile-brand {
  display: none;
}
@media (max-width: 1100px) and (min-width: 861px) {
  .sidebar {
    width: 190px;
    padding-left: 12px;
    padding-right: 12px;
  }
  .with-navigation .app-content {
    margin-left: 190px;
  }
  .brand {
    gap: 9px;
    padding: 0 8px;
  }
  .brand-text small {
    font-size: 6px;
  }
  .topbar {
    gap: 14px;
  }
  .breadcrumb > span:first-child,
  .breadcrumb > .app-icon {
    display: none;
  }
}
@media (max-width: 860px) {
  .sidebar {
    display: none;
  }
  .with-navigation .app-content {
    margin-left: 0;
    padding-bottom: calc(74px + env(safe-area-inset-bottom));
  }
  .topbar {
    height: 68px;
    gap: 14px;
    padding: 0 18px;
  }
  .mobile-brand {
    display: block;
    font-size: 31px;
    flex-shrink: 0;
    padding-bottom: 4px;
  }
  .breadcrumb {
    display: none;
  }
  .global-search {
    margin-left: 0;
    flex: 1;
    width: auto;
    height: 44px;
  }
  .icon-button {
    width: 44px;
    height: 44px;
  }
  .bottom-nav {
    position: fixed;
    inset: auto 0 0;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
    border-top: 1px solid var(--border-subtle);
    background: var(--bg-elevated);
    z-index: var(--z-nav);
  }
  .bottom-nav a {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 5px;
    min-height: 48px;
    color: var(--faint);
    font-size: 10px;
    border-radius: 8px;
  }
  .bottom-nav a.active {
    color: var(--accent);
    background: var(--accent-soft);
  }
}
@media (max-width: 420px) {
  .topbar {
    gap: 10px;
  }
  .global-search {
    gap: 7px;
    padding-left: 9px;
  }
  .header-tools {
    gap: 2px;
  }
  .search-submit {
    display: none;
  }
}
</style>
