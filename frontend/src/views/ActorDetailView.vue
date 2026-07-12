<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { getActor, listActorMedia } from '@/api/media'
import type { Actor, MediaListItem } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = defineProps<{ id: string }>()
const actor = ref<Actor | null>(null)
const items = ref<MediaListItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
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

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div class="page">
    <div v-if="actor" class="hero">
      <img v-if="actor.image_url" class="avatar" :src="actor.image_url" :alt="actor.name" />
      <div v-else class="avatar mono" :style="monogramStyle(actor.name)">
        {{ monogramChar({ title: actor.name }) }}
      </div>
      <div>
        <h1 class="page-title">{{ actor.name }}</h1>
        <p class="muted">{{ actor.media_count ?? items.length }} 部作品</p>
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
}
.avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border);
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
</style>
