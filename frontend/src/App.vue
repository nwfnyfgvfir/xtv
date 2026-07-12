<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const active = computed(() => {
  if (route.path.startsWith('/settings')) return 'settings'
  if (route.path.startsWith('/search')) return 'search'
  return 'library'
})
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand" @click="router.push('/')">
        <span class="brand-mark">TV</span>
        <span class="brand-sub">CINEMA</span>
      </div>
      <nav class="nav">
        <button :class="{ on: active === 'library' }" @click="router.push('/')">媒体库</button>
        <button :class="{ on: active === 'search' }" @click="router.push('/search')">搜索</button>
        <button :class="{ on: active === 'settings' }" @click="router.push('/settings')">设置</button>
      </nav>
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
  gap: 28px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
  background: rgba(11, 13, 18, 0.88);
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
  gap: 6px;
}
.nav button {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: 8px 14px;
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
</style>
