<script setup lang="ts">
defineOptions({ name: 'SearchView' })

import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import ActorCard from '@/components/ActorCard.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listActors, listLibraries, listMedia } from '@/api/media'
import type { Actor, Library, MediaListItem, MediaSort } from '@/api/types'
import { usePagedRoute } from '@/composables/usePagedRoute'
import { getErrorMessage } from '@/utils/errors'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import { DEFAULT_PAGE_SIZE, queryString } from '@/utils/pageQuery'

type SearchTab = 'media' | 'actors'

const { route, page, replaceQuery, goPage, syncPageFromRoute } = usePagedRoute()

const tab = ref<SearchTab>(route.query.tab === 'actors' ? 'actors' : 'media')
const q = ref(queryString(route.query, 'q'))
const libraryId = ref<number | null>(Number(route.query.library || 0) || null)
const libraries = ref<Library[]>([])
const items = ref<MediaListItem[]>([])
const actorItems = ref<Actor[]>([])
const total = ref(0)
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const searched = ref(Boolean(route.query.q || route.query.library || route.query.tab))
const PAGE_SIZE = DEFAULT_PAGE_SIZE

function syncSearchQuery(nextPage: number, nextTab: SearchTab = tab.value) {
  tab.value = nextTab
  replaceQuery(
    {
      tab: nextTab === 'media' ? undefined : nextTab,
      q: q.value || undefined,
      library: nextTab === 'media' && libraryId.value ? String(libraryId.value) : undefined,
    },
    nextPage,
  )
}

async function runSearch() {
  loading.value = true
  searched.value = true
  try {
    if (tab.value === 'actors') {
      const data = await listActors({
        q: q.value || undefined,
        page: page.value,
        page_size: PAGE_SIZE,
      })
      actorItems.value = data.items
      items.value = []
      total.value = data.total
    } else {
      const data = await listMedia({
        q: q.value || undefined,
        library_id: libraryId.value || undefined,
        sort: sort.value,
        page: page.value,
        page_size: PAGE_SIZE,
      })
      items.value = data.items
      actorItems.value = []
      total.value = data.total
    }
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '搜索失败'))
  } finally {
    loading.value = false
  }
}

function onTabChange(next: SearchTab) {
  if (next === tab.value) return
  syncSearchQuery(1, next)
  void runSearch()
}

function onSearch() {
  syncSearchQuery(1)
  void runSearch()
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  if (searched.value && tab.value === 'media') {
    syncSearchQuery(1)
    void runSearch()
  }
}

function onPageChange(p: number) {
  if (!goPage(p)) return
  void runSearch()
}

function onMediaRefreshed(updated: MediaListItem) {
  const idx = items.value.findIndex((i) => i.id === updated.id)
  if (idx >= 0) items.value[idx] = { ...items.value[idx], ...updated }
}

function onActorRefreshed(updated: Actor) {
  const idx = actorItems.value.findIndex((a) => a.id === updated.id)
  if (idx >= 0) {
    actorItems.value[idx] = { ...actorItems.value[idx], ...updated }
  }
}

watch(
  () => [route.query.page, route.query.q, route.query.library, route.query.tab] as const,
  () => {
    const nextQ = queryString(route.query, 'q')
    const nextLib = Number(route.query.library || 0) || null
    const nextTab: SearchTab = route.query.tab === 'actors' ? 'actors' : 'media'
    let changed = syncPageFromRoute()
    if (nextQ !== q.value) {
      q.value = nextQ
      changed = true
    }
    if (nextLib !== libraryId.value) {
      libraryId.value = nextLib
      changed = true
    }
    if (nextTab !== tab.value) {
      tab.value = nextTab
      changed = true
    }
    if (changed && (searched.value || nextQ || nextLib || nextTab === 'actors')) {
      searched.value = true
      void runSearch()
    }
  },
)

