<script setup lang="ts">
import type { MediaListItem } from '@/api/types'
import MediaCard from './MediaCard.vue'

defineProps<{ items: MediaListItem[] }>()
</script>

<template>
  <div v-if="items.length" class="grid">
    <MediaCard v-for="item in items" :key="item.id" :item="item" />
  </div>
  <el-empty v-else description="暂无媒体，请先添加媒体库并扫描" />
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
}
</style>
