<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import VideoPlayer from '@/components/VideoPlayer.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import AppIcon from '@/components/AppIcon.vue'
import { isActiveTask, useTasks } from '@/composables/useTasks'
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
import type { MediaDetail, PlayInfo, ScrapeSource } from '@/api/types'
import { normalizeScrapeSource, scrapeSources } from '@/utils/scrapeSources'
import { getErrorMessage } from '@/utils/errors'
import { formatFileSize } from '@/utils/format'
import { monogramChar, monogramStyle } from '@/utils/monogram'
import { useCoverImage } from '@/composables/useCoverImage'

const props = defineProps<{ id: string }>()
const router = useRouter()
const item = ref<MediaDetail | null>(null)
const play = ref<PlayInfo | null>(null)
const loading = ref(false)
const playing = ref(false)
const coverPreviewVisible = ref(false)
const favLoading = ref(false)
const playLoading = ref(false)
const { tasks, acceptTask, panelOpen } = useTasks()
const scrapeSubmitting = ref(false)
const currentTask = computed(() =>
  tasks.value.find((task) => task.media_id === Number(props.id) && task.kind === 'rescrape'),
)
const scrapeLoading = computed(
  () => scrapeSubmitting.value || Boolean(currentTask.value && isActiveTask(currentTask.value)),
)
const translateLoading = ref(false)
const deleteLoading = ref(false)
const providers = ref<string[]>([])
const FOLLOW_GLOBAL_SOURCE = '__follow_global_source__'
const scrapeProvider = ref(FOLLOW_GLOBAL_SOURCE)
const scrapeUrl = ref('')
const scrapeSource = ref<ScrapeSource>('metatube')
const useStash = computed(() => scrapeSource.value === 'stash')
const supportsSourceUrl = computed(() => scrapeSource.value !== 'metatube')
const sourceUrlPlaceholder = computed(() =>
  useStash.value ? '支持 Stash-box 场景链接或站点影片链接' : '可选，按所选刮削器或来源地址匹配',
)
const followsGlobalSource = computed(() => scrapeProvider.value === FOLLOW_GLOBAL_SOURCE)
const sourceModeHint = computed(() =>
  useStash.value && scrapeUrl.value.trim()
    ? 'Stash-box 场景链接可选择对应的 Stash-box；其他站点链接由 Stash 匹配刮削器。'
    : followsGlobalSource.value
      ? '先按设置页的优先级尝试，全部未命中后继续其余可用源。'
      : scrapeProvider.value === ''
        ? '自动尝试适用源，命中后停止；仅 URL 的源需填写来源地址。'
        : '仅本次使用所选来源，文件名原样交给来源查询。',
)
const providerLabels = ref<Record<string, string>>({})
const mediaProviderLabel = computed(() => {
  const provider = item.value?.provider
  if (!provider) return '尚未刮削'
  const source = provider.startsWith('stash:') ? provider.slice(6) : provider
  return providerLabels.value[source] || (source.startsWith('stash-box:') ? 'Stash-box' : provider)
})
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

const { src: cover, showImage, failed: coverFailed, onError: onCoverError, reset: resetCover } = useCoverImage(() => [
  item.value?.cover_url, item.value?.thumb_url, item.value?.backdrop_url,
])
const isChineseSub = computed(
  () => item.value?.subtitle_flag === 'C' || tags.value.includes('中文字幕'),
)
const canRescrape = computed(() => Boolean(item.value?.filename || scrapeUrl.value.trim()))
const isLocal = computed(() => item.value?.source_type === 'local')
const canDelete = computed(() => Boolean(item.value))
const deleteButtonLabel = computed(() => (isLocal.value ? '删除' : '删除索引'))
const fileSizeLabel = computed(() => formatFileSize(item.value?.file_size))
const canTranslate = computed(() => {
  if (!item.value) return false
  if ((item.value.title || '').trim() || (item.value.plot || '').trim()) return true
  return tags.value.length > 0
})

async function load() {
  loading.value = true
  coverPreviewVisible.value = false
  resetCover()
  playing.value = false
  play.value = null
  try {
    item.value = await getMedia(Number(props.id))
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载详情失败'))
  } finally {
    loading.value = false
  }
}

