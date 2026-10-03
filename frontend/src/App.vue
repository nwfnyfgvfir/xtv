<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setupAuthInterceptor, useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { APP_VERSION } from '@/utils/version'

const route = useRoute()
const router = useRouter()
const { theme, toggle } = useTheme()
const appVersion = APP_VERSION
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
        <span class="brand-divider" aria-hidden="true" />
        <span class="brand-sub">影院</span>
        <span class="brand-ver num">{{ appVersion }}</span>
      </div>

      <nav class="nav desktop-nav" aria-label="主导航">
        <button
          type="button"
          class="nav-item"
          :class="{ on: active === 'library' }"
          :aria-current="active === 'library' ? 'page' : undefined"
          @click="go('/')"
        >
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="3" width="7" height="7" rx="1.6" />
            <rect x="14" y="3" width="7" height="7" rx="1.6" />
            <rect x="3" y="14" width="7" height="7" rx="1.6" />
            <rect x="14" y="14" width="7" height="7" rx="1.6" />
          </svg>
          <span>媒体库</span>
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: active === 'actors' }"
          :aria-current="active === 'actors' ? 'page' : undefined"
          @click="go('/actors')"
        >
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="8" r="3.6" />
            <path d="M4.8 20.4c0-3.9 3.3-6.4 7.2-6.4s7.2 2.5 7.2 6.4" />
          </svg>
          <span>演员</span>
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: active === 'favorites' }"
          :aria-current="active === 'favorites' ? 'page' : undefined"
          @click="go('/favorites')"
        >
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 20.4 4.8 13.3a4.6 4.6 0 0 1 6.4-6.5l.8.8.8-.8a4.6 4.6 0 0 1 6.4 6.5L12 20.4Z" />
          </svg>
          <span>收藏</span>
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: active === 'search' }"
          :aria-current="active === 'search' ? 'page' : undefined"
          @click="go('/search')"
        >
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="6.4" />
            <path d="m16 16 4.4 4.4" />
          </svg>
          <span>搜索</span>
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ on: active === 'settings' }"
          :aria-current="active === 'settings' ? 'page' : undefined"
          @click="go('/settings')"
        >
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 8h9M17 8h3M4 16h3M11 16h9" />
            <circle cx="15" cy="8" r="2.1" />
            <circle cx="9" cy="16" r="2.1" />
          </svg>
          <span>设置</span>
        </button>
      </nav>

      <div class="tools">
        <button
          class="icon-btn"
          type="button"
          :title="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
          :aria-label="theme === 'dark' ? '切换到亮色' : '切换到暗色'"
          @click="toggle"
        >
          <svg v-if="theme === 'dark'" class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path
              d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"
            />
          </svg>
          <svg v-else class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 14.2A8.4 8.4 0 0 1 9.8 4a8.5 8.5 0 1 0 10.2 10.2Z" />
          </svg>
        </button>
        <button
          v-if="authEnabled && isAuthenticated"
          class="text-btn desktop-only"
          type="button"
          @click="onLogout"
        >
          退出
        </button>
        <button
          v-else-if="authEnabled"
          class="text-btn desktop-only"
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
      <button
        type="button"
        :class="{ on: active === 'library' }"
        :aria-current="active === 'library' ? 'page' : undefined"
        @click="go('/')"
      >
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="3" width="7" height="7" rx="1.6" />
          <rect x="14" y="3" width="7" height="7" rx="1.6" />
          <rect x="3" y="14" width="7" height="7" rx="1.6" />
          <rect x="14" y="14" width="7" height="7" rx="1.6" />
        </svg>
        <span>媒体库</span>
      </button>
      <button
        type="button"
        :class="{ on: active === 'actors' }"
        :aria-current="active === 'actors' ? 'page' : undefined"
        @click="go('/actors')"
      >
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="8" r="3.6" />
          <path d="M4.8 20.4c0-3.9 3.3-6.4 7.2-6.4s7.2 2.5 7.2 6.4" />
        </svg>
        <span>演员</span>
      </button>
      <button
        type="button"
        :class="{ on: active === 'favorites' }"
        :aria-current="active === 'favorites' ? 'page' : undefined"
        @click="go('/favorites')"
      >
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 20.4 4.8 13.3a4.6 4.6 0 0 1 6.4-6.5l.8.8.8-.8a4.6 4.6 0 0 1 6.4 6.5L12 20.4Z" />
        </svg>
        <span>收藏</span>
      </button>
      <button
        type="button"
        :class="{ on: active === 'search' }"
        :aria-current="active === 'search' ? 'page' : undefined"
        @click="go('/search')"
      >
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="6.4" />
          <path d="m16 16 4.4 4.4" />
        </svg>
        <span>搜索</span>
      </button>
      <button
        type="button"
        :class="{ on: active === 'settings' }"
        :aria-current="active === 'settings' ? 'page' : undefined"
        @click="go('/settings')"
      >
        <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 8h9M17 8h3M4 16h3M11 16h9" />
          <circle cx="15" cy="8" r="2.1" />
          <circle cx="9" cy="16" r="2.1" />
        </svg>
        <span>设置</span>
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
  padding-bottom: calc(66px + env(safe-area-inset-bottom));
}
@media (min-width: 861px) {
  .layout.has-bottom {
    padding-bottom: env(safe-area-inset-bottom);
  }
}

