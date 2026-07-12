<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import {
  createLibrary,
  getScanJob,
  listLibraries,
  listMedia,
  scanLibrary,
  deleteLibrary,
  updateLibrary,
} from '@/api/media'
import type { Library, MediaListItem, ScanJob } from '@/api/types'

const route = useRoute()
const router = useRouter()

const items = ref<MediaListItem[]>([])
const libraries = ref<Library[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const scanningId = ref<number | null>(null)
const scanProgress = ref<ScanJob | null>(null)
const currentLibraryId = ref<number | null>(null)

const showCreate = ref(false)
const form = ref({
  name: '番号',
  path: 'local',
  type: 'mixed',
  auto_scan_enabled: false,
  interval_value: 24,
  interval_unit: 'hours' as 'seconds' | 'minutes' | 'hours',
})

function toSeconds(value: number, unit: 'seconds' | 'minutes' | 'hours') {
  if (unit === 'seconds') return Math.max(30, value)
  if (unit === 'minutes') return Math.max(30, value * 60)
  return Math.max(30, value * 3600)
}

function formatInterval(lib: Library) {
  const s = lib.scan_interval_seconds || (lib.scan_interval_hours ? lib.scan_interval_hours * 3600 : 0)
  if (!s) return ''
  if (s % 3600 === 0) return `${s / 3600}h`
  if (s % 60 === 0) return `${s / 60}m`
  return `${s}s`
}

function syncIntervalForm(lib: Library | null) {
  if (!lib) return
  const s =
    lib.scan_interval_seconds ||
    (lib.scan_interval_hours ? lib.scan_interval_hours * 3600 : 86400)
  if (s % 3600 === 0) {
    form.value.interval_value = s / 3600
    form.value.interval_unit = 'hours'
  } else if (s % 60 === 0) {
    form.value.interval_value = s / 60
    form.value.interval_unit = 'minutes'
  } else {
    form.value.interval_value = s
    form.value.interval_unit = 'seconds'
  }
}

const currentLibrary = computed(() =>
  libraries.value.find((l) => l.id === currentLibraryId.value) || null,
)

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
  const cur = libraries.value.find((l) => l.id === currentLibraryId.value) || null
  syncIntervalForm(cur)
}

