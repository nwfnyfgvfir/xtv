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
  renameMedia,
  rescrapeMedia,
  translateMedia,
  unfavoriteMedia,
} from '@/api/media'
import type { MediaDetail, PlayInfo } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
import { formatFileSize } from '@/utils/format'
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
const renameVisible = ref(false)
const renameInput = ref('')
const renameLoading = ref(false)
const renameExt = ref('')

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
const canDelete = computed(() => Boolean(item.value))
const deleteButtonLabel = computed(() => (isLocal.value ? '删除' : '删除索引'))
const fileSizeLabel = computed(() => formatFileSize(item.value?.file_size))
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
  if (!item.value) return
  const label = item.value.number || item.value.filename || String(item.value.id)
  const msg = isLocal.value
    ? `确定删除「${label}」？将删除磁盘上的视频文件及库中索引，此操作不可恢复。`
    : `确定删除「${label}」的库索引？不会删除磁盘上的 .strm 文件；下次扫描可能重新入库。`
  try {
    await ElMessageBox.confirm(msg, isLocal.value ? '删除影片' : '删除索引', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  deleteLoading.value = true
  try {
    await deleteMedia(item.value.id)
    ElMessage.success(isLocal.value ? '已删除' : '已删除索引')
    goBack()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  } finally {
    deleteLoading.value = false
  }
}

function openRename() {
  if (!item.value) return
  const name = item.value.filename || ''
  const dot = name.lastIndexOf('.')
  if (dot > 0) {
    renameInput.value = name.slice(0, dot)
    renameExt.value = name.slice(dot)
  } else {
    renameInput.value = name || item.value.title || ''
    renameExt.value = ''
  }
  renameVisible.value = true
}

async function doRename() {
  if (!item.value) return
  const stem = renameInput.value.trim()
  if (!stem) {
    ElMessage.warning('请输入新文件名')
    return
  }
  const newFilename = renameExt.value ? `${stem}${renameExt.value}` : stem
  renameLoading.value = true
  try {
    item.value = await renameMedia(item.value.id, { new_filename: newFilename })
    ElMessage.success('重命名成功')
    renameVisible.value = false
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '重命名失败'))
  } finally {
    renameLoading.value = false
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
      <button type="button" class="back-btn" @click="goBack">
        <svg class="back-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M15 5.5 8.5 12 15 18.5" />
        </svg>
        <span>返回</span>
      </button>
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
        <div class="number num">{{ item.number || '未知番号' }}</div>
        <h1>{{ item.title || item.filename }}</h1>
        <hr class="title-rule" />
        <p class="muted meta-line">
          <span v-if="item.provider">{{ item.provider }}</span>
          <span v-if="item.release_date"> · {{ item.release_date }}</span>
          <span v-if="item.studio"> · {{ item.studio }}</span>
          <span v-if="item.runtime"> · {{ item.runtime }} 分钟</span>
          <span v-if="isLocal && fileSizeLabel"> · {{ fileSizeLabel }}</span>
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
            plain
            size="large"
            class="btn-rename"
            :disabled="renameLoading"
            @click="openRename"
          >
            重命名
          </el-button>
          <el-button
            v-if="canDelete"
            type="danger"
            plain
            size="large"
            class="btn-delete"
            :loading="deleteLoading"
            :disabled="deleteLoading"
            @click="onDelete"
          >
            {{ deleteButtonLabel }}
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

        <el-dialog v-model="renameVisible" title="重命名" :width="420" center>
          <el-input
            v-model="renameInput"
            placeholder="新文件名（保留原扩展名）"
            clearable
          />
          <template #footer>
            <el-button @click="renameVisible = false">取消</el-button>
            <el-button type="primary" :loading="renameLoading" @click="doRename">
              确认重命名
            </el-button>
          </template>
        </el-dialog>

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
  margin: 0 0 var(--space-5);
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
  border-radius: var(--radius-full);
  padding: 0 var(--space-4) 0 var(--space-3);
  font-size: var(--text-sm);
  font-weight: 500;
  height: 36px;
  cursor: pointer;
  transition:
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
.back-btn:hover {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--panel-hover);
}
.back-ico {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.detail {
  display: grid;
  grid-template-columns: minmax(190px, 268px) 1fr;
  gap: var(--space-8);
  align-items: start;
}
.cover-wrap {
  position: relative;
}
.cover {
  width: 100%;
  border-radius: var(--radius-md);
  box-shadow:
    var(--shadow-lg),
    0 0 0 1px var(--border-subtle);
  display: block;
  background: var(--bg-elevated);
}
.sub-badge {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  font-size: var(--text-2xs);
  font-weight: 700;
  letter-spacing: var(--tracking-wide);
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: var(--on-accent);
}

/* The 番号 is the film's code — give it title-card treatment. */
.number {
  color: var(--accent);
  font-size: var(--text-lg);
  font-weight: 600;
  letter-spacing: var(--tracking-wider);
}
h1 {
  margin: var(--space-2) 0 0;
  font-size: var(--text-2xl);
  line-height: var(--leading-tight);
  letter-spacing: var(--tracking-tight);
  font-weight: 500;
  text-wrap: balance;
}
.title-rule {
  height: 1px;
  border: 0;
  margin: var(--space-4) 0;
  background: linear-gradient(90deg, var(--accent-line), var(--border-subtle) 28%, transparent);
}
.meta-line {
  margin: 0;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}
.btns {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: var(--space-5) 0 var(--space-4);
  align-items: center;
}
.btn-play,
.btn-fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 44px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-full);
  font-size: 0.875rem; /* 14px — matches .el-button--large */
  font-weight: 600;
  letter-spacing: var(--tracking-wide);
  cursor: pointer;
  border: 1px solid transparent;
  transition:
    transform var(--dur-2) var(--ease-out),
    box-shadow var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out),
    color var(--dur-2) var(--ease-out);
}
/* Gold is scarce: the play button is the one saturated element on this page. */
.btn-play {
  background: var(--accent);
  color: var(--on-accent);
  box-shadow: var(--shadow-sm);
  min-width: 128px;
}
.btn-play:hover:not(:disabled) {
  background: var(--accent-hover);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}
