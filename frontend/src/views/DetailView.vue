<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import VideoPlayer from '@/components/VideoPlayer.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import {
  favoriteMedia,
  getMedia,
  playMedia,
  rescrapeMedia,
  unfavoriteMedia,
} from '@/api/media'
import type { MediaDetail, PlayInfo } from '@/api/types'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = defineProps<{ id: string }>()
const router = useRouter()
const item = ref<MediaDetail | null>(null)
const play = ref<PlayInfo | null>(null)
const loading = ref(false)
const playing = ref(false)
const imgFailed = ref(false)
const favLoading = ref(false)

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

async function onToggleFav() {
  if (!item.value) return
  favLoading.value = true
  try {
    item.value = item.value.favorited
      ? await unfavoriteMedia(item.value.id)
      : await favoriteMedia(item.value.id)
  } catch {
    ElMessage.error('收藏操作失败')
  } finally {
    favLoading.value = false
  }
}

onMounted(load)
watch(() => props.id, load)
</script>

<template>
  <div class="page">
    <div v-if="loading && !item" class="muted">加载中…</div>
    <div v-else-if="item" class="detail">
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
          <el-button :loading="favLoading" @click="onToggleFav">
            {{ item.favorited ? '取消收藏' : '收藏' }}
          </el-button>
          <el-button @click="onRescrape" :disabled="!item.number">重新刮削</el-button>
        </div>
        <div v-if="tags.length" class="tags">
          <el-tag v-for="t in tags" :key="t" size="small" effect="dark" class="tag">{{ t }}</el-tag>
        </div>
        <p v-if="item.plot" class="plot">{{ item.plot }}</p>
        <div v-if="item.actors?.length" class="actors">
          <h3>演员</h3>
          <div class="actor-list">
            <button
              v-for="a in item.actors"
              :key="a.id"
              type="button"
              class="actor"
              @click="router.push(`/actors/${a.id}`)"
            >
              <img v-if="a.image_url" :src="a.image_url" :alt="a.name" />
              <span v-else class="a-mono" :style="monogramStyle(a.name)">
                {{ monogramChar({ title: a.name }) }}
              </span>
              <span>{{ a.name }}</span>
            </button>
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
  background: var(--bg);
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
  flex-wrap: wrap;
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
  color: var(--text);
  margin: 0;
  opacity: 0.92;
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
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--panel);
  border: 1px solid var(--border);
  padding: 4px 12px 4px 4px;
  border-radius: 999px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}
.actor:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.actor img,
.a-mono {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  font-size: 12px;
  font-family: var(--font-display);
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
