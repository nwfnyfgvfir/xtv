<script setup lang="ts">
import { ref } from 'vue'
import MediaGrid from '@/components/MediaGrid.vue'
import { listMedia } from '@/api/media'
import type { MediaListItem } from '@/api/types'
import { ElMessage } from 'element-plus'

const q = ref('')
const items = ref<MediaListItem[]>([])
const loading = ref(false)
const searched = ref(false)

async function search() {
  loading.value = true
  searched.value = true
  try {
    const data = await listMedia({ q: q.value || undefined, page: 1, page_size: 60 })
    items.value = data.items
  } catch {
    ElMessage.error('搜索失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page" v-loading="loading">
    <h1 class="page-title">搜索</h1>
    <p class="muted intro">按番号、标题或文件名查找</p>
    <div class="bar">
      <el-input
        v-model="q"
        placeholder="番号 / 标题 / 文件名"
        clearable
        @keyup.enter="search"
      />
      <el-button type="primary" @click="search">搜索</el-button>
    </div>
    <MediaGrid v-if="searched || items.length" :items="items" />
    <p v-else class="muted tip">输入关键词后回车或点击搜索</p>
  </div>
</template>

<style scoped>
.intro {
  margin: -8px 0 16px;
  font-size: 13px;
}
.bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  max-width: 640px;
}
.tip {
  margin-top: 24px;
}
</style>
