<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import CoverPlaceholder from './CoverPlaceholder.vue'

const props = defineProps<{ item: MediaListItem }>()
const router = useRouter()
const imgFailed = ref(false)

const title = computed(() => props.item.title || props.item.number || props.item.filename)
const cover = computed(() => props.item.cover_url || props.item.thumb_url || '')
const showImage = computed(() => Boolean(cover.value) && !imgFailed.value)

watch(cover, () => {
  imgFailed.value = false
})

function open() {
  router.push(`/media/${props.item.id}`)
}

function onImgError() {
  imgFailed.value = true
}
</script>

<template>
  <article class="card" @click="open" role="button" tabindex="0" @keyup.enter="open">
    <div class="poster">
      <img
        v-if="showImage"
        :src="cover"
        :alt="title"
        loading="lazy"
        @error="onImgError"
      />
      <CoverPlaceholder
        v-else
        :number="item.number"
        :title="item.title"
        :filename="item.filename"
      />
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
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}
.card:hover,
.card:focus-visible {
  transform: translateY(-3px);
  border-color: rgba(232, 168, 56, 0.45);
  box-shadow:
    0 14px 32px rgba(0, 0, 0, 0.45),
    0 0 0 1px rgba(232, 168, 56, 0.12);
  outline: none;
}
.poster {
  position: relative;
  background: #0a0c10;
}
.poster img {
  width: 100%;
  aspect-ratio: 2 / 3;
  object-fit: cover;
  display: block;
  background: #111;
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
  top: 8px;
  right: 8px;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.65);
  color: var(--muted);
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
