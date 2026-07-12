<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { getActor, listActorMedia, rescrapeActorImage } from '@/api/media'
import type { Actor, MediaListItem } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = defineProps<{ id: string }>()
const actor = ref<Actor | null>(null)
const items = ref<MediaListItem[]>([])
const loading = ref(false)
const imgLoading = ref(false)
const imgFailed = ref(false)

async function load() {
  loading.value = true
  imgFailed.value = false
  try {
    actor.value = await getActor(Number(props.id))
    const data = await listActorMedia(Number(props.id), { page: 1, page_size: 96 })
    items.value = data.items
  } catch {
    ElMessage.error('加载演员详情失败')
  } finally {
    loading.value = false
  }
}

async function onRescrapeImage() {
  if (!actor.value) return
  imgLoading.value = true
  try {
    actor.value = await rescrapeActorImage(actor.value.id)
    imgFailed.value = false
    ElMessage.success('头像已更新')
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(msg || '头像刮削失败')
  } finally {
    imgLoading.value = false
  }
}

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div class="page">
    <div v-if="actor" class="hero">
      <img
        v-if="actor.image_url && !imgFailed"
        class="avatar"
        :src="actor.image_url"
        :alt="actor.name"
        @error="imgFailed = true"
      />
      <div v-else class="avatar mono" :style="monogramStyle(actor.name)">
        {{ monogramChar({ title: actor.name }) }}
      </div>
      <div class="info">
        <h1 class="page-title">{{ actor.name }}</h1>
        <p class="muted">{{ actor.media_count ?? items.length }} 部作品</p>
        <el-button size="small" :loading="imgLoading" @click="onRescrapeImage">
          重新刮削头像
        </el-button>
      </div>
    </div>
    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />
  </div>
</template>

<style scoped>
.hero {
  display: flex;
  gap: 18px;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border);
  flex-shrink: 0;
}
.mono {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 36px;
  color: var(--accent);
  background: var(--panel);
}
.info {
  min-width: 0;
}
.info .page-title {
  margin-bottom: 4px;
}
.info .muted {
  margin: 0 0 10px;
}
</style>
