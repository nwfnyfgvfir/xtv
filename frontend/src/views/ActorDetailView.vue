<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import {
  favoriteActor,
  getActor,
  listActorMedia,
  rescrapeActorImage,
  unfavoriteActor,
} from '@/api/media'
import type { Actor, MediaListItem, MediaSort } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
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
const favLoading = ref(false)
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
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载演员详情失败'))
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
    ElMessage.error(getErrorMessage(e, '头像刮削失败'))
  } finally {
    imgLoading.value = false
  }
}

async function onToggleFav() {
  if (!actor.value) return
  favLoading.value = true
  try {
    actor.value = actor.value.favorited
      ? await unfavoriteActor(actor.value.id)
      : await favoriteActor(actor.value.id)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '收藏操作失败'))
  } finally {
    favLoading.value = false
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
          <button
            type="button"
            class="btn-fav"
            :class="{ on: actor.favorited, loading: favLoading }"
            :disabled="favLoading"
            :aria-pressed="actor.favorited"
            @click="onToggleFav"
          >
            <span v-if="favLoading" class="btn-spin" aria-hidden="true" />
            <svg v-else class="btn-ico" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path
                v-if="actor.favorited"
                fill="currentColor"
                d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
              />
              <path
                v-else
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                d="M12.1 8.64l-.1.1-.11-.11C10.14 6.6 7.1 6.48 5.4 8.2c-1.7 1.72-1.6 4.46.2 6.06L12 20.5l6.4-6.24c1.8-1.6 1.9-4.34.2-6.06-1.7-1.72-4.74-1.6-6.5.44z"
              />
            </svg>
            <span>{{ actor.favorited ? '已收藏' : '收藏' }}</span>
          </button>
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
.btn-fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  min-width: 96px;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease,
    color 0.15s ease;
}
.btn-fav:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  color: var(--accent);
  background: var(--accent-soft);
}
.btn-fav.on {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
  background: var(--accent-soft);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent);
}
.btn-fav:disabled {
  opacity: 0.75;
  cursor: wait;
}
.btn-ico {
  display: block;
  flex-shrink: 0;
}
.btn-spin {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--accent) 35%, transparent);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: fav-rotate 0.7s linear infinite;
}
@keyframes fav-rotate {
  to {
    transform: rotate(360deg);
  }
}
.info {
  min-width: 0;
  flex: 1 1 200px;
}
.info .page-title {
  margin-bottom: 4px;
}
.info .muted {
  margin: 0 0 10px;
}
@media (max-width: 640px) {
  .hero {
    gap: 12px;
  }
  .avatar {
    width: 80px;
    height: 80px;
  }
  .hero-actions {
    width: 100%;
  }
  .hero-actions :deep(.el-select) {
    flex: 1 1 140px;
    min-width: 0;
  }
}
</style>