async function loadProviders() {
  try {
    const s = await getSettings()
    scrapeSource.value = normalizeScrapeSource(s.scrape_source)
    const fields = scrapeSources[scrapeSource.value]
    providerLabels.value = s.movie_provider_labels || {}
    const list = [...(s.movie_providers || [])]
    const pri = s[fields.priority] || []
    for (const p of pri) {
      if (p && !list.includes(p)) list.push(p)
    }
    providers.value = list
    scrapeProvider.value = FOLLOW_GLOBAL_SOURCE
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
  const url = supportsSourceUrl.value ? scrapeUrl.value.trim() : ''
  scrapeSubmitting.value = true
  try {
    const task = await rescrapeMedia(Number(props.id), {
      // Omission follows global priorities; explicit "" requests full automatic mode.
      provider: followsGlobalSource.value ? undefined : scrapeProvider.value,
      url: url || undefined,
    })
    acceptTask(task)
    panelOpen.value = true
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '刮削失败'))
  } finally {
    scrapeSubmitting.value = false
  }
}

watch(
  () =>
    currentTask.value
      ? `${currentTask.value.job_id}:${currentTask.value.status}:${currentTask.value.scraped}`
      : '',
  async () => {
    const task = currentTask.value
    if (!task || isActiveTask(task) || !task.scraped) return
    const id = props.id
    try {
      const updated = await getMedia(Number(id))
      if (props.id === id) {
        item.value = updated
        resetCover()
      }
    } catch {
      /* Normal page loading still reports errors. */
    }
  },
)

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
    item.value = await renameMedia(item.value.id, {
      new_filename: newFilename,
    })
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
  <div class="page detail-page">
    <div class="top-actions">
      <button type="button" class="back-btn" @click="goBack">
        <AppIcon name="back" :size="17" />返回上一页
      </button>
      <span v-if="item" class="detail-state"
        ><span :class="{ ready: !!item.scraped_at }" />{{
          item.scraped_at ? '已刮削' : '待补全信息'
        }}</span
      >
    </div>
    <div v-if="loading && !item" class="detail-loading" role="status">
      <div class="loading-block" />
      <p>正在载入影片信息…</p>
    </div>
    <template v-else-if="item">
      <section class="detail" aria-label="影片信息与播放">
        <div class="cover-wrap">
          <button
            v-if="showImage"
            type="button"
            class="cover-open"
            aria-label="查看完整封面"
            @click="coverPreviewVisible = true"
          >
            <img class="cover" :src="cover" :alt="item.title || item.filename" @error="onCoverError" />
          </button>
          <CoverPlaceholder
            v-else
            size="lg"
            :number="item.number"
            :title="item.title"
            :filename="item.filename"
          />
          <span v-if="isChineseSub" class="sub-badge">中文字幕</span>
          <button v-if="coverFailed" type="button" class="cover-retry" @click="resetCover">
            <AppIcon name="refresh" :size="16" />图片加载失败，重试
          </button>
        </div>
        <div class="hero-info">
          <div class="media-kicker">
            <AppIcon name="film" :size="15" /><span class="number">{{
              item.number || '未知番号'
            }}</span
            ><span class="media-type">{{
              item.source_type === 'local' ? '本地视频' : 'STRM 直链'
            }}</span>
          </div>
          <h1 class="detail-title">{{ item.title || item.filename }}</h1>
          <div class="meta-line">
            <span v-if="item.score != null" class="rating"
              ><AppIcon name="star" :size="14" />{{ item.score.toFixed(1) }}</span
            >
            <span v-if="item.release_date">{{ item.release_date }}</span>
            <span v-if="item.runtime"
              ><AppIcon name="clock" :size="13" />{{ item.runtime }} 分钟</span
            >
            <span v-if="item.studio">{{ item.studio }}</span>
          </div>
          <div v-if="tags.length" class="tags" role="list" aria-label="影片标签">
            <span
              v-for="tag in tags"
              :key="tag"
              class="tag"
              :class="{ accent: tag === '中文字幕' || tag === '中字' }"
              role="listitem"
              >{{ tag }}</span
            >
          </div>
          <div class="primary-actions">
            <button type="button" class="btn-play" :disabled="playLoading" @click="onPlay">
              <span v-if="playLoading" class="btn-spin" aria-hidden="true" /><AppIcon
                v-else
                name="play"
                :size="18"
              /><span>{{ playLoading ? '准备中…' : '立即播放' }}</span>
            </button>
            <button
              type="button"
              class="btn-fav"
              :class="{ on: item.favorited }"
              :disabled="favLoading"
              :aria-pressed="item.favorited"
              @click="onToggleFav"
            >
              <span v-if="favLoading" class="btn-spin" aria-hidden="true" /><AppIcon
                v-else
                name="heart"
                :size="18"
              /><span>{{ item.favorited ? '已收藏' : '收藏影片' }}</span>
            </button>
          </div>
          <ExternalPlayersBar
            :media-id="item.id"
            :name="item.filename || item.number || item.title || 'video'"
            :play="play"
            @play-resolved="play = $event"
          />
        </div>
      </section>

      <section v-if="playing && play" ref="playerWrap" class="player-wrap" aria-label="视频播放器">
        <div class="section-heading">
          <h2>正在播放</h2>
          <span>{{ play.kind === 'local' ? '本地播放' : '直链播放' }}</span>
        </div>
        <VideoPlayer
          :media-id="Number(id)"
          :src="play.play_url"
          :subtitles="play.subtitles || []"
          :autoplay="true"
        />
      </section>

      <div class="detail-content">
        <div class="editorial">
          <section v-if="item.plot" class="content-section">
            <h2>剧情简介</h2>
            <p class="plot">{{ item.plot }}</p>
          </section>
          <section v-if="item.actors?.length" class="content-section actors">
            <div class="section-heading">
              <h2>出演演员</h2>
              <span>{{ item.actors.length }} 位</span>
            </div>
            <div class="actor-list">
              <button
                v-for="actor in item.actors"
                :key="actor.id"
                type="button"
                class="actor"
                @click="router.push(`/actors/${actor.id}`)"
              >
                <img
                  v-if="actor.image_url"
                  :src="actor.image_url"
                  :alt="actor.name"
                  loading="lazy"
                />
                <span v-else class="a-mono" :style="monogramStyle(actor.name)">{{
                  monogramChar({ title: actor.name })
                }}</span>
                <span>{{ actor.name }}</span>
              </button>
            </div>
          </section>
          <p v-if="!item.plot && !item.actors?.length" class="no-details">
            暂时没有更多介绍，可在右侧管理区重新刮削影片信息。
          </p>
        </div>

        <aside class="file-panel" aria-label="文件信息与管理">
          <h2>媒体信息</h2>
          <dl class="file-facts">
            <div>
              <dt>刮削来源</dt>
              <dd>{{ mediaProviderLabel }}</dd>
            </div>
            <div>
              <dt>文件格式</dt>
              <dd>
                {{ item.filename.split('.').pop()?.toUpperCase() || '—' }}
              </dd>
            </div>
            <div v-if="isLocal && fileSizeLabel">
              <dt>文件大小</dt>
              <dd>{{ fileSizeLabel }}</dd>
            </div>
          </dl>
          <div class="file-path">
            <span>文件路径</span>
            <p>{{ item.path }}</p>
          </div>
          <details class="maintenance">
            <summary>
              <AppIcon name="settings" :size="17" /><span
                >管理与刮削<small>更新信息、翻译与文件操作</small></span
              ><AppIcon name="down" class="disclosure-arrow" :size="16" />
            </summary>
            <div class="maintenance-content">
              <div class="scrape-row">
                <label v-if="supportsSourceUrl" class="management-field"
                  >来源 URL<el-input
                    v-model="scrapeUrl"
                    clearable
                    maxlength="2048"
                    :placeholder="sourceUrlPlaceholder"
                    aria-label="刮削来源 URL"
                    :disabled="scrapeLoading"
                /></label>
                <div class="management-field">
                  <span>查询文件名</span><code class="source-filename">{{ item.filename }}</code>
                  <span class="field-hint muted">直接使用原文件名去掉扩展名后的文本查询，由刮削源匹配。</span>
                </div>
                <div class="management-field">
                  <span>刮削器</span
                  ><el-select
                    v-model="scrapeProvider"
                    clearable
                    filterable
                    allow-create
                    default-first-option
                    placeholder="自动选择"
                    aria-label="刮削器"
                    :disabled="scrapeLoading"
                    ><el-option label="跟随全局配置" :value="FOLLOW_GLOBAL_SOURCE" />
                    <el-option label="自动（全部适用源）" value="" /><el-option
                      v-for="provider in providers"
                      :key="provider"
                      :label="providerLabels[provider] || provider"
                      :value="provider"
                  /></el-select>
                  <span class="field-hint muted">{{ sourceModeHint }}</span>
                </div>
                <div class="maintenance-actions">
                  <el-button
                    :loading="scrapeLoading"
                    :disabled="!canRescrape || translateLoading"
                    @click="onRescrape"
                    ><AppIcon name="refresh" :size="14" />重新刮削</el-button
                  ><el-button
                    :loading="translateLoading"
                    :disabled="!canTranslate || scrapeLoading"
                    @click="onTranslate"
                    ><AppIcon name="translate" :size="14" />翻译</el-button
                  >
                </div>
              </div>
              <div class="file-actions">
                <el-button :disabled="renameLoading" @click="openRename">重命名文件</el-button
                ><el-button
                  v-if="canDelete"
                  type="danger"
                  plain
                  :loading="deleteLoading"
                  :disabled="deleteLoading"
                  @click="onDelete"
                  >{{ deleteButtonLabel }}</el-button
                >
              </div>
            </div>
          </details>
        </aside>
      </div>

      <el-dialog v-if="showImage" v-model="coverPreviewVisible" title="完整封面" width="min(1100px, 94vw)" append-to-body>
        <img class="cover-original" :src="cover" :alt="item.title || item.filename" />
      </el-dialog>
      <el-dialog v-model="renameVisible" title="重命名文件" width="min(440px, 92vw)">
        <p class="dialog-help">修改文件名，扩展名 {{ renameExt || '（无）' }} 将保持不变。</p>
        <el-input
          v-model="renameInput"
          placeholder="新文件名"
          aria-label="新文件名"
          :disabled="renameLoading"
          clearable
          @keyup.enter="doRename"
        />
        <template #footer
          ><el-button @click="renameVisible = false">取消</el-button
          ><el-button type="primary" :loading="renameLoading" @click="doRename"
            >确认重命名</el-button
          ></template
        >
      </el-dialog>
    </template>
    <div v-else class="detail-empty">
      <AppIcon name="film" :size="36" />
      <h2>暂时无法加载影片</h2>
      <p>可以重新尝试，或返回媒体库查看其他影片。</p>
      <el-button @click="load">重新加载</el-button>
    </div>
  </div>
