<script setup lang="ts">
defineOptions({ name: 'LibraryView' })

import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import DirectoryPickerDialog from '@/components/DirectoryPickerDialog.vue'
import MediaGrid from '@/components/MediaGrid.vue'
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

const currentLibrary = computed(() =>
  libraries.value.find((l) => l.id === currentLibraryId.value) || null,
)

function libraryFingerprint(libs: Library[], libId: number | null, mediaTotal: number, ids: number[]) {
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

async function loadMedia(opts?: { quiet?: boolean }) {
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
    if (changed || !quiet) {
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
      prevCur !== currentLibraryId.value ||
      prevSig !== nextSig ||
      !lastSoftFingerprint
    if (curChanged) {
      await loadMedia({ quiet: true })
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
    await loadMedia()
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
  void loadMedia()
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
}

watch(
  () => route.query.library,
  (v) => {
    const id = Number(v || 0) || null
    if (id && id !== currentLibraryId.value) {
      currentLibraryId.value = id
      void loadMedia()
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
  <div class="page">
    <div class="head">
      <div>
        <h1 class="page-title">媒体库</h1>
      </div>
      <el-button class="add-lib-btn" type="primary" @click="showCreate = true">添加媒体库</el-button>
    </div>

    <div v-if="libraries.length" class="lib-tabs">
      <button
        v-for="lib in libraries"
        :key="lib.id"
        type="button"
        class="lib-tab"
        :class="{ on: lib.id === currentLibraryId }"
        @click="selectLibrary(lib.id)"
      >
        <span class="name">{{ lib.name }}</span>
        <span class="count">{{ lib.media_count ?? 0 }}</span>
      </button>
    </div>
    <p v-else class="muted hint">
      尚未添加媒体库。路径可填相对 MEDIA_ROOT 的路径，例如 <code>local</code> 或 <code>strm</code>。
    </p>

    <div v-if="currentLibrary" class="lib-toolbar">
      <div class="meta muted">
        <span>{{ currentLibrary.path }}</span>
        <span>· {{ currentLibrary.type }}</span>
        <span>· 实时监听中</span>
      </div>
      <div class="actions">
        <el-select
          class="sort-select"
          :model-value="sort"
          size="small"
          @change="onSortChange"
        >
          <el-option
            v-for="opt in MEDIA_SORT_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-button
          size="small"
          type="warning"
          :loading="scanningId === currentLibrary.id"
          :disabled="scanningId != null && scanningId !== currentLibrary.id"
          @click="onScan(currentLibrary)"
        >
          扫描
        </el-button>
        <el-button
          size="small"
          type="primary"
          plain
          :loading="scanningId === currentLibrary.id"
          :disabled="scanningId != null && scanningId !== currentLibrary.id"
          @click="onRescrapePending(currentLibrary)"
        >
          刮削未刮削
        </el-button>
        <div class="actions-more desktop-more">
          <el-button size="small" type="danger" plain @click="onDelete(currentLibrary)">删除</el-button>
        </div>
        <el-dropdown class="mobile-more" trigger="click" @command="onMoreCommand">
          <el-button size="small">更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="delete">
                <span class="danger-text">删除媒体库</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div v-if="currentLibrary" class="filter-chips" role="toolbar" aria-label="列表筛选">
      <button type="button" class="chip" :class="{ on: filter === '' }" @click="onFilterChange('')">
        全部
      </button>
      <button
        type="button"
        class="chip"
        :class="{ on: filter === 'unscraped' }"
        @click="onFilterChange('unscraped')"
      >
        未刮削
      </button>
      <button
        type="button"
        class="chip"
        :class="{ on: filter === 'chinese' }"
        @click="onFilterChange('chinese')"
      >
        中字
      </button>
      <button
        type="button"
        class="chip"
        :class="{ on: filter === 'favorited' }"
        @click="onFilterChange('favorited')"
      >
        已收藏
      </button>
    </div>

    <div v-if="scanProgress && scanningId" class="scan-banner">
      <div class="scan-text">
        任务进行中 · scanned {{ scanProgress.scanned }} · created {{ scanProgress.created }} · scraped
        {{ scanProgress.scraped }}
      </div>
      <div class="scan-msg muted">{{ scanProgress.message || scanProgress.status }}</div>
      <div class="scan-bar"><i /></div>
    </div>

    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" @refreshed="onItemRefreshed" />

    <AppPagination :total="total" :page="page" :page-size="PAGE_SIZE" @update:page="onPageChange" />

    <el-dialog v-model="showCreate" title="添加媒体库" class="create-lib-dialog" width="min(440px, 92vw)">
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="路径">
          <div class="path-row">
            <el-input v-model="form.path" placeholder="local 或 strm" clearable />
            <el-button @click="showPathPicker = true">浏览</el-button>
          </div>
          <div class="muted tip">相对 MEDIA_ROOT 的路径可点浏览选择；绝对路径请手填</div>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="mixed" value="mixed" />
            <el-option label="local" value="local" />
            <el-option label="strm" value="strm" />
          </el-select>
        </el-form-item>
        <p class="muted tip create-tip">创建后目录实时监听自动开启；需要全量校验时点工具栏「扫描」。</p>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <DirectoryPickerDialog
      v-model="showPathPicker"
      :initial-path="form.path"
      @select="onPathPicked"
    />
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.lib-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.lib-tab {
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  border-radius: 999px;
  padding: 8px 14px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
}
.lib-tab .name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}
.lib-tab.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.count {
  font-size: 12px;
  opacity: 0.8;
  background: var(--bg);
  padding: 1px 7px;
  border-radius: 999px;
  flex-shrink: 0;
}
.lib-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.meta {
  font-size: 13px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}
.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
}
.actions-more {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.mobile-more {
  display: none;
}
.sort-select {
  width: 168px;
}
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.chip {
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  min-height: 34px;
}
.chip.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.chip:hover:not(.on) {
  color: var(--text);
  border-color: var(--border-strong);
}
.danger-text {
  color: var(--danger);
}
.scan-banner {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(232, 168, 56, 0.35);
  background: var(--accent-soft);
}
.scan-text {
  font-weight: 600;
  color: var(--accent);
  font-size: 13px;
}
.scan-msg {
  font-size: 12px;
  margin-top: 4px;
}
.scan-bar {
  margin-top: 10px;
  height: 3px;
  background: var(--border);
  border-radius: 99px;
  overflow: hidden;
}
.scan-bar i {
  display: block;
  height: 100%;
  width: 35%;
  background: var(--accent);
  animation: scanmove 1.1s ease-in-out infinite;
}
@keyframes scanmove {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(320%);
  }
}
.hint {
  margin-bottom: 18px;
}
code {
  color: var(--accent);
}
.path-row {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}
.path-row .el-input {
  flex: 1;
  min-width: 0;
}
.tip {
  margin-top: 6px;
  font-size: 12px;
}
.create-tip {
  margin: 0 0 4px 0;
  padding-left: 100px;
  font-size: 12px;
}
@media (max-width: 520px) {
  .create-tip {
    padding-left: 0;
  }
}
@media (max-width: 860px) {
  .lib-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .actions {
    width: 100%;
    flex-wrap: wrap;
  }
  .sort-select {
    width: min(168px, 100%);
    flex: 1 1 140px;
  }
  .desktop-more {
    display: none;
  }
  .mobile-more {
    display: inline-flex;
  }
  .add-lib-btn {
    flex-shrink: 0;
  }
}
@media (max-width: 640px) {
  .lib-tab .name {
    max-width: 100px;
  }
  .meta {
    font-size: 12px;
  }
}
</style>
