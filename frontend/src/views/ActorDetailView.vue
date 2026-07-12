<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { getActor, listActorMedia, rescrapeActorImage } from '@/api/media'
import type { Actor, MediaListItem, MediaSort } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import {
  DEFAULT_PAGE_SIZE,
  pageQueryPatch,
  parsePage,
  scrollListTop,
} from '@/utils/pageQuery'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const actor = ref<Actor | null>(null)
const items = ref<MediaListItem[]>([])
const total = ref(0)
const page = ref(parsePage(route.query))
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const imgLoading = ref(false)
const imgFailed = ref(false)
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
  imgFailed.value = false
  try {
    actor.value = await getActor(Number(props.id))
    const data = await listActorMedia(Number(props.id), {
      page: page.value,
      page_size: PAGE_SIZE,
      sort: sort.value,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载演员详情失败')
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

async function onRescrapeImage() {
  if (!actor.value) return
  imgLoading.value = true
  try {
    actor.value = await rescrapeActorImage(actor.value.id)
    imgFailed.value = false
    ElMessage.success('头像已更新')
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(msg || '头像刮削失败')
  } finally {
    imgLoading.value = false
  }
}

watch(
  () => props.id,
  () => {
    syncPageQuery(1)
    void load()
  },
)

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
    <div v-if="actor" class="hero">
      <img
        v-if="actor.image_url && !imgFailed"
        class="avatar"
        :src="actor.image_url"
        :alt="actor.name"
        @error="imgFailed = true"
      />
      <div v-else class="avatar mono" :style="monogramStyle(actor.name)">
        {{ monogramChar({ title: actor.name }) }}
      </div>
      <div class="info">
        <h1 class="page-title">{{ actor.name }}</h1>
        <p class="muted">{{ actor.media_count ?? total }} 部作品</p>
        <div class="hero-actions">
          <el-select :model-value="sort" size="small" style="width: 168px" @change="onSortChange">
            <el-option
              v-for="opt in MEDIA_SORT_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <el-button size="small" :loading="imgLoading" @click="onRescrapeImage">
            重新刮削头像
          </el-button>
        </div>
      </div>
    </div>
    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />
    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 18px;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border);
  flex-shrink: 0;
}
.mono {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 36px;
  color: var(--accent);
  background: var(--panel);
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}
.info {
  min-width: 0;
}
.info .page-title {
  margin-bottom: 4px;
}
.info .muted {
  margin: 0 0 10px;
}
</style>