</template>
<style scoped>
.top-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: none;
  color: var(--muted);
  padding: 4px 0;
  min-height: 32px;
  cursor: pointer;
  font-size: 12px;
}
.back-btn:hover {
  color: var(--accent);
}
.detail-state {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  color: var(--faint);
  font-size: 11px;
}
.detail-state > span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--faint);
}
.detail-state > span.ready {
  background: var(--accent);
}
.detail {
  display: grid;
  grid-template-columns: minmax(280px, 440px) minmax(0, 1fr);
  gap: clamp(28px, 3vw, 50px);
  align-items: start;
  padding-bottom: 40px;
  border-bottom: 1px solid var(--border-subtle);
}
.cover-wrap {
  position: relative;
  aspect-ratio: var(--poster-ratio);
  border-radius: 12px;
  overflow: hidden;
  background: var(--bg-elevated);
}
.cover-open,
.cover-wrap > :deep(.cover-placeholder) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.cover-open {
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
}
.cover {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: fill;
}
.cover-original {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 75dvh;
  margin: 0 auto;
  object-fit: contain;
}
.source-filename {
  overflow-wrap: anywhere;
  font-size: 13px;
}
.cover-retry {
  position: absolute;
  bottom: 12px;
  left: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 44px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
}
.sub-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  padding: 4px 9px;
  background: #0d231dd9;
  color: #bef6dc;
  border-radius: 5px;
  font-size: 11px;
}
.hero-info {
  min-width: 0;
  padding-top: 8px;
}
.media-kicker {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--accent);
}
.number {
  min-width: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.media-type {
  font-size: 10px;
  color: var(--faint);
  border: 1px solid var(--border);
  padding: 1px 7px;
  border-radius: 4px;
  margin-left: 6px;
}
.detail-title {
  margin: 17px 0 19px;
  font-size: clamp(22px, 2.1vw, 31px);
  font-weight: 600;
  line-height: 1.55;
  letter-spacing: -0.025em;
  text-wrap: pretty;
  overflow-wrap: anywhere;
}
.meta-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 18px;
  color: var(--muted);
  font-size: 12px;
}
.meta-line > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.rating {
  color: var(--warning);
  font-family: var(--font-mono);
  font-weight: 600;
}
.rating :deep(svg) {
  fill: currentColor;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 23px 0 0;
}
.tag {
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 5px;
  font-size: 10px;
  padding: 3px 9px;
}
.tag.accent {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--accent-line);
}
.primary-actions {
  display: flex;
  align-items: center;
  gap: 11px;
  margin: 28px 0 24px;
}
.btn-play,
.btn-fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 46px;
  padding: 0 26px;
  border-radius: 7px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.btn-play {
  background: var(--accent);
  color: var(--on-accent);
}
.btn-play :deep(svg) {
  fill: currentColor;
  stroke-width: 1;
}
.btn-play:hover:not(:disabled) {
  background: var(--accent-hover);
}
.btn-fav {
  background: transparent;
  color: var(--text-soft);
  border-color: var(--border-strong);
}
.btn-fav:hover,
.btn-fav.on {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.btn-fav.on :deep(svg) {
  fill: currentColor;
}
.btn-play:disabled,
.btn-fav:disabled {
  opacity: 0.6;
  cursor: wait;
}
.btn-spin {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.hero-info :deep(.external-players) {
  padding: 16px 0 0;
  border: 0;
  border-top: 1px solid var(--border-subtle);
  background: transparent;
  border-radius: 0;
  margin: 0;
}
.hero-info :deep(.ep-toolbar) {
  gap: 8px;
}
.hero-info :deep(.ep-label) {
  font-size: 11px;
  letter-spacing: 0;
  margin-right: auto;
}
.hero-info :deep(.ep-action),
.hero-info :deep(.ep-toggle) {
  border: 0;
  background: transparent;
  padding: 0 5px;
  font-size: 10px;
}
.hero-info :deep(.ep-icon-btn) {
  width: 38px;
  height: 38px;
  border-radius: 8px;
}
.hero-info :deep(.ep-icon-btn img) {
  width: 25px;
  height: 25px;
}
.detail-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 46px;
  padding-top: 34px;
  align-items: start;
}
.content-section + .content-section {
  margin-top: 35px;
}
.content-section h2,
.file-panel h2,
.player-wrap h2 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 17px;
}
.plot {
  font-size: 13px;
  color: var(--muted);
  line-height: 2;
  white-space: pre-line;
  margin: 0;
  overflow-wrap: anywhere;
}
.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.section-heading > span {
  font-size: 11px;
  color: var(--faint);
}
.actor-list {
  display: flex;
  flex-wrap: wrap;
  gap: 25px;
}
.actor {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 10px;
  width: 70px;
  padding: 0;
  background: none;
  border: 0;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}
