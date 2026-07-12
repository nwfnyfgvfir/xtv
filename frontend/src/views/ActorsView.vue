<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import { listActors } from '@/api/media'
import type { Actor } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'
import {
  DEFAULT_PAGE_SIZE,
  pageQueryPatch,
  parsePage,
  scrollListTop,
} from '@/utils/pageQuery'

const route = useRoute()
const router = useRouter()
const items = ref<Actor[]>([])
const total = ref(0)
const page = ref(parsePage(route.query))
const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const loading = ref(false)
const PAGE_SIZE = DEFAULT_PAGE_SIZE

function syncQuery(nextPage: number, nextQ = q.value) {
  page.value = nextPage
  router.replace({
    query: {
      ...route.query,
      q: nextQ || undefined,
      ...pageQueryPatch(nextPage),
    },
  })
}

async function load() {
  loading.value = true
  try {
    const data = await listActors({
      q: q.value || undefined,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载演员失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  syncQuery(1, q.value)
  void load()
}

function onPageChange(p: number) {
  if (p === page.value) return
  syncQuery(p)
  scrollListTop()
  void load()
}

watch(
  () => [route.query.page, route.query.q] as const,
  () => {
    const p = parsePage(route.query)
    const nextQ = typeof route.query.q === 'string' ? route.query.q : ''
    let changed = false
    if (p !== page.value) {
      page.value = p
      changed = true
    }
    if (nextQ !== q.value) {
      q.value = nextQ
      changed = true
    }
    if (changed) void load()
  },
)

onMounted(() => {
  page.value = parsePage(route.query)
  if (typeof route.query.q === 'string') q.value = route.query.q
  void load()
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">演员</h1>
    <div class="bar">
      <el-input v-model="q" placeholder="搜索演员" clearable @keyup.enter="onSearch" />
      <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
    </div>
    <div v-if="loading && !items.length" class="muted">加载中…</div>
    <div v-else-if="items.length" class="grid">
      <button
        v-for="a in items"
        :key="a.id"
        class="actor-card"
        type="button"
        @click="router.push(`/actors/${a.id}`)"
      >
        <img v-if="a.image_url" :src="a.image_url" :alt="a.name" loading="lazy" />
        <div v-else class="mono" :style="monogramStyle(a.name)">
          {{ monogramChar({ title: a.name }) }}
        </div>
        <div class="info">
          <div class="name">{{ a.name }}</div>
          <div class="muted count">{{ a.media_count ?? 0 }} 部作品</div>
        </div>
      </button>
    </div>
    <el-empty v-else description="暂无演员，请先刮削媒体" />
    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 10px;
  max-width: 520px;
  margin-bottom: 18px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
}
.actor-card {
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  padding: 0;
  text-align: left;
  color: inherit;
  box-shadow: var(--shadow-card);
}
.actor-card:hover {
  border-color: var(--accent);
}
.actor-card img,
.mono {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 42px;
  color: var(--accent);
  background: var(--bg-elevated);
}
.info {
  padding: 10px;
}
.name {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.count {
  font-size: 12px;
  margin-top: 2px;
}
</style>
