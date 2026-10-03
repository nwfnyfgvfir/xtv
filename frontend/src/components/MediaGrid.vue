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
  grid-template-columns: repeat(auto-fill, minmax(166px, 1fr));
  gap: var(--space-6) var(--space-4);
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-4) var(--space-2);
  }
}
@media (max-width: 380px) {
  .grid {
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3) 6px;
  }
}

/* Empty state: teach, don't just announce emptiness. */
.empty {
  margin-top: var(--space-12);
  padding: var(--space-12) var(--space-4);
  text-align: center;
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border);
  background: color-mix(in oklab, var(--panel) 55%, transparent);
}
.empty-mark {
  display: block;
  font-family: var(--font-serif);
  font-size: var(--text-4xl);
  line-height: 1;
  letter-spacing: var(--tracking-tight);
  color: var(--accent);
  opacity: 0.5;
}
.empty-title {
  margin: var(--space-4) 0 var(--space-1);
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--text);
}
.empty-hint {
  margin: 0 auto;
  max-width: 42ch;
  font-size: var(--text-sm);
}
</style>
