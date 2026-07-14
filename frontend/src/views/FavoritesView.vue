<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import ActorCard from '@/components/ActorCard.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listFavoriteActors, listFavorites } from '@/api/media'
import type { Actor, MediaListItem, MediaSort } from '@/api/types'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import {
  DEFAULT_PAGE_SIZE,
  pageQueryPatch,
  parsePage,
  scrollListTop,
} from '@/utils/pageQuery'

type FavTab = 'media' | 'actors'

const route = useRoute()
const router = useRouter()
const tab = ref<FavTab>(route.query.tab === 'actors' ? 'actors' : 'media')
const mediaItems = ref<MediaListItem[]>([])
const actorItems = ref<Actor[]>([])
const total = ref(0)
const page = ref(parsePage(route.query))
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const PAGE_SIZE = DEFAULT_PAGE_SIZE

function syncQuery(nextPage: number, nextTab: FavTab = tab.value) {
  page.value = nextPage
  tab.value = nextTab
  router.replace({
    query: {
      ...route.query,
      tab: nextTab === 'media' ? undefined : nextTab,
      ...pageQueryPatch(nextPage),
    },
  })
}

async function load() {
  loading.value = true
  try {
    if (tab.value === 'actors') {
      const data = await listFavoriteActors({
        page: page.value,
        page_size: PAGE_SIZE,
      })
      actorItems.value = data.items
      mediaItems.value = []
      total.value = data.total
    } else {
      const data = await listFavorites({
        page: page.value,
        page_size: PAGE_SIZE,
        sort: sort.value,
      })
      mediaItems.value = data.items
      actorItems.value = []
      total.value = data.total
    }
  } catch {
    ElMessage.error('加载收藏失败')
  } finally {
    loading.value = false
  }
}

function onTabChange(next: FavTab) {
  if (next === tab.value) return
  syncQuery(1, next)
  void load()
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  syncQuery(1)
  void load()
}

function onPageChange(p: number) {
  if (p === page.value) return
  syncQuery(p)
  scrollListTop()
  void load()
}

function onActorRefreshed(updated: Actor) {
  if (!updated.favorited) {
    actorItems.value = actorItems.value.filter((a) => a.id !== updated.id)
    total.value = Math.max(0, total.value - 1)
    return
  }
  const idx = actorItems.value.findIndex((a) => a.id === updated.id)
  if (idx >= 0) {
    actorItems.value[idx] = { ...actorItems.value[idx], ...updated }
  }
}

watch(
  () => [route.query.page, route.query.tab] as const,
  () => {
    const p = parsePage(route.query)
    const nextTab: FavTab = route.query.tab === 'actors' ? 'actors' : 'media'
    let changed = false
    if (p !== page.value) {
      page.value = p
      changed = true
    }
    if (nextTab !== tab.value) {
      tab.value = nextTab
      changed = true
    }
    if (changed) void load()
  },
)

onMounted(() => {
  page.value = parsePage(route.query)
  tab.value = route.query.tab === 'actors' ? 'actors' : 'media'
  void load()
})
</script>

<template>
  <div class="page">
    <div class="head">
      <div>
        <h1 class="page-title">收藏</h1>
        <p class="muted intro">
          {{ tab === 'actors' ? '已收藏的演员' : '已收藏的作品' }}
        </p>
      </div>
      <el-select
        v-if="tab === 'media'"
        :model-value="sort"
        size="small"
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
    </div>

    <div class="tabs" role="tablist" aria-label="收藏分类">
      <button
        type="button"
        role="tab"
        class="tab"
        :class="{ active: tab === 'media' }"
        :aria-selected="tab === 'media'"
        @click="onTabChange('media')"
      >
        作品
      </button>
      <button
        type="button"
        role="tab"
        class="tab"
        :class="{ active: tab === 'actors' }"
        :aria-selected="tab === 'actors'"
        @click="onTabChange('actors')"
      >
        演员
      </button>
    </div>

    <template v-if="tab === 'media'">
      <SkeletonGrid v-if="loading && !mediaItems.length" />
      <MediaGrid
        v-else
        :items="mediaItems"
        empty-title="暂无收藏"
        empty-hint="在片库卡片或详情页点心形即可收藏"
      />
    </template>
    <template v-else>
      <div v-if="loading && !actorItems.length" class="muted">加载中…</div>
      <div v-else-if="actorItems.length" class="actor-grid">
        <ActorCard
          v-for="a in actorItems"
          :key="a.id"
          :actor="a"
          @refreshed="onActorRefreshed"
        />
      </div>
      <el-empty
        v-else
        description="暂无收藏演员"
      >
        <template #description>
          <p>暂无收藏演员</p>
          <p class="muted empty-hint">在演员列表或详情页点心形即可收藏</p>
        </template>
      </el-empty>
    </template>

    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 16px;
  border-radius: 999px;
  background: var(--panel);
  border: 1px solid var(--border);
}
.tab {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  padding: 6px 16px;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--accent);
  background: var(--accent-soft);
}
.actor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
}
.empty-hint {
  margin: 4px 0 0;
  font-size: 13px;
}
@media (max-width: 640px) {
  .actor-grid {
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .actor-grid {
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 8px;
  }
}
</style>
