<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import VideoPlayer from '@/components/VideoPlayer.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import ExternalPlayersBar from '@/components/ExternalPlayersBar.vue'
import {
  deleteMedia,
  favoriteMedia,
  getMedia,
  getSettings,
  playMedia,
  rescrapeMedia,
  translateMedia,
  unfavoriteMedia,
} from '@/api/media'
import type { MediaDetail, PlayInfo } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = defineProps<{ id: string }>()
const router = useRouter()
const item = ref<MediaDetail | null>(null)
const play = ref<PlayInfo | null>(null)
const loading = ref(false)
const playing = ref(false)
const imgFailed = ref(false)
const favLoading = ref(false)
const playLoading = ref(false)
const scrapeLoading = ref(false)
const translateLoading = ref(false)
const deleteLoading = ref(false)
const providers = ref<string[]>([])
const scrapeProvider = ref('')
const scrapeFallback = ref(true)
const scrapeNumber = ref('')
const playerWrap = ref<HTMLElement | null>(null)

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
const isChineseSub = computed(
  () => item.value?.subtitle_flag === 'C' || tags.value.includes('中文字幕'),
)
const canRescrape = computed(() =>
  Boolean((scrapeNumber.value || item.value?.number || '').trim()),
)
const isLocal = computed(() => item.value?.source_type === 'local')
const canTranslate = computed(() => {
  if (!item.value) return false
  if ((item.value.title || '').trim() || (item.value.plot || '').trim()) return true
  return tags.value.length > 0
})

function syncScrapeNumber() {
  scrapeNumber.value = item.value?.number || ''
}

async function load() {
  loading.value = true
  imgFailed.value = false
  playing.value = false
  play.value = null
  try {
    item.value = await getMedia(Number(props.id))
    syncScrapeNumber()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载详情失败'))
  } finally {
    loading.value = false
  }
}

async function loadProviders() {
  try {
    const s = await getSettings()
    const list = [...(s.movie_providers || [])]
    const pri = s.metatube_provider_priority || []
    for (const p of pri) {
      if (p && !list.includes(p)) list.push(p)
    }
    if (s.metatube_provider && !list.includes(s.metatube_provider)) {
      list.push(s.metatube_provider)
    }
    providers.value = list
    scrapeProvider.value = pri[0] || s.metatube_provider || ''
    scrapeFallback.value = s.metatube_fallback !== false
  } catch {
    /* ignore */
  }
}

async function onPlay() {
  playLoading.value = true
  try {
    play.value = await playMedia(Number(props.id))
    playing.value = true
    await nextTick()
    playerWrap.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '获取播放地址失败'))
  } finally {
    playLoading.value = false
  }
}

async function onRescrape() {
  const number = (scrapeNumber.value || item.value?.number || '').trim()
  if (!number) {
    ElMessage.warning('请先填写番号')
    return
  }
  scrapeLoading.value = true
  try {
    item.value = await rescrapeMedia(Number(props.id), {
      // Always send provider (including "") so「自动」does not inherit global preferred source.
      provider: scrapeProvider.value,
      fallback: scrapeFallback.value,
      number,
    })
    syncScrapeNumber()
    imgFailed.value = false
    ElMessage.success('刮削完成')
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '刮削失败'))
  } finally {
    scrapeLoading.value = false
  }
}

async function onToggleFav() {
  if (!item.value) return
  favLoading.value = true
  try {
    item.value = item.value.favorited
      ? await unfavoriteMedia(item.value.id)
      : await favoriteMedia(item.value.id)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '收藏操作失败'))
  } finally {
    favLoading.value = false
  }
}

async function onTranslate() {
  if (!item.value) return
  translateLoading.value = true
  try {
    item.value = await translateMedia(item.value.id)
    ElMessage.success('翻译完成')
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '翻译失败'))
  } finally {
    translateLoading.value = false
  }
}

