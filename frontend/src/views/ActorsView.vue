<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listActors } from '@/api/media'
import type { Actor } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const router = useRouter()
const items = ref<Actor[]>([])
const total = ref(0)
const page = ref(1)
const q = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await listActors({ q: q.value || undefined, page: page.value, page_size: 48 })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载演员失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h1 class="page-title">演员</h1>
    <div class="bar">
      <el-input v-model="q" placeholder="搜索演员" clearable @keyup.enter="load" />
      <el-button type="primary" :loading="loading" @click="load">搜索</el-button>
    </div>
    <div v-if="loading && !items.length" class="muted">加载中…</div>
    <div v-else-if="items.length" class="grid">
      <button
        v-for="a in items"
        :key="a.id"
        class="actor-card"
        type="button"
        @click="router.push(`/actors/${a.id}`)"
      >
        <img v-if="a.image_url" :src="a.image_url" :alt="a.name" loading="lazy" />
        <div v-else class="mono" :style="monogramStyle(a.name)">
          {{ monogramChar({ title: a.name }) }}
        </div>
        <div class="info">
          <div class="name">{{ a.name }}</div>
          <div class="muted count">{{ a.media_count ?? 0 }} 部作品</div>
        </div>
      </button>
    </div>
    <el-empty v-else description="暂无演员，请先刮削媒体" />
    <div v-if="total > 48" class="pager">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="48"
        v-model:current-page="page"
        @current-change="load"
      />
    </div>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  gap: 10px;
  max-width: 520px;
  margin-bottom: 18px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
}
.actor-card {
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  padding: 0;
  text-align: left;
  color: inherit;
  box-shadow: var(--shadow-card);
}
.actor-card:hover {
  border-color: var(--accent);
}
.actor-card img,
.mono {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 42px;
  color: var(--accent);
  background: var(--bg-elevated);
}
.info {
  padding: 10px;
}
.name {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.count {
  font-size: 12px;
  margin-top: 2px;
}
.pager {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
