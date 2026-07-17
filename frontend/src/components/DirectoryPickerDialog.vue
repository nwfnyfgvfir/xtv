<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { browseLibraryDirs } from '@/api/media'
import type { BrowseDirEntry, BrowseDirsOut } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'

const props = defineProps<{
  modelValue: boolean
  /** Initial relative path when opening (e.g. form.path). */
  initialPath?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  select: [path: string]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const browsePath = ref('')
const result = ref<BrowseDirsOut | null>(null)
const loading = ref(false)
const error = ref('')

const canSelect = computed(() => Boolean(browsePath.value))
const pathLabel = computed(() => (browsePath.value ? browsePath.value : 'MEDIA_ROOT /'))

function isRelativePath(p: string) {
  const s = (p || '').trim()
  if (!s) return true
  if (s.startsWith('/') || s.startsWith('\\')) return false
  if (/^[a-zA-Z]:[\\/]/.test(s)) return false
  if (s.includes('..')) return false
  return true
}

async function load(path: string) {
  loading.value = true
  error.value = ''
  try {
    const data = await browseLibraryDirs(path)
    result.value = data
    browsePath.value = data.path
  } catch (e: unknown) {
    error.value = getErrorMessage(e, '无法列出目录')
    result.value = null
  } finally {
    loading.value = false
  }
}

async function openAtInitial() {
  const start = (props.initialPath || '').trim()
  if (start && isRelativePath(start)) {
    await load(start)
    if (result.value) return
  }
  await load('')
}

function enterDir(entry: BrowseDirEntry) {
  void load(entry.path)
}

function goParent() {
  if (result.value?.parent === null || result.value?.parent === undefined) {
    if (browsePath.value) void load('')
    return
  }
  void load(result.value.parent)
}

function refresh() {
  void load(browsePath.value)
}

function confirm() {
  if (!canSelect.value) return
  emit('select', browsePath.value)
  visible.value = false
}

function onClose() {
  error.value = ''
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void openAtInitial()
  },
)
</script>

<template>
  <el-dialog
    v-model="visible"
    title="选择目录"
    class="dir-picker-dialog"
    width="min(480px, 92vw)"
    append-to-body
    destroy-on-close
    @closed="onClose"
  >
    <div class="picker-toolbar">
      <div class="path-label" :title="pathLabel">{{ pathLabel }}</div>
      <div class="picker-actions">
        <el-button size="small" :disabled="!browsePath || loading" @click="goParent">上级</el-button>
        <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
      </div>
    </div>

    <div v-if="error" class="picker-error">{{ error }}</div>
    <div v-else-if="loading && !result" class="picker-empty muted">加载中…</div>
    <ul v-else-if="result?.directories?.length" class="dir-list" :class="{ dim: loading }">
      <li v-for="d in result.directories" :key="d.path">
        <button type="button" class="dir-item" @click="enterDir(d)">
          <span class="folder-ico" aria-hidden="true">📁</span>
          <span class="dir-name">{{ d.name }}</span>
        </button>
      </li>
    </ul>
    <div v-else class="picker-empty muted">此目录下没有子文件夹</div>

    <p class="picker-hint muted">仅可浏览 MEDIA_ROOT 下的目录；选中后写入相对路径。绝对路径请直接手填。</p>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!canSelect" @click="confirm">选择此目录</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.picker-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.path-label {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-display);
  letter-spacing: 0.02em;
}
.picker-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.dir-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: min(360px, 50vh);
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-elevated);
}
.dir-list.dim {
  opacity: 0.65;
  pointer-events: none;
}
.dir-list li + li {
  border-top: 1px solid var(--border);
}
.dir-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--text);
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
  font-size: 14px;
  min-height: 44px;
}
.dir-item:hover {
  background: var(--accent-soft);
  color: var(--accent);
}
.folder-ico {
  flex-shrink: 0;
  font-size: 16px;
  line-height: 1;
}
.dir-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.picker-empty {
  padding: 28px 12px;
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: 10px;
}
.picker-error {
  padding: 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
  font-size: 13px;
}
.picker-hint {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.45;
}
</style>
