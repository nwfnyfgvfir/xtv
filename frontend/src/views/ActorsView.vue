<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import ActorCard from '@/components/ActorCard.vue'
import { listActors } from '@/api/media'
import type { Actor } from '@/api/types'
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

function onActorRefreshed(updated: Actor) {
  const idx = items.value.findIndex((a) => a.id === updated.id)
  if (idx >= 0) {
    items.value[idx] = { ...items.value[idx], ...updated }
  }
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
      <ActorCard
        v-for="a in items"
        :key="a.id"
        :actor="a"
        @refreshed="onActorRefreshed"
      />
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
  flex-wrap: wrap;
  align-items: center;
}
.bar :deep(.el-input) {
  flex: 1 1 180px;
  min-width: 0;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
}
@media (max-width: 640px) {
  .bar {
    max-width: none;
    width: 100%;
  }
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 8px;
  }
}
</style>