.btn-play:active:not(:disabled) {
  background: var(--accent-press);
  transform: translateY(0);
}
.btn-play:disabled {
  opacity: 0.7;
  cursor: wait;
}

.btn-fav {
  background: var(--panel);
  color: var(--text);
  border-color: var(--border);
  min-width: 120px;
}
.btn-fav:hover:not(:disabled) {
  border-color: var(--accent-line);
  color: var(--accent);
  background: var(--panel-hover);
}
.btn-fav.on {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.btn-fav:disabled {
  opacity: 0.7;
  cursor: wait;
}
/* Rename / delete now inherit the shared .el-button--large sizing. */
.btn-rename,
.btn-delete {
  min-width: 104px;
}
.btn-ico {
  display: block;
  flex-shrink: 0;
}
.btn-spin {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in oklab, var(--on-accent) 30%, transparent);
  border-top-color: var(--on-accent);
  border-radius: 50%;
  animation: btn-rotate 0.7s linear infinite;
  flex-shrink: 0;
}
.btn-spin.dark {
  border-color: color-mix(in oklab, var(--accent) 30%, transparent);
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
  gap: var(--space-2);
  align-items: center;
  margin-bottom: var(--space-4);
}
.scrape-number {
  width: 148px;
  flex: 0 0 148px;
}
.scrape-provider {
  min-width: 140px;
  /* Provider names are short (JavBus / FANZA / MetaTube) — a wide dropdown
     just adds empty space. Cap it close to its content. */
  flex: 0 1 220px;
  max-width: 220px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: var(--space-1) 0 var(--space-5);
}
.tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 4px 11px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
  line-height: var(--leading-snug);
  color: var(--text-soft);
  background: var(--panel-hover);
  border: 1px solid var(--border);
  transition:
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag:hover {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.tag.accent {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--accent-line);
  font-weight: 600;
}
.plot {
  white-space: pre-wrap;
  line-height: var(--leading-relaxed);
  color: var(--text-soft);
  margin: 0;
  max-width: 74ch;
  text-wrap: pretty;
}
.actors h3 {
  margin: var(--space-6) 0 var(--space-3);
  font-size: var(--text-2xs);
  letter-spacing: var(--tracking-widest);
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
}
.actor-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.actor {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--panel);
  border: 1px solid var(--border);
  padding: 4px var(--space-3) 4px 4px;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  color: var(--text);
  cursor: pointer;
  min-height: 40px;
  transition:
    color var(--dur-2) var(--ease-out),
    border-color var(--dur-2) var(--ease-out),
    background-color var(--dur-2) var(--ease-out);
}
.actor:hover {
  border-color: var(--accent-line);
  color: var(--accent);
  background: var(--panel-hover);
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
  font-size: var(--text-xs);
  color: var(--accent);
  font-family: var(--font-serif);
}
.path {
  margin-top: var(--space-5);
  font-size: var(--text-xs);
  color: var(--faint);
  font-family: var(--font-mono);
  word-break: break-all;
}
.player-wrap {
  margin-top: var(--space-10);
  margin-bottom: var(--space-4);
  padding-top: var(--space-5);
  border-top: 1px solid var(--border-subtle);
  max-width: 100%;
}
.player-wrap :deep(.artplayer-app),
.player-wrap :deep(video) {
  max-width: 100%;
}

@media (max-width: 720px) {
  .detail {
    grid-template-columns: 1fr;
    gap: var(--space-5);
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
  h1 {
    font-size: var(--text-xl);
  }
}
</style>
