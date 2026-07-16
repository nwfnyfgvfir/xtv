<script setup lang="ts">
defineOptions({ name: 'ActorsView' })

import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import ActorCard from '@/components/ActorCard.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listActors } from '@/api/media'
import type { Actor, ActorSort } from '@/api/types'
import { usePagedRoute } from '@/composables/usePagedRoute'
import { ACTOR_SORT_OPTIONS, loadActorSort, saveActorSort } from '@/utils/actorSort'
import { getErrorMessage } from '@/utils/errors'
import { DEFAULT_PAGE_SIZE, queryString } from '@/utils/pageQuery'

const { route, page, replaceQuery, goPage, syncPageFromRoute } = usePagedRoute()
const items = ref<Actor[]>([])
const total = ref(0)
const q = ref(queryString(route.query, 'q'))
const sort = ref<ActorSort>(loadActorSort())
const loading = ref(false)
const PAGE_SIZE = DEFAULT_PAGE_SIZE

async function load() {
  loading.value = true
  try {
    const data = await listActors({
      q: q.value || undefined,
      sort: sort.value,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    items.value = data.items
    total.value = data.total
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载演员失败'))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  replaceQuery({ q: q.value || undefined }, 1)
  void load()
}

function onSortChange(v: ActorSort) {
  sort.value = v
  saveActorSort(v)
  replaceQuery({ q: q.value || undefined }, 1)
  void load()
}

function onPageChange(p: number) {
  if (!goPage(p)) return
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
    const nextQ = queryString(route.query, 'q')
    let changed = syncPageFromRoute()
    if (nextQ !== q.value) {
      q.value = nextQ
      changed = true
    }
    if (changed) void load()
  },
)

onMounted(() => {
  q.value = queryString(route.query, 'q')
  void load()
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">演员</h1>
    <div class="bar">
      <el-input v-model="q" placeholder="搜索演员" clearable @keyup.enter="onSearch" />
      <el-select
        class="sort-select"
        :model-value="sort"
        size="default"
        @change="onSortChange"
      >
        <el-option
          v-for="opt in ACTOR_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
    </div>
    <SkeletonGrid v-if="loading && !items.length" variant="actor" :count="12" />
    <div v-else-if="items.length" class="grid">
      <ActorCard
        v-for="a in items"
        :key="a.id"
        :actor="a"
        @refreshed="onActorRefreshed"
      />
    </div>
    <el-empty
      v-else
      :description="q ? '未找到匹配演员' : '暂无演员，请先刮削媒体'"
    />
    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 10px;
  max-width: 640px;
  margin-bottom: 18px;
  flex-wrap: wrap;
  align-items: center;
}
.bar :deep(.el-input) {
  flex: 1 1 180px;
  min-width: 0;
}
.sort-select {
  width: 168px;
  flex: 0 0 auto;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 16px;
}
@media (max-width: 640px) {
  .bar {
    max-width: none;
    width: 100%;
  }
  .bar :deep(.el-input) {
    flex: 1 1 100%;
  }
  .bar :deep(.el-input__wrapper) {
    min-height: 40px;
    font-size: 16px;
  }
  .sort-select {
    flex: 1 1 calc(50% - 5px);
    width: auto;
    min-width: 0;
  }
  .bar .el-button {
    flex: 1 1 auto;
    width: 100%;
    min-height: 40px;
  }
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
}
</style>
