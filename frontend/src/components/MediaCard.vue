<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CoverPlaceholder from './CoverPlaceholder.vue'
import { favoriteMedia, unfavoriteMedia } from '@/api/media'
import { getErrorMessage } from '@/utils/errors'
import { rememberListAnchor } from '@/utils/listScrollAnchor'

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
const score = computed(() =>
  typeof props.item.score === 'number' ? props.item.score.toFixed(1) : '',
)
const year = computed(() => (props.item.release_date || '').slice(0, 4))
// Prefer something human-readable over the raw "local"/"strm" token.
const metaText = computed(() => {
  const parts = [year.value, score.value ? `★ ${score.value}` : ''].filter(Boolean)
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

function open() {
  rememberListAnchor('media', props.item.id)
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
  <article
    class="card"
    :data-media-id="item.id"
    role="button"
    tabindex="0"
    @click="open"
    @keyup.enter="open"
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
        <svg v-else class="fav-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path
            v-if="favorited"
            fill="currentColor"
            stroke="none"
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

      <div class="foot">
        <span v-if="item.number" class="tag-num num">{{ item.number }}</span>
        <span v-if="!item.scraped_at" class="tag-pending">未刮削</span>
      </div>
    </div>

    <div class="meta">
      <div class="title" :title="title">{{ title }}</div>
      <div class="sub num">{{ metaText }}</div>
    </div>
  </article>
</template>

<style scoped>
.card {
  cursor: pointer;
  min-width: 0;
  /* GPU layer + clip: avoids 1px light fringe on rounded corners */
  transform: translateZ(0);
  backface-visibility: hidden;
}

/* The poster IS the card. No chrome, no border box — just the artwork
   lifted off the backdrop, with a hairline ring that turns gold on hover. */
.poster {
  position: relative;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-elevated);
  /* Component-level container: the card adapts to its own width, not the
     viewport — the same card works in a 3-up phone grid and a wide desktop one. */
  container-type: inline-size;
  box-shadow:
    var(--shadow-sm),
    0 0 0 1px var(--border-subtle);
  transition:
    transform var(--dur-3) var(--ease-out),
    box-shadow var(--dur-3) var(--ease-out);
}
.card:hover .poster,
.card:focus-visible .poster {
  transform: translateY(-4px);
  box-shadow:
    var(--shadow-lg),
    0 0 0 1px var(--accent-line);
}
.card:focus-visible {
  outline: none;
}

/* Cinematic scrim: keeps badges legible over any artwork, deepens on hover. */
.poster::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 1;
  background: var(--scrim);
  opacity: 0.5;
  transition: opacity var(--dur-3) var(--ease-out);
  pointer-events: none;
}
.card:hover .poster::after {
  opacity: 0.9;
}

.poster img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center center;
  /* Crop thin white margins common in scraped package art */
  transform: scale(1.04);
  transform-origin: center center;
  background: var(--bg-elevated);
  transition: transform var(--dur-4) var(--ease-out);
}
.card:hover .poster img {
  transform: scale(1.07);
}
.poster :deep(.cover-placeholder) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  aspect-ratio: auto;
  border: none;
  border-radius: 0;
}

.fav {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  z-index: 3;
  border: 1px solid oklch(100% 0 0 / 0.14);
  width: 34px;
  height: 34px;
  min-width: 34px;
  border-radius: var(--radius-full);
  background: oklch(12% 0.01 75 / 0.6);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: var(--ink-100);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  opacity: 0;
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
/* Reveal on hover, but never hide an already-favourited item. */
.card:hover .fav,
.card:focus-within .fav,
.fav.on,
.fav:focus-visible {
  opacity: 1;
}
.fav:hover:not(:disabled) {
  transform: scale(1.1);
  color: var(--accent);
}
.fav.on {
  color: var(--accent);
  background: color-mix(in oklab, var(--gold-600) 42%, oklch(12% 0.01 75 / 0.72));
}
.fav:disabled {
  opacity: 1;
  cursor: wait;
}
.fav-icon {
  display: block;
}
.fav-spin {
  width: 15px;
  height: 15px;
  border: 2px solid color-mix(in oklab, var(--accent) 35%, transparent);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: fav-rotate 0.7s linear infinite;
}
@keyframes fav-rotate {
  to {
    transform: rotate(360deg);
  }
}

/* Top-left: the single most useful signal for this library. */
.tag-sub {
  position: absolute;
  top: var(--space-2);
  left: var(--space-2);
  z-index: 3;
  font-size: var(--text-2xs);
  font-weight: 700;
  letter-spacing: var(--tracking-wide);
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--on-accent);
}

/* Bottom row sits on the scrim: 番号 left, status right. */
.foot {
  position: absolute;
  left: var(--space-2);
  right: var(--space-2);
  bottom: var(--space-2);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  pointer-events: none;
}
.tag-num {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--gold-300);
  text-shadow: 0 1px 6px oklch(0% 0 0 / 0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag-pending {
  flex-shrink: 0;
  font-size: var(--text-2xs);
  padding: 2px 7px;
  border-radius: var(--radius-full);
  background: oklch(12% 0.01 75 / 0.7);
  color: var(--ink-200);
  border: 1px solid oklch(100% 0 0 / 0.14);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

/* Narrow cards (3-up phone grid): the 番号 is the identifier, so it wins the
   space. The missing poster already signals "unscraped" visually. */
@container (max-width: 134px) {
  .tag-pending {
    display: none;
  }
}

.meta {
  padding: var(--space-3) 2px 0;
}
.title {
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.7em;
  color: var(--text-soft);
  transition: color var(--dur-2) var(--ease-out);
}
.card:hover .title {
  color: var(--text);
}
.sub {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--faint);
}

@media (max-width: 640px) {
  .fav {
    width: 30px;
    height: 30px;
    min-width: 30px;
    top: 6px;
    right: 6px;
  }
  .fav-icon {
    width: 15px;
    height: 15px;
  }
  .tag-sub {
    top: 6px;
    left: 6px;
    padding: 2px 6px;
  }
  .foot {
    left: 6px;
    right: 6px;
    bottom: 6px;
  }
  .meta {
    padding-top: var(--space-2);
  }
  .title {
    font-size: var(--text-xs);
  }
  .tag-num {
    font-size: var(--text-xs);
  }
}

/* Touch devices have no hover — keep the favourite affordance visible. */
@media (hover: none) {
  .fav {
    opacity: 1;
  }
}
</style>
