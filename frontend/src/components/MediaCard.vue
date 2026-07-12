<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CoverPlaceholder from './CoverPlaceholder.vue'
import { favoriteMedia, unfavoriteMedia } from '@/api/media'

const props = defineProps<{ item: MediaListItem }>()
const emit = defineEmits<{ refreshed: [MediaListItem] }>()
const router = useRouter()
const imgFailed = ref(false)
const favLoading = ref(false)
const favorited = ref(Boolean(props.item.favorited))

const title = computed(() => props.item.title || props.item.number || props.item.filename)
// Prefer portrait thumb for 2:3 cards; cover is often a landscape jacket.
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
  } catch {
    ElMessage.error('收藏操作失败')
  } finally {
    favLoading.value = false
  }
}
</script>

<template>
  <article class="card" @click="open" role="button" tabindex="0" @keyup.enter="open">
    <div class="poster">
      <img v-if="showImage" :src="cover" :alt="title" loading="lazy" @error="onImgError" />
      <CoverPlaceholder
        v-else
        :number="item.number"
        :title="item.title"
        :filename="item.filename"
      />
      <button class="fav" type="button" :disabled="favLoading" @click="toggleFav">
        {{ favorited ? '♥' : '♡' }}
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
  aspect-ratio: 2 / 3;
  object-fit: contain;
  object-position: center center;
  display: block;
  background: var(--bg);
}
.fav {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  border: 0;
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: var(--accent);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
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
</style>
