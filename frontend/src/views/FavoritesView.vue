<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listFavorites } from '@/api/media'
import type { MediaListItem, MediaSort } from '@/api/types'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import {
  DEFAULT_PAGE_SIZE,
  pageQueryPatch,
  parsePage,
  scrollListTop,
} from '@/utils/pageQuery'

const route = useRoute()
const router = useRouter()
const items = ref<MediaListItem[]>([])
const total = ref(0)
const page = ref(parsePage(route.query))
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const PAGE_SIZE = DEFAULT_PAGE_SIZE

function syncPageQuery(nextPage: number) {
  page.value = nextPage
  router.replace({
    query: {
      ...route.query,
      ...pageQueryPatch(nextPage),
    },
  })
}

async function load() {
  loading.value = true
  try {
    const data = await listFavorites({
      page: page.value,
      page_size: PAGE_SIZE,
      sort: sort.value,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载收藏失败')
  } finally {
    loading.value = false
  }
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  syncPageQuery(1)
  void load()
}

function onPageChange(p: number) {
  if (p === page.value) return
  syncPageQuery(p)
  scrollListTop()
  void load()
}

watch(
  () => route.query.page,
  (v) => {
    const p = parsePage({ page: v })
    if (p !== page.value) {
      page.value = p
      void load()
    }
  },
)

onMounted(() => {
  page.value = parsePage(route.query)
  void load()
})
</script>

<template>
  <div class="page">
    <div class="head">
      <div>
        <h1 class="page-title">收藏</h1>
        <p class="muted intro">已收藏的作品</p>
      </div>
      <el-select :model-value="sort" size="small" style="width: 168px" @change="onSortChange">
        <el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
    </div>
    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />
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
.head > div {
  min-width: 0;
  flex: 1 1 auto;
}
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
@media (max-width: 640px) {
  .head :deep(.el-select) {
    width: 100% !important;
    max-width: 220px;
  }
}
</style>
