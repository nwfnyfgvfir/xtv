<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppPagination from '@/components/AppPagination.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import { batchDeleteMedia, listDuplicates } from '@/api/media'
import type { DuplicateGroup, DuplicateMediaItem } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
import { formatFileSize } from '@/utils/format'

const router = useRouter()
const groups = ref<DuplicateGroup[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const q = ref('')
const loading = ref(false)
const deleteLoading = ref(false)
const selected = ref<Set<number>>(new Set())

const selectedCount = computed(() => selected.value.size)

async function load() {
  loading.value = true
  try {
    const data = await listDuplicates({
      q: q.value.trim() || undefined,
      page: page.value,
      page_size: pageSize,
    })
    groups.value = data.items
    total.value = data.total
    // Drop selections that are no longer on this page
    const visible = new Set(data.items.flatMap((g) => g.items.map((i) => i.id)))
    const next = new Set<number>()
    for (const id of selected.value) {
      if (visible.has(id)) next.add(id)
    }
    selected.value = next
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '加载重复项失败'))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void load()
}

function onPageChange(p: number) {
  page.value = p
  void load()
}

function isSelected(id: number) {
  return selected.value.has(id)
}

function toggle(id: number, on?: boolean) {
  const next = new Set(selected.value)
  const should = on ?? !next.has(id)
  if (should) next.add(id)
  else next.delete(id)
  selected.value = next
}

function selectGroup(group: DuplicateGroup, on: boolean) {
  const next = new Set(selected.value)
  for (const item of group.items) {
    if (on) next.add(item.id)
    else next.delete(item.id)
  }
  selected.value = next
}

function groupAllSelected(group: DuplicateGroup) {
  return group.items.length > 0 && group.items.every((i) => selected.value.has(i.id))
}

/** Keep the largest file_size (nulls last); select the rest in the group. */
function keepLargest(group: DuplicateGroup) {
  let best: DuplicateMediaItem | null = null
  for (const item of group.items) {
    if (best == null) {
      best = item
      continue
    }
    const a = item.file_size ?? -1
    const b = best.file_size ?? -1
    if (a > b || (a === b && item.id < best.id)) best = item
  }
  if (!best) return
  const next = new Set(selected.value)
  for (const item of group.items) {
    if (item.id === best.id) next.delete(item.id)
    else next.add(item.id)
  }
  selected.value = next
}

function coverOf(item: DuplicateMediaItem) {
  return item.thumb_url || item.cover_url || ''
}

function openDetail(id: number) {
  router.push({ name: 'detail', params: { id: String(id) } })
}

function applyDeletion(ids: number[]) {
  const gone = new Set(ids)
  const nextGroups: DuplicateGroup[] = []
  let removedGroups = 0
  for (const g of groups.value) {
    const items = g.items.filter((i) => !gone.has(i.id))
    if (items.length < 2) {
      removedGroups += 1
      continue
    }
    nextGroups.push({ number: g.number, count: items.length, items })
  }
  groups.value = nextGroups
  total.value = Math.max(0, total.value - removedGroups)
  const nextSel = new Set<number>()
  for (const id of selected.value) {
    if (!gone.has(id)) nextSel.add(id)
  }
  selected.value = nextSel
}