.actor img,
.a-mono {
  width: 61px;
  height: 61px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--panel-hover);
}
.a-mono {
  display: grid;
  place-items: center;
  color: var(--text-soft);
  font-family: var(--font-display);
  font-size: 23px;
}
.actor:hover {
  color: var(--accent);
}
.actor > span:last-child {
  display: block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-panel {
  padding: 22px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  border-radius: 11px;
  min-width: 0;
}
.file-panel h2 {
  font-size: 13px;
  margin-bottom: 20px;
}
.file-facts {
  display: grid;
  gap: 13px;
  margin: 0;
  font-size: 11px;
}
.file-facts > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 15px;
}
.file-facts dt,
.file-path > span {
  color: var(--faint);
  flex-shrink: 0;
}
.file-facts dd {
  margin: 0;
  color: var(--text-soft);
  text-align: right;
  overflow-wrap: anywhere;
}
.file-path {
  margin-top: 18px;
  font-size: 11px;
}
.file-path p {
  font-size: 10px;
  font-family: var(--font-mono);
  line-height: 1.8;
  color: var(--muted);
  overflow-wrap: anywhere;
  margin: 5px 0 0;
}
.maintenance {
  border-top: 1px solid var(--border);
  margin-top: 21px;
  padding-top: 18px;
}
.maintenance summary {
  display: flex;
  align-items: center;
  gap: 9px;
  list-style: none;
  cursor: pointer;
  color: var(--text-soft);
  font-size: 12px;
}
.maintenance summary::-webkit-details-marker {
  display: none;
}
.maintenance summary small {
  display: block;
  font-size: 10px;
  color: var(--faint);
  margin-top: 3px;
}
.disclosure-arrow {
  margin-left: auto;
  color: var(--faint);
  transition: transform var(--dur-2);
}
.maintenance[open] .disclosure-arrow {
  transform: rotate(180deg);
}
.maintenance-content {
  padding-top: 22px;
}
.scrape-row {
  display: grid;
  gap: 14px;
}
.management-field {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--muted);
  font-size: 11px;
}
.scrape-row :deep(.el-select),
.scrape-row :deep(.el-input) {
  width: 100%;
}
.scrape-row :deep(.el-switch__label) {
  font-size: 11px;
}
.maintenance-actions,
.file-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.maintenance-actions > .el-button,
.file-actions > .el-button {
  flex: 1;
  padding-left: 10px;
  padding-right: 10px;
  font-size: 11px;
}
.file-actions {
  border-top: 1px solid var(--border-subtle);
  padding-top: 16px;
  margin-top: 20px;
}
.player-wrap {
  margin: 32px 0 8px;
  padding: 22px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  scroll-margin-top: 100px;
}
.dialog-help {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 18px;
}
.no-details {
  color: var(--faint);
  font-size: 12px;
  margin: 0;
  padding: 12px 0;
}
.detail-loading {
  color: var(--faint);
  font-size: 13px;
  min-height: 360px;
  display: grid;
  place-content: center;
  justify-items: center;
}
.loading-block {
  width: 60px;
  height: 80px;
  border-radius: 6px;
  background: var(--skeleton);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.4;
  }
}
.detail-empty {
  min-height: 350px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: var(--faint);
}
.detail-empty h2 {
  color: var(--text-soft);
  font-size: 17px;
  margin-bottom: 0;
}
.detail-empty p {
  font-size: 12px;
  margin-bottom: 25px;
}
@media (max-width: 1180px) {
  .detail {
    grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
    gap: 28px;
  }
  .detail-content {
    gap: 28px;
    grid-template-columns: minmax(0, 1fr) 280px;
  }
}
@media (max-width: 1000px) {
  .detail-content {
    grid-template-columns: minmax(0, 1fr);
  }
  .file-panel {
    max-width: none;
  }
  .file-facts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 15px;
  }
  .file-facts > div {
    display: grid;
    gap: 5px;
  }
  .file-facts dd {
    text-align: left;
  }
  .scrape-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .file-actions > .el-button {
    flex: 0 1 auto;
  }
}
@media (max-width: 640px) {
  .top-actions {
    margin-bottom: 23px;
  }
  .detail {
    grid-template-columns: minmax(0, 1fr);
    padding-bottom: 28px;
    gap: 23px;
  }
  .cover-wrap {
    width: 100%;
    margin: 0 auto;
  }
  .hero-info {
    padding-top: 0;
  }
  .detail-title {
    font-size: 22px;
    margin: 14px 0;
  }
  .meta-line {
    font-size: 11px;
    gap: 9px 14px;
  }
  .tags {
    margin-top: 18px;
  }
  .primary-actions {
    margin: 24px 0;
  }
  .btn-play,
  .btn-fav {
    flex: 1;
    padding: 0 14px;
    min-height: 48px;
  }
  .detail-content {
    padding-top: 26px;
    gap: 27px;
  }
  .file-panel {
    padding: 19px;
  }
  .file-facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .scrape-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .management-field {
    font-size: 12px;
  }
  .maintenance-actions > .el-button,
  .file-actions > .el-button {
    min-height: 43px;
    flex: 1;
    font-size: 12px;
  }
  .actor-list {
    gap: 20px;
  }
  .player-wrap {
    padding: 12px;
    scroll-margin-top: 82px;
  }
}
</style>
