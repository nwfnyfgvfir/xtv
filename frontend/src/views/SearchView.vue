<script setup lang="ts">
import { ref } from 'vue'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { listLibraries, listMedia } from '@/api/media'
import type { Library, MediaListItem, MediaSort } from '@/api/types'
import { ElMessage } from 'element-plus'
import { onMounted } from 'vue'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'

const q = ref('')
const libraryId = ref<number | null>(null)
const libraries = ref<Library[]>([])
const items = ref<MediaListItem[]>([])
const sort = ref<MediaSort>(loadMediaSort())
const loading = ref(false)
const searched = ref(false)

onMounted(async () => {
  try {
    libraries.value = await listLibraries()
  } catch {
    /* ignore */
  }
})

async function search() {
  loading.value = true
  searched.value = true
  try {
    const data = await listMedia({
      q: q.value || undefined,
      library_id: libraryId.value || undefined,
      sort: sort.value,
      page: 1,
      page_size: 60,
    })
    items.value = data.items
  } catch {
    ElMessage.error('搜索失败')
  } finally {
    loading.value = false
  }
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  if (searched.value) void search()
}
</script>

<template>
  <div class="page">
    <h1 class="page-title">搜索</h1>
    <p class="muted intro">按番号、标题或文件名查找；可限定媒体库</p>
    <div class="bar">
      <el-select
        v-model="libraryId"
        clearable
        placeholder="全部媒体库"
        style="width: 180px"
      >
        <el-option
          v-for="lib in libraries"
          :key="lib.id"
          :label="lib.name"
          :value="lib.id"
        />
      </el-select>
      <el-select :model-value="sort" style="width: 168px" @change="onSortChange">
        <el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
      <el-input
        v-model="q"
        placeholder="番号 / 标题 / 文件名"
        clearable
        @keyup.enter="search"
      />
      <el-button type="primary" :loading="loading" @click="search">搜索</el-button>
    </div>
    <SkeletonGrid v-if="loading && !items.length" :count="8" />
    <MediaGrid v-else-if="searched || items.length" :items="items" />
    <p v-else class="muted tip">输入关键词后回车或点击搜索</p>
  </div>
</template>

<style scoped>
.intro {
  margin: -4px 0 16px;
  font-size: 13px;
}
.bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  max-width: 760px;
  flex-wrap: wrap;
}
.tip {
  margin-top: 24px;
}
</style>