async function onDeleteSelected() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除已选的 ${ids.length} 项？\n· 本地影片：删除磁盘文件与库索引\n· strm：仅删除库索引（文件仍在，扫描可能恢复）\n此操作不可恢复。`,
      '删除重复项',
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
    const result = await batchDeleteMedia(ids)
    if (result.deleted.length) {
      applyDeletion(result.deleted)
      ElMessage.success(`已删除 ${result.deleted.length} 项`)
    }
    if (result.failed.length) {
      const sample = result.failed
        .slice(0, 3)
        .map((f) => `#${f.id}: ${f.error}`)
        .join('；')
      ElMessage.warning(
        `${result.failed.length} 项失败${sample ? `（${sample}）` : ''}`,
      )
    }
    if (!groups.value.length && total.value > 0) {
      // Current page emptied but more groups exist
      page.value = Math.max(1, page.value - 1)
      void load()
    }
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '删除失败'))
  } finally {
    deleteLoading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page" :class="{ 'has-bar': selectedCount > 0 }">
    <div class="head">
      <div>
        <h1 class="page-title">重复影片</h1>
        <p class="muted intro">
          按番号聚合（忽略大小写；-C / 多碟也算重复）。共
          <strong>{{ total }}</strong> 组
        </p>
      </div>
      <div class="head-actions">
        <el-input
          v-model="q"
          clearable
          placeholder="筛选番号"
          class="search"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <el-button @click="onSearch">搜索</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div v-if="loading && !groups.length" class="muted empty">加载中…</div>
    <div v-else-if="!groups.length" class="muted empty">未发现重复（按番号）</div>

    <section v-for="group in groups" :key="group.number" class="group">
      <header class="group-head">
        <div class="group-title">
          <span class="num">{{ group.number }}</span>
          <span class="muted">· {{ group.count }} 份</span>
        </div>
        <div class="group-actions">
          <el-button size="small" text @click="selectGroup(group, !groupAllSelected(group))">
            {{ groupAllSelected(group) ? '取消全选' : '全选' }}
          </el-button>
          <el-button size="small" text @click="keepLargest(group)">仅保留最大体积</el-button>
        </div>
      </header>
      <ul class="rows">
        <li v-for="item in group.items" :key="item.id" class="row">
          <el-checkbox
            :model-value="isSelected(item.id)"
            @change="(v: boolean | string | number) => toggle(item.id, Boolean(v))"
          />
          <button type="button" class="thumb" @click="openDetail(item.id)">
            <img
              v-if="coverOf(item)"
              :src="coverOf(item)"
              alt=""
              loading="lazy"
              @error="($event.target as HTMLImageElement).style.display = 'none'"
            />
            <CoverPlaceholder
              v-else
              :number="item.number"
              :title="item.title"
              :filename="item.filename"
            />
          </button>
          <div class="meta" @click="openDetail(item.id)">
            <div class="line1">
              <span class="lib">{{ item.library_name || `库 #${item.library_id}` }}</span>
              <span class="pill" :class="item.source_type">{{ item.source_type }}</span>
              <span v-if="item.subtitle_flag === 'C'" class="pill sub">中字</span>
              <span v-if="item.disc" class="pill disc">{{ item.disc }}</span>
              <span v-if="item.file_size != null" class="muted size">{{
                formatFileSize(item.file_size)
              }}</span>
            </div>
            <div class="line2 muted" :title="item.path">
              {{ item.filename }}
            </div>
            <div v-if="item.title" class="line3 muted">{{ item.title }}</div>
          </div>
        </li>
      </ul>
    </section>

    <AppPagination
      v-if="total > pageSize"
      :page="page"
      :page-size="pageSize"
      :total="total"
      @update:page="onPageChange"
    />

    <div v-if="selectedCount > 0" class="action-bar">
      <span>已选 {{ selectedCount }} 项</span>
      <el-button @click="selected = new Set()">取消</el-button>
      <el-button type="danger" :loading="deleteLoading" @click="onDeleteSelected">
        删除所选
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.page {
  padding-bottom: 24px;
}
.page.has-bar {
  padding-bottom: 88px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 18px;
}
.intro {
  margin: 4px 0 0;
  font-size: 13px;
}
.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.search {
  width: min(220px, 100%);
}
.empty {
  padding: 48px 12px;
  text-align: center;
}
.group {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  margin-bottom: 14px;
  overflow: hidden;
}
.group-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}
.group-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.num {
  font-weight: 700;
  letter-spacing: 0.04em;
  font-size: 15px;
}
.group-actions {
  display: flex;
  gap: 4px;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
}
.row {
  display: grid;
  grid-template-columns: auto 64px 1fr;
  gap: 10px 12px;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}
.row:last-child {
  border-bottom: none;
}
.thumb {
  width: 64px;
  height: 90px;
  border: none;
  padding: 0;
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg, #111);
  cursor: pointer;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.meta {
  min-width: 0;
  cursor: pointer;
}
.line1 {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
  align-items: center;
  font-size: 13px;
}
.lib {
  font-weight: 600;
}
.pill {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--border);
  text-transform: lowercase;
}
.pill.local {
  color: var(--ok, #3d9);
}
.pill.strm {
  color: var(--warn, #db8);
}
.pill.sub {
  color: #6af;
}
.pill.disc {
  opacity: 0.85;
}
.size {
  font-size: 12px;
}
.line2,
.line3 {
  margin-top: 4px;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.action-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(64px + env(safe-area-inset-bottom));
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: center;
  padding: 12px 16px;
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  border-top: 1px solid var(--border);
  backdrop-filter: blur(8px);
}
@media (min-width: 861px) {
  .action-bar {
    bottom: 0;
  }
}
</style>