/* ---------------------------------------------------------------- topbar */

.topbar {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-3) var(--gutter);
  padding-top: calc(var(--space-3) + env(safe-area-inset-top));
  padding-left: max(var(--gutter), env(safe-area-inset-left));
  padding-right: max(var(--gutter), env(safe-area-inset-right));
  border-bottom: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--bg) 86%, transparent);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  backdrop-filter: blur(16px) saturate(1.3);
  -webkit-backdrop-filter: blur(16px) saturate(1.3);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
}
.brand-mark {
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 500;
  letter-spacing: var(--tracking-tight);
  color: var(--accent);
  line-height: 1;
}
.brand-divider {
  width: 1px;
  height: 18px;
  background: var(--accent-line);
  flex-shrink: 0;
}
.brand-sub {
  font-size: var(--text-sm);
  font-weight: 500;
  letter-spacing: var(--tracking-widest);
  color: var(--muted);
}
.brand-ver {
  margin-left: var(--space-1);
  font-size: var(--text-2xs);
  color: var(--faint);
  opacity: 0.7;
}

/* ---------------------------------------------------------------- nav */

.nav {
  display: flex;
  gap: var(--space-1);
  flex: 1;
  justify-content: center;
  flex-wrap: wrap;
}
.nav-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  min-height: 40px;
  transition:
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out);
}
.nav-item .ico {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}
.nav-item:hover:not(.on) {
  color: var(--text);
  background: var(--panel-hover);
}
.nav-item.on {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--accent-line);
  font-weight: 600;
}

/* ---------------------------------------------------------------- tools */

.tools {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-shrink: 0;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
  border-radius: var(--radius-full);
  width: 40px;
  height: 40px;
  cursor: pointer;
  transition:
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
.icon-btn .ico {
  width: 18px;
  height: 18px;
}
.icon-btn:hover {
  border-color: var(--accent-line);
  color: var(--accent);
  background: var(--panel-hover);
}
.text-btn {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  cursor: pointer;
  font-size: var(--text-sm);
  min-height: 40px;
  transition:
    color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
.text-btn:hover {
  color: var(--accent);
  background: var(--panel-hover);
}

/* Shared icon rendering: line icons, never filled blobs. */
.ico {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* ---------------------------------------------------------------- bottom nav */

.bottom-nav {
  display: none;
}

@media (max-width: 860px) {
  .desktop-nav,
  .desktop-only {
    display: none !important;
  }
  .topbar {
    gap: var(--space-3);
    padding-top: calc(var(--space-2) + env(safe-area-inset-top));
    padding-bottom: var(--space-2);
  }
  .brand-mark {
    font-size: 21px;
  }
  .brand-sub {
    font-size: var(--text-xs);
  }
  /* Keep the version visible on phones too — just smaller and quieter. */
  .brand-ver {
    font-size: 10px;
    margin-left: 0;
  }

  .bottom-nav {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-nav);
    background: color-mix(in oklab, var(--bg-elevated) 92%, transparent);
    border-top: 1px solid var(--border-subtle);
    backdrop-filter: blur(16px) saturate(1.3);
    -webkit-backdrop-filter: blur(16px) saturate(1.3);
    padding: var(--space-2) var(--space-1) calc(var(--space-2) + env(safe-area-inset-bottom));
    padding-left: max(var(--space-1), env(safe-area-inset-left));
    padding-right: max(var(--space-1), env(safe-area-inset-right));
  }
  .bottom-nav button {
    position: relative;
    border: 0;
    background: transparent;
    color: var(--faint);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    font-size: var(--text-2xs);
    padding: var(--space-2) var(--space-1);
    min-height: 48px;
    cursor: pointer;
    transition: color var(--dur-2) var(--ease-out);
  }
  .bottom-nav .ico {
    width: 21px;
    height: 21px;
  }
  .bottom-nav button.on {
    color: var(--accent);
    font-weight: 600;
  }
  /* Active marker — a short gold bar, the recurring "scene marker" motif. */
  .bottom-nav button.on::before {
    content: '';
    position: absolute;
    top: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 20px;
    height: 2px;
    border-radius: 0 0 var(--radius-xs) var(--radius-xs);
    background: var(--accent);
  }
}
</style>
