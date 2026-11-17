<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Library, WaitingFile, CleanupItem } from '@/api/types'
import {
  updateLibrary,
  getWaitingFiles,
  recheckWaiting,
  cleanupPreview,
} from '@/api/media'
import { useTasks } from '@/composables/useTasks'
import { getErrorMessage } from '@/utils/errors'
const props = defineProps<{ modelValue: boolean; library: Library | null }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const tab = ref('policy')
const busy = ref(false)
const { acceptTask, panelOpen } = useTasks()
const policy = ref({
  auto_scan_enabled: true,
  scan_mode: 'native' as 'poll' | 'native',
  ts_policy: 'auto' as 'auto' | 'complete',
  scan_interval_seconds: 120,
  file_settle_seconds: 60,
  ignore_dirs: '',
})
const waiting = ref<WaitingFile[]>([]),
  waitingTotal = ref(0)
const suspects = ref<CleanupItem[]>([]),
  scanned = ref(0),
  totalIndexed = ref(0)
const cursor = ref<number | null>(0),
  checked = ref(false)
async function perform(work: () => Promise<void>) {
  busy.value = true
  try {
    await work()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    busy.value = false
  }
}
async function loadWaiting(reset = false) {
  if (!props.library) return
  const rows = await getWaitingFiles(props.library.id, reset ? 0 : waiting.value.length)
  waiting.value = reset ? rows.items : [...waiting.value, ...rows.items]
  waitingTotal.value = rows.total
}
watch(
  () => props.modelValue,
  (open) => {
    if (!open || !props.library) return
    const lib = props.library
    policy.value = {
      auto_scan_enabled: lib.auto_scan_enabled,
      scan_mode: lib.scan_mode || 'native',
      ts_policy: lib.ts_policy || 'auto',
      scan_interval_seconds: lib.effective_poll_interval_seconds || 120,
      file_settle_seconds: lib.effective_settle_seconds ?? 60,
      ignore_dirs: lib.effective_ignore_dirs || '',
    }
    tab.value = 'policy'
    suspects.value = []
    scanned.value = 0
    cursor.value = 0
    checked.value = false
    void perform(() => loadWaiting(true))
  },
)
async function save() {
  await perform(async () => {
    if (!props.library) return
    await updateLibrary(props.library.id, policy.value)
    emit('saved')
    ElMessage.success('扫描设置策略已保存')
  })
}
async function recheck() {
  await perform(async () => {
    if (!props.library) return
    acceptTask(await recheckWaiting(props.library.id))
    visible.value = false
    panelOpen.value = true
  })
}
async function inspect(reset = false) {
  await perform(async () => {
    if (!props.library || (!reset && cursor.value === null)) return
    const data = await cleanupPreview(props.library.id, reset ? 0 : cursor.value || 0)
    suspects.value = reset ? data.items : [...suspects.value, ...data.items]
    scanned.value = (reset ? 0 : scanned.value) + data.scanned
    totalIndexed.value = data.total_indexed
    cursor.value = data.next_cursor
    checked.value = true
  })
}
</script>

