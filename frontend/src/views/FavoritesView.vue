<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listFavorites } from '@/api/media'
import type { MediaListItem } from '@/api/types'

const items = ref<MediaListItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await listFavorites({ page: 1, page_size: 96 })
    items.value = data.items
  } catch {
    ElMessage.error('加载收藏失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h1 class="page-title">收藏</h1>
    <p class="muted intro">已收藏的作品</p>
    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />
  </div>
</template>

<style scoped>
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
</style>
