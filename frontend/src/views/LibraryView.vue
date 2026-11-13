<script setup lang="ts">
defineOptions({ name: 'LibraryView' })

import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import DirectoryPickerDialog from '@/components/DirectoryPickerDialog.vue'
import MediaGrid from '@/components/MediaGrid.vue'
import AppIcon from '@/components/AppIcon.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import {
  createLibrary,
  getScanJob,
  listLibraries,
  listMedia,
  rescrapePendingLibrary,
  scanLibrary,
  deleteLibrary,
} from '@/api/media'
import type { Library, MediaListItem, MediaSort, ScanJob } from '@/api/types'
import { usePagedRoute } from '@/composables/usePagedRoute'
import { getErrorMessage } from '@/utils/errors'
import { loadMediaSort, MEDIA_SORT_OPTIONS, saveMediaSort } from '@/utils/mediaSort'
import { DEFAULT_PAGE_SIZE, parsePage, queryString } from '@/utils/pageQuery'

type MediaFilter = '' | 'unscraped' | 'chinese' | 'favorited'

const { route, page, replaceQuery, goPage, syncPageFromRoute } = usePagedRoute()

const items = ref<MediaListItem[]>([])
const libraries = ref<Library[]>([])
const total = ref(0)
const sort = ref<MediaSort>(loadMediaSort())
const filter = ref<MediaFilter>(parseFilter(queryString(route.query, 'filter')))
const PAGE_SIZE = DEFAULT_PAGE_SIZE
const loading = ref(false)
const scanningId = ref<number | null>(null)
const scanProgress = ref<ScanJob | null>(null)
const currentLibraryId = ref<number | null>(null)
const SOFT_REFRESH_MS = 20000
let softRefreshTimer: number | undefined
/** Fingerprint of last known library content for soft-refresh. */
let lastSoftFingerprint = ''
let loadedOnce = false

const showCreate = ref(false)
const showPathPicker = ref(false)
const form = ref({
  name: '番号',
  path: 'local',
  type: 'mixed',
})

function onPathPicked(path: string) {
  form.value.path = path
}

function parseFilter(raw: string): MediaFilter {
  if (raw === 'unscraped' || raw === 'chinese' || raw === 'favorited') return raw
  return ''
}

const currentLibrary = computed(
  () => libraries.value.find((l) => l.id === currentLibraryId.value) || null,
)

function libraryFingerprint(
  libs: Library[],
  libId: number | null,
  mediaTotal: number,
  ids: number[],
) {
  const libPart = libs
    .map((l) => `${l.id}:${l.media_count ?? 0}:${l.content_revision ?? 0}`)
    .join('|')
  return `${libPart}#${libId ?? ''}:${mediaTotal}:${ids.join(',')}`
}

function mediaListParams() {
  const params: Parameters<typeof listMedia>[0] = {
    page: page.value,
    page_size: PAGE_SIZE,
    library_id: currentLibraryId.value ?? undefined,
    sort: sort.value,
  }
  if (filter.value === 'unscraped') params.scraped = false
  else if (filter.value === 'chinese') params.subtitle_flag = 'C'
  else if (filter.value === 'favorited') params.favorited = true
  return params
}

async function loadLibraries() {
  libraries.value = await listLibraries()
  const qLib = Number(route.query.library || 0) || null
  if (qLib && libraries.value.some((l) => l.id === qLib)) {
    currentLibraryId.value = qLib
  } else if (!currentLibraryId.value && libraries.value.length) {
    currentLibraryId.value = libraries.value[0].id
  } else if (
    currentLibraryId.value &&
    !libraries.value.some((l) => l.id === currentLibraryId.value)
  ) {
    currentLibraryId.value = libraries.value[0]?.id ?? null
  }
}

async function loadMedia(opts?: { quiet?: boolean; force?: boolean }) {
  if (currentLibraryId.value == null) {
    items.value = []
    total.value = 0
    lastSoftFingerprint = libraryFingerprint(libraries.value, null, 0, [])
    return
  }
  const quiet = Boolean(opts?.quiet) && items.value.length > 0
  if (!quiet) loading.value = true
  try {
    const data = await listMedia(mediaListParams())
    const nextIds = data.items.map((i) => i.id)
    const prevIds = items.value.map((i) => i.id)
    const changed =
      data.total !== total.value ||
      nextIds.length !== prevIds.length ||
      nextIds.some((id, idx) => id !== prevIds[idx]) ||
      data.items.some((it, idx) => it.favorited !== items.value[idx]?.favorited)
    if (changed || !quiet || opts?.force) {
      items.value = data.items
      total.value = data.total
    }
    lastSoftFingerprint = libraryFingerprint(
      libraries.value,
      currentLibraryId.value,
      data.total,
      nextIds,
    )
  } catch (e: unknown) {
    if (!quiet) ElMessage.error(getErrorMessage(e, '加载媒体失败'))
  } finally {
    if (!quiet) loading.value = false
  }
}