onMounted(async () => {
  try {
    libraries.value = await listLibraries()
  } catch {
    /* ignore */
  }
  q.value = queryString(route.query, 'q')
  libraryId.value = Number(route.query.library || 0) || null
  tab.value = route.query.tab === 'actors' ? 'actors' : 'media'
  if (q.value || libraryId.value || route.query.page || tab.value === 'actors') {
    searched.value = true
    void runSearch()
  }
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">搜索</h1>
    <p class="muted intro">
      {{ tab === 'actors' ? '按演员名查找本地已刮削演员' : '按番号、标题或文件名查找；可限定媒体库' }}
    </p>

    <div class="tabs">
      <button type="button" class="tab" :class="{ on: tab === 'media' }" @click="onTabChange('media')">
        媒体
      </button>
      <button
        type="button"
        class="tab"
        :class="{ on: tab === 'actors' }"
        @click="onTabChange('actors')"
      >
        演员
      </button>
    </div>

    <div class="bar">
      <el-select
        v-if="tab === 'media'"
        v-model="libraryId"
        clearable
        placeholder="全部媒体库"
        style="width: 180px"
      >
        <el-option
          v-for="lib in libraries"
          :key="lib.id"
          :label="lib.name"
          :value="lib.id"
        />
      </el-select>
      <el-select
        v-if="tab === 'media'"
        :model-value="sort"
        style="width: 168px"
        @change="onSortChange"
      >
        <el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-input
        v-model="q"
        :placeholder="tab === 'actors' ? '演员名' : '番号 / 标题 / 文件名'"
        clearable
        @keyup.enter="onSearch"
      />
      <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
    </div>

    <template v-if="tab === 'media'">
      <SkeletonGrid v-if="loading && !items.length" :count="8" />
      <template v-else-if="searched || items.length">
        <MediaGrid :items="items" @refreshed="onMediaRefreshed" />
        <AppPagination
          :total="total"
          :page="page"
          :page-size="PAGE_SIZE"
          @update:page="onPageChange"
        />
      </template>
      <p v-else class="muted tip">输入关键词后回车或点击搜索</p>
    </template>

    <template v-else>
      <SkeletonGrid v-if="loading && !actorItems.length" variant="actor" :count="8" />
      <template v-else-if="searched || actorItems.length">
        <div v-if="actorItems.length" class="actor-grid">
          <ActorCard
            v-for="a in actorItems"
            :key="a.id"
            :actor="a"
            @refreshed="onActorRefreshed"
          />
        </div>
        <el-empty v-else :description="q ? '未找到匹配演员' : '暂无演员，请先刮削媒体'" />
        <AppPagination
          :total="total"
          :page="page"
          :page-size="PAGE_SIZE"
          @update:page="onPageChange"
        />
      </template>
      <p v-else class="muted tip">输入演员名后回车或点击搜索</p>
    </template>
  </div>
</template>

<style scoped>
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
.tabs {
  display: inline-flex;
  gap: 6px;
  margin-bottom: 14px;
  padding: 4px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel);
}
.tab {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}
.tab.on {
  background: var(--accent-soft);
  color: var(--accent);
}
.bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  max-width: 760px;
  flex-wrap: wrap;
  align-items: center;
}
.bar :deep(.el-select),
.bar :deep(.el-input) {
  min-width: 0;
}
.actor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
}
.tip {
  margin-top: 24px;
}
@media (max-width: 640px) {
  .bar {
    max-width: none;
  }
  .bar :deep(.el-select) {
    flex: 1 1 calc(50% - 5px);
    width: auto !important;
    min-width: 0;
  }
  .bar :deep(.el-input) {
    flex: 1 1 100%;
  }
  .bar :deep(.el-input__wrapper) {
    min-height: 40px;
    font-size: 16px;
  }
  .bar .el-button {
    flex: 1 1 auto;
    min-height: 40px;
  }
  .actor-grid {
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .actor-grid {
    grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
    gap: 8px;
  }
}
</style>
