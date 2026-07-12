<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import VideoPlayer from '@/components/VideoPlayer.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import { getMedia, playMedia, rescrapeMedia } from '@/api/media'
import type { MediaDetail, PlayInfo } from '@/api/types'

const props = defineProps<{ id: string }>()
const item = ref<MediaDetail | null>(null)
const play = ref<PlayInfo | null>(null)
const loading = ref(false)
const playing = ref(false)
const imgFailed = ref(false)

const tags = computed(() => {
  if (!item.value?.tags_json) return [] as string[]
  try {
    const v = JSON.parse(item.value.tags_json)
    return Array.isArray(v) ? v.map(String) : []
  } catch {
    return []
  }
})

const cover = computed(() => item.value?.cover_url || item.value?.thumb_url || '')
const showImage = computed(() => Boolean(cover.value) && !imgFailed.value)

async function load() {
  loading.value = true
  imgFailed.value = false
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
    imgFailed.value = false
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
        <img
          v-if="showImage"
          class="cover"
          :src="cover"
          :alt="item.title || ''"
          @error="imgFailed = true"
        />
        <CoverPlaceholder
          v-else
          size="lg"
          :number="item.number"
          :title="item.title"
          :filename="item.filename"
        />
      </div>
      <div class="right">
        <div class="number">{{ item.number || '未知番号' }}</div>
        <h1>{{ item.title || item.filename }}</h1>
        <p class="muted meta-line">
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
  grid-template-columns: 260px 1fr;
  gap: 28px;
  align-items: start;
}
@media (max-width: 720px) {
  .detail {
    grid-template-columns: 1fr;
  }
}
.cover {
  width: 100%;
  border-radius: 14px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-card);
  display: block;
  background: #0a0c10;
}
.number {
  font-family: var(--font-display);
  color: var(--accent);
  font-size: 22px;
  letter-spacing: 0.08em;
  text-shadow: 0 0 20px var(--accent-glow);
}
h1 {
  margin: 8px 0 10px;
  font-size: 26px;
  line-height: 1.3;
  font-weight: 600;
}
.meta-line {
  margin: 0;
}
.btns {
  display: flex;
  gap: 10px;
  margin: 16px 0;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.plot {
  white-space: pre-wrap;
  line-height: 1.7;
  color: #d4cfc4;
  margin: 0;
}
.actors h3 {
  margin: 18px 0 10px;
  font-size: 14px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
}
.actor-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.actor {
  background: var(--panel);
  border: 1px solid var(--border);
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 13px;
}
.path {
  margin-top: 18px;
  font-size: 12px;
  word-break: break-all;
}
.player-wrap {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
</style>