async function loadMedia() {
  if (currentLibraryId.value == null) {
    items.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const data = await listMedia({
      page: page.value,
      page_size: 48,
      library_id: currentLibraryId.value,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载媒体失败')
  } finally {
    loading.value = false
  }
}

async function load() {
  try {
    await loadLibraries()
    await loadMedia()
  } catch {
    ElMessage.error('加载失败，请确认后端已启动并已登录')
  }
}

function selectLibrary(id: number) {
  currentLibraryId.value = id
  page.value = 1
  const lib = libraries.value.find((l) => l.id === id) || null
  syncIntervalForm(lib)
  router.replace({ query: { ...route.query, library: String(id) } })
  void loadMedia()
}

async function onCreate() {
  try {
    const secs = form.value.auto_scan_enabled
      ? toSeconds(form.value.interval_value, form.value.interval_unit)
      : null
    const lib = await createLibrary({
      name: form.value.name,
      path: form.value.path,
      type: form.value.type,
      auto_scan_enabled: form.value.auto_scan_enabled,
      scan_interval_seconds: secs,
      scan_interval_hours: secs ? Math.max(1, Math.round(secs / 3600)) : null,
    })
    showCreate.value = false
    ElMessage.success('媒体库已创建')
    await loadLibraries()
    selectLibrary(lib.id)
  } catch {
    ElMessage.error('创建失败')
  }
}

async function onScan(lib: Library) {
  if (scanningId.value) return
  scanningId.value = lib.id
  scanProgress.value = null
  try {
    const job = await scanLibrary(lib.id)
    ElMessage.info(`扫描已开始: ${job.job_id}`)
    await pollJob(job.job_id)
    await loadLibraries()
    if (currentLibraryId.value === lib.id) await loadMedia()
  } catch (e: unknown) {
    const msg = (e as { message?: string })?.message
    ElMessage.error(msg || '扫描失败')
  } finally {
    scanningId.value = null
    scanProgress.value = null
  }
}

async function pollJob(jobId: string) {
  const max = 600 // up to ~10 min with 1s interval
  for (let i = 0; i < max; i++) {
    try {
      const job = await getScanJob(jobId)
      scanProgress.value = job
      if (job.status === 'done') {
        ElMessage.success(job.message || '扫描完成')
        return
      }
      if (job.status === 'error') {
        throw new Error(job.message || '扫描出错')
      }
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 404) throw new Error('扫描任务丢失（服务可能已重启）')
      if (e instanceof Error && e.message !== '扫描出错' && !String(e).includes('Network')) {
        // continue on transient
      }
      if (e instanceof Error && (e.message.includes('扫描') || e.message.includes('任务'))) throw e
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error('扫描超时，请稍后刷新查看结果')
}

async function onDelete(lib: Library) {
  await deleteLibrary(lib.id)
  ElMessage.success('已删除')
  if (currentLibraryId.value === lib.id) currentLibraryId.value = null
  await load()
}

async function toggleAutoScan(lib: Library) {
  try {
    const secs =
      lib.scan_interval_seconds ||
      (lib.scan_interval_hours ? lib.scan_interval_hours * 3600 : 86400)
    await updateLibrary(lib.id, {
      auto_scan_enabled: !lib.auto_scan_enabled,
      scan_interval_seconds: secs,
      scan_interval_hours: Math.max(1, Math.round(secs / 3600)),
    })
    await loadLibraries()
    ElMessage.success(!lib.auto_scan_enabled ? '已开启定时扫描' : '已关闭定时扫描')
  } catch {
    ElMessage.error('更新失败')
  }
}

async function saveInterval(lib: Library) {
  const secs = toSeconds(form.value.interval_value, form.value.interval_unit)
  try {
    await updateLibrary(lib.id, {
      scan_interval_seconds: secs,
      scan_interval_hours: Math.max(1, Math.round(secs / 3600)),
      auto_scan_enabled: true,
    })
    await loadLibraries()
    ElMessage.success(`定时间隔已设为 ${secs}s`)
  } catch {
    ElMessage.error('更新间隔失败')
  }
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

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="head">
      <div>
        <h1 class="page-title">媒体库</h1>
        <p class="muted intro">按库浏览（Jellyfin 风格），互不混排</p>
      </div>
      <el-button type="primary" @click="showCreate = true">添加媒体库</el-button>
    </div>

    <div v-if="libraries.length" class="lib-tabs">
      <button
        v-for="lib in libraries"
        :key="lib.id"
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
        <span v-if="currentLibrary.auto_scan_enabled">
          · 定时每 {{ formatInterval(currentLibrary) || '24h' }}
        </span>
      </div>
      <div class="actions">
        <div class="interval-inline">
          <el-input-number
            v-model="form.interval_value"
            size="small"
            :min="1"
            :max="999999"
            controls-position="right"
          />
          <el-select v-model="form.interval_unit" size="small" style="width: 78px">
            <el-option label="秒" value="seconds" />
            <el-option label="分" value="minutes" />
            <el-option label="时" value="hours" />
          </el-select>
          <el-button size="small" plain @click="saveInterval(currentLibrary)">应用间隔</el-button>
        </div>
        <el-button size="small" @click="toggleAutoScan(currentLibrary)">
          {{ currentLibrary.auto_scan_enabled ? '关闭定时' : '开启定时' }}
        </el-button>
        <el-button
          size="small"
          type="warning"
          :loading="scanningId === currentLibrary.id"
          @click="onScan(currentLibrary)"
        >
          扫描
        </el-button>
        <el-button size="small" type="danger" plain @click="onDelete(currentLibrary)">删除</el-button>
      </div>
    </div>

    <div v-if="scanProgress && scanningId" class="scan-banner">
      <div class="scan-text">
        扫描中 · scanned {{ scanProgress.scanned }} · created {{ scanProgress.created }} · scraped
        {{ scanProgress.scraped }}
      </div>
      <div class="scan-msg muted">{{ scanProgress.message || scanProgress.status }}</div>
      <div class="scan-bar"><i /></div>
    </div>

    <SkeletonGrid v-if="loading && !items.length" />
    <MediaGrid v-else :items="items" />

    <div v-if="total > 48" class="pager">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="48"
        v-model:current-page="page"
        @current-change="loadMedia"
      />
    </div>

    <el-dialog v-model="showCreate" title="添加媒体库" width="440px">
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="form.path" placeholder="local 或 strm" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="mixed" value="mixed" />
            <el-option label="local" value="local" />
            <el-option label="strm" value="strm" />
          </el-select>
        </el-form-item>
        <el-form-item label="定时扫描">
          <el-switch v-model="form.auto_scan_enabled" />
        </el-form-item>
        <el-form-item label="扫描间隔">
          <div class="interval-row">
            <el-input-number v-model="form.interval_value" :min="1" :max="999999" />
            <el-select v-model="form.interval_unit" style="width: 110px">
              <el-option label="秒" value="seconds" />
              <el-option label="分" value="minutes" />
              <el-option label="时" value="hours" />
            </el-select>
          </div>
          <div class="muted tip">最小 30 秒；创建或点「应用间隔」写入当前库</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.intro {
  margin: 0 0 16px;
  font-size: 13px;
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
}
.lib-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
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
}
.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
}
.interval-inline {
  display: inline-flex;
  gap: 6px;
  align-items: center;
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
.pager {
  margin-top: 22px;
  display: flex;
  justify-content: center;
}
code {
  color: var(--accent);
}
.interval-row {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}
.tip {
  margin-top: 6px;
  font-size: 12px;
}
@media (max-width: 640px) {
  .lib-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .actions {
    flex-wrap: wrap;
  }
}
</style>
