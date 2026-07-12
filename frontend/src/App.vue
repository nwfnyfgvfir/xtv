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
      <div class="brand" @click="router.push('/')">TV</div>
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
  gap: 24px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: rgba(15, 17, 21, 0.92);
  position: sticky;
  top: 0;
  z-index: 20;
  backdrop-filter: blur(8px);
}
.brand {
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--accent);
  cursor: pointer;
  font-size: 20px;
}
.nav {
  display: flex;
  gap: 8px;
}
.nav button {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}
.nav button.on,
.nav button:hover {
  color: var(--text);
  background: #222733;
}
</style>
