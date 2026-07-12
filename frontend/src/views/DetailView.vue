<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import VideoPlayer from '@/components/VideoPlayer.vue'
import { getMedia, playMedia, rescrapeMedia } from '@/api/media'
import type { MediaDetail, PlayInfo } from '@/api/types'

const props = defineProps<{ id: string }>()
const item = ref<MediaDetail | null>(null)
const play = ref<PlayInfo | null>(null)
const loading = ref(false)
const playing = ref(false)

const tags = computed(() => {
  if (!item.value?.tags_json) return [] as string[]
  try {
    const v = JSON.parse(item.value.tags_json)
    return Array.isArray(v) ? v.map(String) : []
  } catch {
    return []
  }
})

async function load() {
  loading.value = true
  try {
    item.value = await getMedia(Number(props.id))
  } catch {
    ElMessage.error('加载详情失败')
  } finally {
    loading.value = false
  }
}

async function onPlay() {
  try {
    play.value = await playMedia(Number(props.id))
    playing.value = true
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(msg || '获取播放地址失败')
  }
}

async function onRescrape() {
  try {
    item.value = await rescrapeMedia(Number(props.id))
    ElMessage.success('刮削完成')
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(msg || '刮削失败')
  }
}

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div class="page" v-loading="loading">
    <div v-if="item" class="detail">
      <div class="left">
        <img v-if="item.cover_url" class="cover" :src="item.cover_url" :alt="item.title || ''" />
        <div v-else class="cover-placeholder big">No Cover</div>
      </div>
      <div class="right">
        <div class="number">{{ item.number || '未知番号' }}</div>
        <h1>{{ item.title || item.filename }}</h1>
        <p class="muted">
          <span v-if="item.provider">{{ item.provider }}</span>
          <span v-if="item.release_date"> · {{ item.release_date }}</span>
          <span v-if="item.studio"> · {{ item.studio }}</span>
          <span> · {{ item.source_type }}</span>
        </p>
        <div class="btns">
          <el-button type="primary" @click="onPlay">播放</el-button>
          <el-button @click="onRescrape" :disabled="!item.number">重新刮削</el-button>
        </div>
        <div v-if="tags.length" class="tags">
          <el-tag v-for="t in tags" :key="t" size="small" effect="dark" class="tag">{{ t }}</el-tag>
        </div>
        <p v-if="item.plot" class="plot">{{ item.plot }}</p>
        <div v-if="item.actors?.length" class="actors">
          <h3>演员</h3>
          <div class="actor-list">
            <span v-for="a in item.actors" :key="a.id" class="actor">{{ a.name }}</span>
          </div>
        </div>
        <p class="muted path">{{ item.path }}</p>
      </div>
    </div>

    <div v-if="playing && play" class="player-wrap">
      <VideoPlayer :media-id="Number(id)" :src="play.play_url" />
      <p class="muted">播放类型: {{ play.kind }}</p>
    </div>
  </div>
</template>

<style scoped>
.detail {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 24px;
}
@media (max-width: 720px) {
  .detail {
    grid-template-columns: 1fr;
  }
}
.cover {
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--border);
}
.big {
  min-height: 320px;
  border-radius: 12px;
}
.number {
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 0.04em;
}
h1 {
  margin: 6px 0 8px;
  font-size: 24px;
  line-height: 1.3;
}
.btns {
  display: flex;
  gap: 10px;
  margin: 14px 0;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.plot {
  white-space: pre-wrap;
  line-height: 1.6;
  color: #cfd3da;
}
.actors h3 {
  margin: 16px 0 8px;
  font-size: 15px;
}
.actor-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.actor {
  background: #222733;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
}
.path {
  margin-top: 16px;
  font-size: 12px;
  word-break: break-all;
}
.player-wrap {
  margin-top: 28px;
}
</style>
