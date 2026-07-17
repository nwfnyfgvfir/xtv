<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import MediaCard from './MediaCard.vue'

withDefaults(
  defineProps<{
    items: MediaListItem[]
    emptyTitle?: string
    emptyHint?: string
  }>(),
  {
    emptyTitle: '暂无媒体',
    emptyHint: '请先添加媒体库并扫描本地 / strm 目录',
  },
)

const emit = defineEmits<{ refreshed: [MediaListItem] }>()

function onRefreshed(item: MediaListItem) {
  emit('refreshed', item)
}
</script>

<template>
  <div v-if="items.length" class="grid">
    <MediaCard v-for="item in items" :key="item.id" :item="item" @refreshed="onRefreshed" />
  </div>
  <div v-else class="empty">
    <div class="empty-mark">TV影院</div>
    <p>{{ emptyTitle }}</p>
    <p class="muted">{{ emptyHint }}</p>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
  gap: 16px;
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
}
.empty {
  margin-top: 48px;
  text-align: center;
  padding: 40px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--panel) 80%, transparent);
}
.empty-mark {
  font-family: var(--font-display);
  font-size: 32px;
  letter-spacing: 0.08em;
  color: var(--accent);
  opacity: 0.85;
  margin-bottom: 8px;
  font-weight: 700;
}
.empty p {
  margin: 6px 0;
}
</style>
