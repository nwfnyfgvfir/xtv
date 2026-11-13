<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import { onActivated, onMounted, watch } from 'vue'
import { restoreListAnchor } from '@/utils/listScrollAnchor'
import MediaCard from './MediaCard.vue'

const props = withDefaults(
  defineProps<{
    items: MediaListItem[]
    emptyTitle?: string
    emptyHint?: string
  }>(),
  {
    emptyTitle: '这里还是空的',
    emptyHint: '添加一个媒体库并扫描本地 / strm 目录，影片会出现在这里',
  },
)

const emit = defineEmits<{ refreshed: [MediaListItem] }>()

function onRefreshed(item: MediaListItem) {
  emit('refreshed', item)
}

function tryRestore() {
  restoreListAnchor('media')
}

onMounted(tryRestore)
onActivated(tryRestore)
watch(
  () => props.items,
  () => tryRestore(),
  { flush: 'post' },
)
</script>

<template>
  <div v-if="items.length" class="grid">
    <MediaCard v-for="item in items" :key="item.id" :item="item" @refreshed="onRefreshed" />
  </div>
  <div v-else class="empty">
    <span class="empty-mark" aria-hidden="true">TV</span>
    <p class="empty-title">{{ emptyTitle }}</p>
    <p class="empty-hint muted">{{ emptyHint }}</p>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(164px, 1fr));
  gap: 28px 20px;
}
.empty {
  display: grid;
  justify-items: center;
  align-content: center;
  min-height: 300px;
  padding: 40px 24px;
  border: 1px dashed var(--border);
  border-radius: 12px;
  text-align: center;
}
.empty-mark {
  font-family: var(--font-display);
  font-size: 40px;
  color: var(--faint);
  letter-spacing: -0.08em;
  opacity: 0.5;
}
.empty-title {
  margin: 16px 0 6px;
  font-size: 16px;
  color: var(--text-soft);
}
.empty-hint {
  margin: 0;
  max-width: 36ch;
  font-size: 12px;
  line-height: 1.8;
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px 14px;
  }
}
</style>