async function onDelete() {
  if (!item.value || !isLocal.value) return
  const label = item.value.number || item.value.filename || String(item.value.id)
  try {
    await ElMessageBox.confirm(
      `确定删除「${label}」？将删除磁盘上的视频文件及库中索引，此操作不可恢复。`,
      '删除影片',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }
  deleteLoading.value = true
  try {
    await deleteMedia(item.value.id)
    ElMessage.success('已删除')
    goBack()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  } finally {
    deleteLoading.value = false
  }
}

/** Prefer history back so list ?page= is preserved; fallback to library home. */
function goBack() {
  if (typeof window !== 'undefined' && window.history.length > 1) {
    router.back()
    return
  }
  router.replace({ path: '/' })
}

onMounted(() => {
  void load()
  void loadProviders()
})
watch(() => props.id, load)
</script>

<template>
  <div class="page">
    <div class="top-actions">
      <el-button text type="primary" @click="goBack">← 返回</el-button>
    </div>
    <div v-if="loading && !item" class="muted">加载中…</div>
    <div v-else-if="item" class="detail">
      <div class="left">
        <div class="cover-wrap">
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
          <span v-if="isChineseSub" class="sub-badge">中字</span>
        </div>
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
          <button
            type="button"
            class="btn-play"
            :disabled="playLoading"
            :class="{ loading: playLoading }"
            @click="onPlay"
          >
            <span v-if="playLoading" class="btn-spin" aria-hidden="true" />
            <svg v-else class="btn-ico" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path fill="currentColor" d="M8 5.14v14l11-7-11-7z" />
            </svg>
            <span>{{ playLoading ? '准备中…' : '播放' }}</span>
          </button>
          <button
            type="button"
            class="btn-fav"
            :class="{ on: item.favorited, loading: favLoading }"
            :disabled="favLoading"
            :aria-pressed="item.favorited"
            @click="onToggleFav"
          >
            <span v-if="favLoading" class="btn-spin dark" aria-hidden="true" />
            <svg v-else class="btn-ico" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path
                v-if="item.favorited"
                fill="currentColor"
                d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
              />
              <path
                v-else
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                d="M12.1 8.64l-.1.1-.11-.11C10.14 6.6 7.1 6.48 5.4 8.2c-1.7 1.72-1.6 4.46.2 6.06L12 20.5l6.4-6.24c1.8-1.6 1.9-4.34.2-6.06-1.7-1.72-4.74-1.6-6.5.44z"
              />
            </svg>
            <span>{{ item.favorited ? '已收藏' : '收藏' }}</span>
          </button>
          <el-button
            v-if="isLocal"
            type="danger"
            plain
            class="btn-delete"
            :loading="deleteLoading"
            :disabled="deleteLoading"
            @click="onDelete"
          >
            删除
          </el-button>
        </div>
        <ExternalPlayersBar
          :media-id="item.id"
          :name="item.filename || item.number || item.title || 'video'"
          :play="play"
          @play-resolved="play = $event"
        />
        <div class="scrape-row">
          <el-input
            v-model="scrapeNumber"
            class="scrape-number"
            clearable
            maxlength="64"
            placeholder="番号"
            :disabled="scrapeLoading"
          />
          <el-select
            v-model="scrapeProvider"
            class="scrape-provider"
            clearable
            filterable
            allow-create
            default-first-option
            placeholder="刮削源（自动）"
          >
            <el-option label="自动" value="" />
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-switch v-model="scrapeFallback" active-text="fallback" class="scrape-fallback" />
          <el-button
            class="scrape-btn"
            :loading="scrapeLoading"
            :disabled="!canRescrape || translateLoading"
            @click="onRescrape"
          >
            重新刮削
          </el-button>
          <el-button
            class="scrape-btn translate-btn"
            :loading="translateLoading"
            :disabled="!canTranslate || scrapeLoading"
            @click="onTranslate"
          >
            翻译
          </el-button>
        </div>
        <div v-if="tags.length" class="tags" role="list" aria-label="标签">
          <span
            v-for="t in tags"
            :key="t"
            class="tag"
            :class="{ accent: t === '中文字幕' || t === '中字' }"
            role="listitem"
          >{{ t }}</span>
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

    <div v-if="playing && play" ref="playerWrap" class="player-wrap">
      <VideoPlayer
        :media-id="Number(id)"
        :src="play.play_url"
        :subtitles="play.subtitles || []"
        :autoplay="true"
      />
      <p class="muted">播放类型: {{ play.kind }}</p>
    </div>
  </div>
</template>

<style scoped>
.top-actions {
  margin: -4px 0 12px;
}
.detail {
  display: grid;
  grid-template-columns: minmax(180px, 260px) 1fr;
  gap: 28px;
  align-items: start;
}
@media (max-width: 720px) {
  .detail {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .left {
    max-width: 280px;
    margin: 0 auto;
    width: 100%;
  }
  .cover {
    max-height: 55vh;
    object-fit: contain;
    margin: 0 auto;
  }
  .scrape-row {
    flex-direction: column;
    align-items: stretch;
  }
  .scrape-number {
    width: 100% !important;
    flex: 1 1 100% !important;
    max-width: none;
  }
  .scrape-row :deep(.scrape-number),
  .scrape-row :deep(.el-select.scrape-provider),
  .scrape-row :deep(.el-input) {
    width: 100%;
    flex: 1 1 100%;
  }
  .scrape-row :deep(.el-input__wrapper),
  .scrape-row :deep(.el-select__wrapper) {
    min-height: 44px;
    font-size: 16px;
  }
  .scrape-row .scrape-btn {
    width: 100%;
    min-height: 44px;
  }
  .scrape-fallback {
    align-self: flex-start;
  }
}
.cover-wrap {
  position: relative;
}
.cover {
  width: 100%;
  border-radius: 14px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-card);
  display: block;
  background: var(--bg);
}
.sub-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--accent);
  color: #1a1205;
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
  font-size: clamp(20px, 4vw, 26px);
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
  margin: 16px 0 10px;
  align-items: center;
}
.btn-play,
.btn-fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  padding: 0 18px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
  cursor: pointer;
  border: 1px solid transparent;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease,
    color 0.15s ease;
}
.btn-play {
  background: var(--accent);
  color: #1a1205;
  box-shadow: 0 6px 18px var(--accent-glow);
  min-width: 118px;
}
.btn-play:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 22px var(--accent-glow);
}
.btn-play:disabled {
  opacity: 0.75;
  cursor: wait;
}
.btn-fav {
  background: var(--panel);
  color: var(--text);
  border-color: var(--border);
  min-width: 112px;
}
.btn-fav:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  color: var(--accent);
  background: var(--accent-soft);
}
.btn-fav.on {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
  background: var(--accent-soft);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent);
}
.btn-fav:disabled {
  opacity: 0.75;
  cursor: wait;
}
.btn-ico {
  display: block;
  flex-shrink: 0;
}
.btn-spin {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(26, 18, 5, 0.25);
  border-top-color: #1a1205;
  border-radius: 50%;
  animation: btn-rotate 0.7s linear infinite;
  flex-shrink: 0;
}
.btn-spin.dark {
  border-color: color-mix(in srgb, var(--accent) 30%, transparent);
  border-top-color: var(--accent);
}
@keyframes btn-rotate {
  to {
    transform: rotate(360deg);
  }
}
.scrape-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}
.scrape-number {
  width: 140px;
  flex: 0 0 140px;
}
.scrape-provider {
  min-width: 160px;
  flex: 1 1 160px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 2px 0 16px;
}
.tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
  line-height: 1.35;
  color: color-mix(in srgb, var(--text) 92%, var(--muted));
  background: color-mix(in srgb, var(--panel-hover) 88%, var(--accent-soft));
  border: 1px solid color-mix(in srgb, var(--border) 78%, var(--accent) 22%);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--accent) 8%, transparent);
  transition:
    color 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 48%, var(--border));
  background: var(--accent-soft);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 12%, transparent);
  transform: translateY(-1px);
}
.tag.accent {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
  font-weight: 600;
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
  min-height: 40px;
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
  margin-bottom: 12px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  max-width: 100%;
}
.player-wrap :deep(.artplayer-app),
.player-wrap :deep(video) {
  max-width: 100%;
}
</style>