async function softRefreshTick() {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
  if (scanningId.value) return
  try {
    const prevCur = currentLibraryId.value
    const prevSig = libraries.value
      .map((l) => `${l.id}:${l.media_count ?? 0}:${l.content_revision ?? 0}`)
      .join('|')
    await loadLibraries()
    const nextSig = libraries.value
      .map((l) => `${l.id}:${l.media_count ?? 0}:${l.content_revision ?? 0}`)
      .join('|')
    const curChanged =
      prevCur !== currentLibraryId.value || prevSig !== nextSig || !lastSoftFingerprint
    if (curChanged) {
      await loadMedia({ quiet: true, force: true })
    }
  } catch {
    /* ignore soft-refresh errors */
  }
}

function onVisibilityChange() {
  if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
    void softRefreshTick()
  }
}

function startSoftRefresh() {
  stopSoftRefresh()
  softRefreshTimer = window.setInterval(() => {
    void softRefreshTick()
  }, SOFT_REFRESH_MS)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }
}

function stopSoftRefresh() {
  if (softRefreshTimer != null) {
    window.clearInterval(softRefreshTimer)
    softRefreshTimer = undefined
  }
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}

async function load() {
  try {
    await loadLibraries()
    await loadMedia({ force: true })
    loadedOnce = true
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载失败，请确认后端已启动并已登录'))
  }
}

function selectLibrary(id: number) {
  currentLibraryId.value = id
  replaceQuery(
    {
      library: String(id),
      filter: filter.value || undefined,
    },
    1,
  )
  void loadMedia({ force: true })
}

function onSortChange(v: MediaSort) {
  sort.value = v
  saveMediaSort(v)
  replaceQuery({ filter: filter.value || undefined }, 1)
  void loadMedia()
}

function onFilterChange(next: MediaFilter) {
  if (next === filter.value) return
  filter.value = next
  replaceQuery({ filter: next || undefined }, 1)
  void loadMedia()
}

function onPageChange(p: number) {
  if (!goPage(p)) return
  void loadMedia()
}

function onItemRefreshed(updated: MediaListItem) {
  const idx = items.value.findIndex((i) => i.id === updated.id)
  if (idx < 0) return
  if (filter.value === 'favorited' && !updated.favorited) {
    items.value = items.value.filter((i) => i.id !== updated.id)
    total.value = Math.max(0, total.value - 1)
    return
  }
  items.value[idx] = { ...items.value[idx], ...updated }
}

async function onCreate() {
  try {
    const lib = await createLibrary({
      name: form.value.name,
      path: form.value.path,
      type: form.value.type,
    })
    showCreate.value = false
    ElMessage.success('媒体库已创建')
    await loadLibraries()
    selectLibrary(lib.id)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '创建失败'))
  }
}

async function onScan(lib: Library) {
  if (scanningId.value) return
  scanningId.value = lib.id
  scanProgress.value = null
  try {
    const job = await scanLibrary(lib.id)
    ElMessage.info(`扫描已开始: ${job.job_id}`)
    await pollJob(job.job_id, '扫描')
    await loadLibraries()
    if (currentLibraryId.value === lib.id) await loadMedia()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '扫描失败'))
  } finally {
    scanningId.value = null
    scanProgress.value = null
  }
}

async function onRescrapePending(lib: Library) {
  if (scanningId.value) return
  scanningId.value = lib.id
  scanProgress.value = null
  try {
    const job = await rescrapePendingLibrary(lib.id)
    ElMessage.info(`补刮已开始: ${job.job_id}`)
    await pollJob(job.job_id, '补刮')
    await loadLibraries()
    if (currentLibraryId.value === lib.id) await loadMedia()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '补刮失败'))
  } finally {
    scanningId.value = null
    scanProgress.value = null
  }
}

