<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CoverPlaceholder from './CoverPlaceholder.vue'
import { favoriteMedia, unfavoriteMedia } from '@/api/media'
import { getErrorMessage } from '@/utils/errors'

const props = defineProps<{ item: MediaListItem }>()
const emit = defineEmits<{ refreshed: [MediaListItem] }>()
const router = useRouter()
const imgFailed = ref(false)
const favLoading = ref(false)
const favorited = ref(Boolean(props.item.favorited))

const title = computed(() => props.item.title || props.item.number || props.item.filename)
// Prefer portrait thumb for 3:4 cards; cover is often a landscape jacket.
const cover = computed(() => props.item.thumb_url || props.item.cover_url || '')
const showImage = computed(() => Boolean(cover.value) && !imgFailed.value)
const isChineseSub = computed(() => props.item.subtitle_flag === 'C')

watch(
  () => props.item.favorited,
  (v) => {
    favorited.value = Boolean(v)
  },
)
watch(cover, () => {
  imgFailed.value = false
})

function open() {
  router.push(`/media/${props.item.id}`)
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
  <article class="card" @click="open" role="button" tabindex="0" @keyup.enter="open">
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
      <button
        class="fav"
        type="button"
        :class="{ on: favorited, loading: favLoading }"
        :disabled="favLoading"
        :aria-label="favorited ? '取消收藏' : '收藏'"
        :aria-pressed="favorited"
        @click="toggleFav"
      >
        <span v-if="favLoading" class="fav-spin" aria-hidden="true" />
        <svg
          v-else
          class="fav-icon"
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
        >
          <path
            v-if="favorited"
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
      </button>
      <span v-if="isChineseSub" class="sub-badge">中字</span>
      <span v-if="item.number" class="badge">{{ item.number }}</span>
      <span v-if="!item.scraped_at" class="chip">未刮削</span>
    </div>
    <div class="meta">
      <div class="title" :title="title">{{ title }}</div>
      <div class="sub muted">{{ item.source_type }}</div>
    </div>
  </article>
</template>

<style scoped>
.card {
  cursor: pointer;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-card);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.card:hover,
.card:focus-visible {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  outline: none;
}
.poster {
  position: relative;
  background: var(--bg);
}
.poster img {
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  object-position: center center;
  display: block;
  background: var(--bg);
}
.fav {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  border: 1px solid rgba(255, 255, 255, 0.12);
  width: 40px;
  height: 40px;
  min-width: 40px;
  border-radius: 999px;
  background: rgba(8, 10, 14, 0.58);
  backdrop-filter: blur(6px);
  color: var(--text);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition:
    transform 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}
.fav:hover:not(:disabled) {
  transform: scale(1.08);
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  box-shadow: 0 0 14px var(--accent-glow);
}
.fav.on {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: color-mix(in srgb, var(--accent) 18%, rgba(8, 10, 14, 0.65));
  box-shadow: 0 0 12px var(--accent-glow);
}
.fav:disabled {
  opacity: 0.75;
  cursor: wait;
}
.fav-icon {
  display: block;
}
.fav-spin {
  width: 16px;
  height: 16px;
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
.sub-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 3;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 3px 7px;
  border-radius: 6px;
  background: var(--accent);
  color: #1a1205;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
.badge {
  position: absolute;
  left: 8px;
  bottom: 8px;
  background: rgba(8, 10, 14, 0.82);
  color: var(--accent);
  font-family: var(--font-display);
  font-size: 13px;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid rgba(232, 168, 56, 0.25);
  z-index: 2;
}
.chip {
  position: absolute;
  bottom: 8px;
  right: 8px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.65);
  color: #ddd;
  border: 1px solid var(--border);
  z-index: 2;
}
.meta {
  padding: 11px 12px 12px;
}
.title {
  font-size: 13.5px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.7em;
  color: var(--text);
}
.sub {
  margin-top: 4px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
@media (max-width: 640px) {
  .poster img {
    aspect-ratio: 1;
  }
  :deep(.cover-placeholder) {
    aspect-ratio: 1;
  }
  .fav {
    width: 34px;
    height: 34px;
    min-width: 34px;
    top: 6px;
    left: 6px;
  }
  .fav-icon {
    width: 15px;
    height: 15px;
  }
  .meta {
    padding: 8px 8px 10px;
  }
  .title {
    font-size: 12.5px;
    min-height: 2.5em;
  }
  .sub {
    font-size: 11px;
  }
  .badge {
    font-size: 11px;
    padding: 2px 6px;
  }
}
</style>
