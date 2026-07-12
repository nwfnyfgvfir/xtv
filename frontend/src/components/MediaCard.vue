<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{ item: MediaListItem }>()
const router = useRouter()

const title = computed(() => props.item.title || props.item.number || props.item.filename)
const cover = computed(() => props.item.cover_url || props.item.thumb_url || '')

function open() {
  router.push(`/media/${props.item.id}`)
}
</script>

<template>
  <div class="card" @click="open">
    <div class="poster">
      <img v-if="cover" :src="cover" :alt="title" loading="lazy" />
      <div v-else class="cover-placeholder">{{ item.number || 'No Cover' }}</div>
      <span v-if="item.number" class="badge">{{ item.number }}</span>
    </div>
    <div class="meta">
      <div class="title" :title="title">{{ title }}</div>
      <div class="sub muted">{{ item.source_type }}</div>
    </div>
  </div>
</template>

<style scoped>
.card {
  cursor: pointer;
  border-radius: 12px;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.card:hover {
  transform: translateY(-2px);
  border-color: #3d4555;
}
.poster {
  position: relative;
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
  background: rgba(0, 0, 0, 0.72);
  color: var(--accent);
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
}
.meta {
  padding: 10px;
}
.title {
  font-size: 13px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.7em;
}
.sub {
  margin-top: 4px;
  font-size: 12px;
}
</style>