async function pollJob(jobId: string, kind = '扫描') {
  const max = 600 // up to ~10 min with 1s interval
  for (let i = 0; i < max; i++) {
    try {
      const job = await getScanJob(jobId)
      scanProgress.value = job
      if (job.status === 'done') {
        ElMessage.success(job.message || `${kind}完成`)
        return
      }
      if (job.status === 'error') {
        throw new Error(job.message || `${kind}出错`)
      }
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 404) throw new Error(`${kind}任务丢失（服务可能已重启）`)
      if (e instanceof Error && (e.message.includes(kind) || e.message.includes('任务'))) throw e
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error(`${kind}超时，请稍后刷新查看结果`)
}

async function onDelete(lib: Library) {
  try {
    await ElMessageBox.confirm(
      `确定删除媒体库「${lib.name}」？将移除该库的索引记录（不会删除磁盘上的媒体文件）。`,
      '删除媒体库',
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
  try {
    await deleteLibrary(lib.id)
    ElMessage.success('已删除')
    if (currentLibraryId.value === lib.id) currentLibraryId.value = null
    await load()
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  }
}

function onMoreCommand(cmd: string) {
  const lib = currentLibrary.value
  if (!lib) return
  if (cmd === 'delete') void onDelete(lib)
  if (cmd === 'scan') void onScan(lib)
  if (cmd === 'rescrape') void onRescrapePending(lib)
}

watch(
  () => route.query.library,
  (v) => {
    const id = Number(v || 0) || null
    if (id && id !== currentLibraryId.value) {
      currentLibraryId.value = id
      void loadMedia({ force: true })
    }
  },
)

watch(
  () => route.query.page,
  () => {
    if (syncPageFromRoute()) void loadMedia()
  },
)

watch(
  () => route.query.filter,
  (v) => {
    const next = parseFilter(typeof v === 'string' ? v : '')
    if (next !== filter.value) {
      filter.value = next
      void loadMedia()
    }
  },
)

onMounted(() => {
  page.value = parsePage(route.query)
  filter.value = parseFilter(queryString(route.query, 'filter'))
  void load()
  startSoftRefresh()
})

onActivated(() => {
  if (loadedOnce) void softRefreshTick()
})

onBeforeUnmount(stopSoftRefresh)
</script>

<template>
  <div class="page library-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">私人媒体空间</p>
        <h1 class="page-title">媒体库</h1>
        <p class="page-description">
          {{ currentLibrary?.name || '你的收藏' }}<span class="description-dot">·</span
          ><span class="num">{{ total }}</span> 部影片
        </p>
      </div>
      <el-button class="add-lib-btn" type="primary" @click="showCreate = true"
        ><AppIcon name="plus" :size="17" />添加媒体库</el-button
      >
    </header>

    <nav v-if="libraries.length" class="lib-tabs" aria-label="选择媒体库">
      <button
        v-for="lib in libraries"
        :key="lib.id"
        type="button"
        class="lib-tab"
        :class="{ on: lib.id === currentLibraryId }"
        :aria-pressed="lib.id === currentLibraryId"
        @click="selectLibrary(lib.id)"
      >
        <AppIcon name="folder" :size="16" /><span class="name">{{ lib.name }}</span
        ><span class="count">{{ lib.media_count ?? 0 }}</span>
      </button>
    </nav>

    <div v-if="currentLibrary" class="lib-toolbar">
      <div class="library-location" :title="currentLibrary.path">
        <AppIcon name="folder" :size="15" /><span>{{ currentLibrary.path }}</span
        ><span class="source-kind">{{ currentLibrary.type }}</span>
      </div>
      <div class="actions">
        <el-button
          :loading="scanningId === currentLibrary.id"
          :disabled="scanningId != null && scanningId !== currentLibrary.id"
          @click="onScan(currentLibrary)"
          ><AppIcon name="refresh" :size="15" />扫描目录</el-button
        >
        <el-button
          :loading="scanningId === currentLibrary.id"
          :disabled="scanningId != null && scanningId !== currentLibrary.id"
          title="刮削当前库中尚未刮削的影片"
          @click="onRescrapePending(currentLibrary)"
          >补全元数据</el-button
        >
        <el-dropdown trigger="click" @command="onMoreCommand">
          <el-button class="library-more" aria-label="媒体库管理" title="媒体库管理"
            ><AppIcon name="dots" :size="18"
          /></el-button>
          <template #dropdown
            ><el-dropdown-menu
              ><el-dropdown-item command="delete"
                ><span class="danger-text">删除媒体库</span></el-dropdown-item
              ></el-dropdown-menu
            ></template
          >
        </el-dropdown>
      </div>
    </div>

    <div v-if="currentLibrary" class="library-controls">
      <div class="filter-chips" role="group" aria-label="列表筛选">
        <button
          type="button"
          class="chip"
          :class="{ on: filter === '' }"
          :aria-pressed="filter === ''"
          @click="onFilterChange('')"
        >
          全部影片
        </button>
        <button
          type="button"
          class="chip"
          :class="{ on: filter === 'unscraped' }"
          :aria-pressed="filter === 'unscraped'"
          @click="onFilterChange('unscraped')"
        >
          未刮削
        </button>
        <button
          type="button"
          class="chip"
          :class="{ on: filter === 'chinese' }"
          :aria-pressed="filter === 'chinese'"
          @click="onFilterChange('chinese')"
        >
          中字
        </button>
        <button
          type="button"
          class="chip"
          :class="{ on: filter === 'favorited' }"
          :aria-pressed="filter === 'favorited'"
          @click="onFilterChange('favorited')"
        >
          <AppIcon name="heart" :size="13" />已收藏
        </button>
      </div>
      <el-dropdown class="mobile-library-menu" trigger="click" @command="onMoreCommand">
        <el-button aria-label="媒体库操作"><AppIcon name="settings" :size="15" />库操作</el-button>
        <template #dropdown
          ><el-dropdown-menu
            ><el-dropdown-item :disabled="scanningId != null" command="scan"
              >扫描目录</el-dropdown-item
            ><el-dropdown-item :disabled="scanningId != null" command="rescrape"
              >补全未刮削影片</el-dropdown-item
            ><el-dropdown-item divided command="delete"
              ><span class="danger-text">删除媒体库</span></el-dropdown-item
            ></el-dropdown-menu
          ></template
        >
      </el-dropdown>
      <el-select
        class="sort-select"
        :model-value="sort"
        aria-label="影片排序"
        @change="onSortChange"
        ><el-option
          v-for="opt in MEDIA_SORT_OPTIONS"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
      /></el-select>
    </div>

    <div v-if="scanProgress && scanningId" class="scan-banner" role="status">
      <div class="scan-text">
        <AppIcon name="refresh" :size="16" />任务进行中<span class="scan-stats"
          >已扫描 {{ scanProgress.scanned }} · 新增 {{ scanProgress.created }} · 已刮削
          {{ scanProgress.scraped }}</span
        >
      </div>
      <div class="scan-msg muted">{{ scanProgress.message || scanProgress.status }}</div>
      <div class="scan-bar"><i /></div>
    </div>

    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid
      v-else
      :items="items"
      :empty-title="libraries.length ? '这里还没有影片' : '从一个媒体库开始'"
      :empty-hint="
        libraries.length
          ? '扫描当前目录，或调整筛选条件查看影片'
          : '添加媒体目录，扫描后即可浏览、筛选和播放影片'
      "
      @refreshed="onItemRefreshed"
    />
    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />

    <el-dialog
      v-model="showCreate"
      title="添加媒体库"
      class="create-lib-dialog"
      width="min(460px, 92vw)"
    >
      <p class="dialog-intro">连接一个媒体目录，开始整理你的收藏。</p>
      <el-form label-position="top">
        <el-form-item label="媒体库名称"
          ><el-input v-model="form.name" placeholder="为这个媒体库起个名字"
        /></el-form-item>
        <el-form-item label="媒体目录"
          ><div class="path-row">
            <el-input v-model="form.path" placeholder="local 或 strm" clearable /><el-button
              @click="showPathPicker = true"
              ><AppIcon name="folder" :size="16" />浏览</el-button
            >
          </div>
          <div class="muted tip">
            相对媒体根目录的路径可以浏览选择，绝对路径请手动填写。
          </div></el-form-item
        >
        <el-form-item label="媒体类型"
          ><el-select v-model="form.type" style="width: 100%"
            ><el-option label="混合媒体" value="mixed" /><el-option
              label="本地视频"
              value="local" /><el-option label="STRM 直链" value="strm" /></el-select
        ></el-form-item>
        <p class="muted tip">创建后将自动监听目录变更。需要全量检查时，可以手动扫描。</p>
      </el-form>
      <template #footer
        ><el-button @click="showCreate = false">取消</el-button
        ><el-button type="primary" @click="onCreate">创建媒体库</el-button></template
      >
    </el-dialog>
    <DirectoryPickerDialog
      v-model="showPathPicker"
      :initial-path="form.path"
      @select="onPathPicked"
    />
  </div>
</template>
<style scoped>
.description-dot {
  margin: 0 10px;
  color: var(--faint);
}
.add-lib-btn {
  flex-shrink: 0;
}
.lib-tabs {
  display: flex;
  gap: 26px;
  overflow-x: auto;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 23px;
}
.lib-tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  background: none;
  border: 0;
  border-bottom: 2px solid transparent;
  padding: 13px 1px 14px;
  margin-bottom: -1px;
  cursor: pointer;
  white-space: nowrap;
  font-size: 13px;
  color: var(--muted);
}
.lib-tab:hover {
  color: var(--text);
}
.lib-tab.on {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.lib-tab.on > .app-icon {
  color: var(--accent);
}
.lib-tab .name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.count {
  padding: 1px 6px;
  background: var(--panel-hover);
  color: var(--faint);
  border-radius: 4px;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.lib-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}
.library-location {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--faint);
  font-size: 11px;
}
.library-location > span:first-of-type {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
}
.source-kind {
  padding: 1px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  font-size: 10px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.library-more.el-button {
  padding: 0 10px;
}
.library-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 26px;
}
.filter-chips {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 4px;
  border-radius: 8px;
  background: var(--bg-elevated);
}
.chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 7px 13px;
  min-height: 33px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
}
.chip.on {
  background: var(--panel-hover);
  color: var(--text);
  box-shadow: var(--shadow-sm);
}
.chip:hover:not(.on) {
  color: var(--text);
}
.sort-select {
  width: 166px;
  flex-shrink: 0;
}
.mobile-library-menu {
  display: none;
}
.sort-select :deep(.el-select__wrapper) {
  background: transparent !important;
  box-shadow: none !important;
}
.sort-select :deep(.el-select__placeholder) {
  font-size: 12px;
  text-align: right;
}
.scan-banner {
  padding: 16px 18px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  border-radius: 9px;
  margin: 0 0 24px;
}
.scan-text {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--accent);
  font-size: 12px;
}
.scan-stats {
  color: var(--text-soft);
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.scan-msg {
  font-size: 11px;
  margin-top: 6px;
}
.scan-bar {
  margin-top: 12px;
  height: 2px;
  background: var(--border);
  border-radius: 9px;
  overflow: hidden;
}
.scan-bar i {
  display: block;
  height: 100%;
  width: 35%;
  background: var(--accent);
  animation: scanmove 1.1s var(--ease-in-out) infinite;
}
@keyframes scanmove {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(320%);
  }
}
.danger-text {
  color: var(--danger);
}
.dialog-intro {
  margin: 0 0 22px;
  font-size: 12px;
  color: var(--muted);
}
.path-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.path-row .el-input {
  flex: 1;
  min-width: 0;
}
.tip {
  font-size: 11px;
  line-height: 1.7;
  margin: 6px 0 0;
}
@media (max-width: 1100px) {
  .library-location > span:first-of-type {
    max-width: 130px;
  }
  .source-kind {
    display: none;
  }
}
@media (max-width: 640px) {
  .lib-tabs {
    gap: 22px;
    margin-bottom: 18px;
  }
  .lib-toolbar {
    display: none;
  }
  .library-location > span:first-of-type {
    max-width: none;
  }
  .actions {
    width: 100%;
  }
  .actions > .el-button {
    flex: 1;
    height: 42px;
  }
  .actions :deep(.library-more) {
    height: 42px;
  }
  .library-controls {
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 20px;
  }
  .filter-chips {
    flex: 1 1 100%;
  }
  .chip {
    flex: 1;
    padding-left: 9px;
    padding-right: 9px;
    min-height: 44px;
  }
  .sort-select {
    width: 150px;
    margin-left: auto;
  }
  .mobile-library-menu {
    display: inline-flex;
  }
  .mobile-library-menu :deep(.el-button) {
    height: 44px;
    font-size: 11px;
  }
  .sort-select :deep(.el-select__wrapper) {
    min-height: 44px;
  }
  .add-lib-btn {
    padding-left: 12px;
    padding-right: 12px;
    height: 44px;
  }
  .scan-stats {
    margin-left: 0;
    width: 100%;
  }
}
</style>