<template>
  <el-dialog v-model="visible" title="扫描设置" width="720px">
    <p class="tool-intro">{{ library?.name }} · {{ library?.path }}</p>
    <p v-if="library?.watch_error" class="tool-hint" role="alert">{{ library.watch_error }}</p>
    <el-tabs v-model="tab">
      <el-tab-pane label="扫描策略" name="policy">
        <el-form label-position="top">
          <el-form-item label="自动扫描"
            ><el-switch v-model="policy.auto_scan_enabled" aria-label="启用自动扫描" /><span
              class="tool-hint"
              >关闭后仅手动扫描；与自动刮削分别控制。</span
            ></el-form-item
          >
          <div class="policy-grid">
            <el-form-item label="监听方式"
              ><el-select v-model="policy.scan_mode" aria-label="监听方式"
                ><el-option label="轮询检测（网络共享可选）" value="poll" /><el-option
                  label="文件事件（仅处理变化路径）"
                  value="native" /></el-select
            ></el-form-item>
            <el-form-item v-if="policy.scan_mode === 'poll'" label="轮询基础间隔（秒）"
              ><el-input-number
                v-model="policy.scan_interval_seconds"
                :min="30"
                :max="86400"
                :step="30"
                aria-label="轮询基础间隔"
            /></el-form-item>
            <el-form-item label="文件连续稳定时间（秒）"
              ><el-input-number
                v-model="policy.file_settle_seconds"
                :min="0"
                :max="3600"
                aria-label="文件连续稳定时间"
            /></el-form-item>
          </div>
          <el-form-item label="TS 文件处理">
            <el-select v-model="policy.ts_policy" aria-label="TS 文件处理">
              <el-option label="自动区分完整影片与下载分片" value="auto" />
              <el-option label="完整文件（允许成组编号的 TS）" value="complete" />
            </el-select>
          </el-form-item>
          <p class="tool-hint">
            自动模式会暂缓成组编号或哈希命名的疑似 TS
            分片，只记录一个待确认项。若实际是完整录像，可选择“完整文件”后重新扫描。播放清单明确引用的分片及下载临时目录仍会跳过。
          </p>
          <p v-if="policy.scan_mode === 'native'" class="tool-hint">
            仅在文件变化后处理对应路径，不做定时全库核对。首次入库、服务停机期间的变化或事件遗漏，可手动扫描。监听不可用时会提示，不会自动切换到轮询。
          </p>
          <p v-else class="tool-hint">轮询会按间隔检查目录和文件属性，只对变化路径建任务；空闲时延长间隔，不做定时全库核对。</p>
          <p class="tool-hint">
            稳定时间为 0
            会关闭时间等待，过程文件和下载状态文件仍被拦截。刮削查询直接使用原文件名，不做番号识别。
          </p>
          <el-form-item label="排除的子目录名（逗号分隔）"
            ><el-input
              v-model="policy.ignore_dirs"
              type="textarea"
              :rows="2"
              aria-label="排除的子目录名"
          /></el-form-item>
          <el-button type="primary" :loading="busy" @click="save">保存扫描策略</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="等待与清理" name="review">
        <div class="review-header">
          <h3>等待就绪 · {{ waitingTotal }}</h3>
          <el-button :loading="busy" :disabled="!waitingTotal" @click="recheck"
            >复查待就绪文件</el-button
          >
        </div>
        <p class="tool-hint">开启自动扫描会自动复查；手动模式可点击复查。等待不会阻塞其他任务。</p>
        <ul class="tool-list">
          <li v-for="row in waiting" :key="row.path">
            <strong>{{ row.filename }}</strong><span>{{ row.reason }}</span>
          </li>
        </ul>
        <el-button v-if="waiting.length < waitingTotal" text @click="perform(() => loadWaiting())"
          >加载更多等待文件</el-button
        >
        <el-button text @click="perform(() => loadWaiting(true))">刷新等待列表</el-button>
        <div class="review-header">
          <h3>疑似过程文件</h3>
          <el-button :loading="busy" @click="inspect(true)">开始只读检查</el-button>
        </div>
        <p class="tool-hint">
          只检查已有索引并给出疑似原因，不删除磁盘文件，也不移除索引。下载暂停也可能看起来稳定，结果需要人工判断。
        </p>
        <p v-if="checked" class="tool-hint">
          已检查 {{ scanned }} / {{ totalIndexed }} 条索引 · 发现 {{ suspects.length }} 个疑似项{{
            cursor === null ? ' · 检查完成' : ''
          }}
        </p>
        <ul class="tool-list">
          <li v-for="row in suspects" :key="row.id">
            <strong>{{ row.filename }}</strong><span>{{ row.reason }}</span
            ><small>{{ row.path }}</small>
          </li>
        </ul>
        <el-button v-if="checked && cursor !== null" :loading="busy" @click="inspect()"
          >继续检查下一批</el-button
        >
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<style scoped>
.tool-intro {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
  margin: 0 0 20px;
}
.policy-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}
.policy-grid .el-select,
.policy-grid .el-input-number {
  width: 100%;
}
.tool-hint {
  display: block;
  font-size: 11px;
  line-height: 1.8;
  color: var(--muted);
  margin: 8px 0 18px;
}
.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 24px;
  flex-wrap: wrap;
}
h3 {
  margin: 0;
  font-size: 14px;
}
.tool-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 270px;
  overflow: auto;
}
.tool-list li {
  display: grid;
  gap: 6px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.tool-list span,
.tool-list small {
  color: var(--muted);
  line-height: 1.7;
}
@media (max-width: 640px) {
  .policy-grid {
    grid-template-columns: 1fr;
  }
  .el-button {
    min-height: 44px;
  }
}
</style>
