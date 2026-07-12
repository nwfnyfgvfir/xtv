<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listFavorites } from '@/api/media'
import type { MediaListItem, MediaSort } from '@/api/types'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'

const items = ref<MediaListItem[]>([])
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await listFavorites({ page: 1, page_size: 96, sort: sort.value })
    items.value = data.items
  } catch {
    ElMessage.error('加载收藏失败')
  } finally {
    loading.value = false
  }
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  void load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="head">
      <div>
        <h1 class="page-title">收藏</h1>
        <p class="muted intro">已收藏的作品</p>
      </div>
      <el-select :model-value="sort" size="small" style="width: 168px" @change="onSortChange">
        <el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
    </div>
    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
</style>
