<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import MediaCard from './MediaCard.vue'

defineProps<{ items: MediaListItem[] }>()
</script>

<template>
  <div v-if="items.length" class="grid">
    <MediaCard v-for="item in items" :key="item.id" :item="item" />
  </div>
  <div v-else class="empty">
    <div class="empty-mark">TV</div>
    <p>暂无媒体</p>
    <p class="muted">请先添加媒体库并扫描本地 / strm 目录</p>
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
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 10px;
  }
}
.empty {
  margin-top: 48px;
  text-align: center;
  padding: 40px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: rgba(20, 24, 32, 0.5);
}
.empty-mark {
  font-family: var(--font-display);
  font-size: 42px;
  letter-spacing: 0.2em;
  color: var(--accent);
  opacity: 0.85;
  margin-bottom: 8px;
}
.empty p {
  margin: 6px 0;
}
</style>
