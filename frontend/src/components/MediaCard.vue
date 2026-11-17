<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import CoverPlaceholder from './CoverPlaceholder.vue'
import AppIcon from './AppIcon.vue'
import { favoriteMedia, unfavoriteMedia } from '@/api/media'
import { getErrorMessage } from '@/utils/errors'
import { rememberListAnchor } from '@/utils/listScrollAnchor'

const props = defineProps<{ item: MediaListItem }>()
const emit = defineEmits<{ refreshed: [MediaListItem] }>()
const imgFailed = ref(false)
const favLoading = ref(false)
const favorited = ref(Boolean(props.item.favorited))

const title = computed(() => props.item.title || props.item.number || props.item.filename)
// Prefer portrait thumb for 3:4 cards; cover is often a landscape jacket.
const cover = computed(() => props.item.thumb_url || props.item.cover_url || '')
const showImage = computed(() => Boolean(cover.value) && !imgFailed.value)
const isChineseSub = computed(() => props.item.subtitle_flag === 'C')
const score = computed(() =>
  typeof props.item.score === 'number' ? props.item.score.toFixed(1) : '',
)
const year = computed(() => (props.item.release_date || '').slice(0, 4))
// Prefer something human-readable over the raw "local"/"strm" token.
const metaText = computed(() => {
  const parts = [year.value, props.item.source_type === 'local' ? '本地' : 'STRM'].filter(Boolean)
  return parts.length ? parts.join('  ') : props.item.source_type
})

watch(
  () => props.item.favorited,
  (v) => {
    favorited.value = Boolean(v)
  },
)
watch(cover, () => {
  imgFailed.value = false
})

function onOpen() {
  rememberListAnchor('media', props.item.id)
}

function onImgError() {
  imgFailed.value = true
}

async function toggleFav(e: Event) {
  e.stopPropagation()
  favLoading.value = true
  try {
    const res = favorited.value
      ? await unfavoriteMedia(props.item.id)
      : await favoriteMedia(props.item.id)
    favorited.value = Boolean(res.favorited)
    emit('refreshed', res)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '收藏操作失败'))
  } finally {
    favLoading.value = false
  }
}
</script>

<template>
  <article class="card" :data-media-id="item.id">
    <router-link
      :to="`/media/${item.id}`"
      class="card-link"
      :aria-label="`查看影片 ${item.number || ''} ${title}`"
      @click="onOpen"
    >
      <div class="poster">
        <img
          v-if="showImage"
          :src="cover"
          :alt="title"
          width="200"
          height="267"
          loading="lazy"
          decoding="async"
          @error="onImgError"
        />
        <CoverPlaceholder
          v-else
          :number="item.number"
          :title="item.title"
          :filename="item.filename"
        />
        <span v-if="isChineseSub" class="tag-sub">中字</span>
        <span v-if="!item.scraped_at" class="tag-pending">待刮削</span>
        <span v-if="score" class="poster-score"><AppIcon name="star" :size="12" />{{ score }}</span>
        <span class="hover-action"><AppIcon name="external" :size="16" />查看详情</span>
      </div>
      <div class="meta">
        <span class="media-number" :title="item.filename">{{ item.number || item.filename }}</span>
        <h3 class="title" :title="title">{{ title }}</h3>
        <p class="sub">{{ metaText }}</p>
      </div>
    </router-link>
    <button
      class="fav"
      type="button"
      :class="{ on: favorited }"
      :disabled="favLoading"
      :aria-label="favorited ? '取消收藏' : '收藏'"
      :aria-pressed="favorited"
      @click="toggleFav"
    >
      <span v-if="favLoading" class="fav-spin" aria-hidden="true" />
      <AppIcon v-else name="heart" :size="17" />
    </button>
  </article>
</template>
<style scoped>
.card {
  min-width: 0;
  position: relative;
}
.card-link {
  display: block;
  border-radius: var(--radius-md);
}
.poster {
  position: relative;
  overflow: hidden;
  aspect-ratio: 3 / 4;
  background: var(--bg-elevated);
  border-radius: 10px;
  isolation: isolate;
}
.poster > img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.card-link:focus-visible {
  outline-offset: 5px;
}
.tag-sub,
.tag-pending,
.poster-score {
  position: absolute;
  z-index: 2;
  font-size: 10px;
  font-weight: 600;
  padding: 3px 7px;
  line-height: 1.5;
  border-radius: 4px;
  color: #f0f7f3;
  background: #0d171cba;
}
.tag-sub {
  top: 9px;
  left: 9px;
  color: #b4f5d7;
}
.tag-pending {
  bottom: 9px;
  left: 9px;
  font-weight: 400;
}
.poster-score {
  right: 9px;
  bottom: 9px;
  display: inline-flex;
  gap: 4px;
  align-items: center;
  font-variant-numeric: tabular-nums;
}
.poster-score :deep(svg) {
  color: #e6c68d;
  fill: #e6c68d;
}
.hover-action {
  position: absolute;
  z-index: 3;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -40%);
  opacity: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  color: #f2fff8;
  background: #10241edb;
  border: 1px solid #ffffff26;
  padding: 9px 14px;
  border-radius: 7px;
  font-size: 12px;
  transition:
    opacity var(--dur-2),
    transform var(--dur-2);
}
.card-link:hover .hover-action,
.card-link:focus-visible .hover-action {
  opacity: 1;
  transform: translate(-50%, -50%);
}
.fav {
  position: absolute;
  right: 8px;
  top: 8px;
  z-index: 4;
  display: grid;
  place-items: center;
  width: 33px;
  height: 33px;
  border: 0;
  border-radius: 7px;
  background: #102027c9;
  color: #e8f1ec;
  opacity: 0;
  cursor: pointer;
  transition:
    opacity var(--dur-2),
    background-color var(--dur-2);
}
.card:hover .fav,
.card:focus-within .fav,
.fav.on,
.fav:disabled {
  opacity: 1;
}
.fav:hover {
  background: #173b30;
  color: #b2efd0;
}
.fav.on {
  color: #b2efd0;
  background: #16362be6;
}
.fav.on :deep(svg) {
  fill: currentColor;
}
.fav:disabled {
  cursor: wait;
}
.fav-spin {
  width: 15px;
  height: 15px;
  border: 2px solid #b2efd044;
  border-top-color: #b2efd0;
  border-radius: 50%;
  animation: fav-spin 0.7s linear infinite;
}
@keyframes fav-spin {
  to {
    transform: rotate(360deg);
  }
}
.meta {
  padding: 13px 1px 0;
}
.media-number {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: var(--text-soft);
  font-family: var(--font-mono);
  letter-spacing: 0.015em;
  font-size: 13px;
  font-weight: 600;
}
.title {
  color: var(--muted);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 3.2em;
  margin: 5px 0 0;
}
.card-link:hover .title {
  color: var(--text-soft);
}
.sub {
  color: var(--faint);
  font-size: 11px;
  margin: 7px 0 0;
  letter-spacing: 0.025em;
}
@media (hover: none) {
  .fav {
    opacity: 1;
    width: 44px;
    height: 44px;
  }
  .hover-action {
    display: none;
  }
}
@media (max-width: 640px) {
  .meta {
    padding-top: 11px;
  }
  .title {
    font-size: 12px;
  }
  .media-number {
    font-size: 12px;
  }
}
</style>
