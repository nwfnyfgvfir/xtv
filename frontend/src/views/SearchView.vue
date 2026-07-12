<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listLibraries, listMedia } from '@/api/media'
import type { Library, MediaListItem, MediaSort } from '@/api/types'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import {
  DEFAULT_PAGE_SIZE,
  pageQueryPatch,
  parsePage,
  scrollListTop,
} from '@/utils/pageQuery'

const route = useRoute()
const router = useRouter()

const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const libraryId = ref<number | null>(
  Number(route.query.library || 0) || null,
)
const libraries = ref<Library[]>([])
const items = ref<MediaListItem[]>([])
const total = ref(0)
const page = ref(parsePage(route.query))
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const searched = ref(Boolean(route.query.q || route.query.library))
const PAGE_SIZE = DEFAULT_PAGE_SIZE

function syncSearchQuery(nextPage: number) {
  page.value = nextPage
  router.replace({
    query: {
      ...route.query,
      q: q.value || undefined,
      library: libraryId.value ? String(libraryId.value) : undefined,
      ...pageQueryPatch(nextPage),
    },
  })
}

async function runSearch() {
  loading.value = true
  searched.value = true
  try {
    const data = await listMedia({
      q: q.value || undefined,
      library_id: libraryId.value || undefined,
      sort: sort.value,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('搜索失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  syncSearchQuery(1)
  void runSearch()
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  if (searched.value) {
    syncSearchQuery(1)
    void runSearch()
  }
}

function onPageChange(p: number) {
  if (p === page.value) return
  syncSearchQuery(p)
  scrollListTop()
  void runSearch()
}

watch(
  () => [route.query.page, route.query.q, route.query.library] as const,
  () => {
    const p = parsePage(route.query)
    const nextQ = typeof route.query.q === 'string' ? route.query.q : ''
    const nextLib = Number(route.query.library || 0) || null
    let changed = false
    if (p !== page.value) {
      page.value = p
      changed = true
    }
    if (nextQ !== q.value) {
      q.value = nextQ
      changed = true
    }
    if (nextLib !== libraryId.value) {
      libraryId.value = nextLib
      changed = true
    }
    if (changed && (searched.value || nextQ || nextLib)) {
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
  page.value = parsePage(route.query)
  if (typeof route.query.q === 'string') q.value = route.query.q
  libraryId.value = Number(route.query.library || 0) || null
  if (q.value || libraryId.value || route.query.page) {
    searched.value = true
    void runSearch()
  }
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">搜索</h1>
    <p class="muted intro">按番号、标题或文件名查找；可限定媒体库</p>
    <div class="bar">
      <el-select
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
      <el-select :model-value="sort" style="width: 168px" @change="onSortChange">
        <el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-input
        v-model="q"
        placeholder="番号 / 标题 / 文件名"
        clearable
        @keyup.enter="onSearch"
      />
      <el-button type="primary" :loading="loading" @click="onSearch">搜索</el-button>
    </div>
    <SkeletonGrid v-if="loading && !items.length" :count="8" />
    <template v-else-if="searched || items.length">
      <MediaGrid :items="items" />
      <AppPagination
        :total="total"
        :page="page"
        :page-size="PAGE_SIZE"
        @update:page="onPageChange"
      />
    </template>
    <p v-else class="muted tip">输入关键词后回车或点击搜索</p>
  </div>
</template>

<style scoped>
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
.bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  max-width: 760px;
  flex-wrap: wrap;
}
.tip {
  margin-top: 24px;
}
</style>
