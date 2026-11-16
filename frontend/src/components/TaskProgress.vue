<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppIcon from './AppIcon.vue'
import type { BackgroundTask, TaskItem } from '@/api/types'
import { listFailedItems } from '@/api/tasks'
import { isActiveTask, taskStatus, taskTitle, useTasks } from '@/composables/useTasks'
import { getErrorMessage } from '@/utils/errors'

const props = defineProps<{ task: BackgroundTask }>()
const { busy, control, panelOpen } = useTasks()
const failures = ref<TaskItem[]>([])
const expanded = ref(false)
const loadingFailures = ref(false)
const percentage = computed(() =>
  props.task.total ? Math.min(100, Math.round((props.task.processed / props.task.total) * 100)) : 0,
)
const phase = computed(
  () =>
    (
      ({
        queued: '等待执行',
        discovering: '建立清单',
        index: '扫描文件',
        scrape: '刮削元数据',
        prune: '核对文件',
      }) as Record<string, string>
    )[props.task.phase] || '',
)

async function act(action: 'cancel' | 'resume' | 'retry') {
  try {
    await control(props.task, action)
    ElMessage.success(
      action === 'cancel'
        ? '已请求取消，当前条目结束后停止'
        : action === 'retry'
          ? '失败条目已加入重试队列'
          : '已加入继续执行队列',
    )
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
async function loadFailures() {
  loadingFailures.value = true
  try {
    const jobId = props.task.job_id
    const rows = await listFailedItems(jobId, failures.value.length)
    if (jobId === props.task.job_id) {
      failures.value.push(...rows)
      expanded.value = true
    }
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '获取失败条目失败'))
  } finally {
    loadingFailures.value = false
  }
}
watch(
  () => props.task.job_id,
  () => {
    failures.value = []
    expanded.value = false
  },
)
</script>

<template>
  <article class="task-card" :data-task-id="task.job_id" :aria-label="taskTitle(task)">
    <div class="task-heading">
      <span class="task-kind"><AppIcon name="clock" :size="16" />{{ taskTitle(task) }}</span>
      <span
        class="task-status"
        :class="{ warning: task.failed || task.status === 'interrupted' }"
        >{{ taskStatus(task) }}</span
      >
    </div>
    <p class="task-library">
      {{ task.library_name }}<span v-if="task.parent_id"> · 失败重试</span>
    </p>
    <router-link
      v-if="task.media_id && task.media_label"
      class="task-target"
      :to="'/media/' + task.media_id"
      @click="panelOpen = false"
      >{{ task.media_label }}</router-link
    >
    <div class="task-counts" aria-live="polite">
      <strong
        >{{ task.processed
        }}<span> / {{ task.total }} {{ task.kind === 'scan' ? '步' : '部' }}</span></strong
      >
      <span>成功 {{ task.succeeded }} · 失败 {{ task.failed }} · 跳过 {{ task.skipped }}</span>
    </div>
    <div
      class="task-track"
      role="progressbar"
      aria-label="任务进度"
      :aria-valuenow="percentage"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <i :style="{ width: percentage + '%' }" />
    </div>
    <p v-if="isActiveTask(task) && task.current" class="task-current">
      {{ phase }} · {{ task.current }}
    </p>
    <p class="task-message">{{ task.message || phase }}</p>
    <p v-if="task.kind === 'scan'" class="task-message">
      已扫描 {{ task.scanned }} · 新增 {{ task.created }} · 移除 {{ task.removed }} · 已刮削
      {{ task.scraped }}
    </p>
    <div class="task-actions">
      <el-button
        v-if="isActiveTask(task)"
        size="small"
        :loading="busy === task.job_id"
        :disabled="task.cancel_requested"
        @click="act('cancel')"
        >{{ task.cancel_requested ? '等待当前条目结束' : '取消任务' }}</el-button
      >
      <el-button
        v-if="task.resumable"
        size="small"
        :loading="busy === task.job_id"
        @click="act('resume')"
        >继续未完成</el-button
      >
      <el-button
        v-if="task.retryable"
        size="small"
        :loading="busy === task.job_id"
        @click="act('retry')"
        >重试失败（{{ task.failed }}）</el-button
      >
      <el-button
        v-if="task.failed"
        size="small"
        text
        :loading="loadingFailures"
        @click="
          expanded ? (expanded = false) : failures.length ? (expanded = true) : loadFailures()
        "
        >{{ expanded ? '收起失败条目' : '查看失败条目' }}</el-button
      >
    </div>
    <ul v-if="expanded" class="task-failures">
      <li v-for="failure in failures" :key="failure.id">
        <strong>{{ failure.label }}</strong><span>{{ failure.error }}</span>
      </li>
      <li v-if="failures.length < task.failed">
        <el-button text :loading="loadingFailures" @click="loadFailures"
          >加载更多失败条目</el-button
        >
      </li>
    </ul>
  </article>
</template>

<style scoped>
.task-target {
  display: block;
  margin: -8px 0 16px;
  color: var(--accent);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.task-card {
  padding: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--bg-elevated);
  min-width: 0;
}
.task-heading,
.task-kind,
.task-counts {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.task-kind {
  justify-content: flex-start;
  font-size: 13px;
  font-weight: 600;
}
.task-status {
  font-size: 11px;
  color: var(--accent);
  white-space: nowrap;
}
.task-status.warning {
  color: var(--danger);
}
.task-library {
  margin: 9px 0 18px;
  color: var(--muted);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.task-counts {
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 11px;
  color: var(--muted);
}
.task-counts strong {
  color: var(--text);
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}
.task-counts strong span {
  color: var(--faint);
  font-size: 12px;
  font-weight: 400;
}
.task-track {
  height: 4px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--border-subtle);
}
.task-track i {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 0.2s;
}
.task-current,
.task-message {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.7;
  overflow-wrap: anywhere;
  margin: 10px 0 0;
}
.task-current {
  color: var(--text);
}
.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.task-actions:empty {
  display: none;
}
.task-actions .el-button {
  margin: 0;
  min-height: 36px;
}
.task-failures {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  border-top: 1px solid var(--border-subtle);
}
.task-failures li {
  display: grid;
  gap: 5px;
  padding: 10px 0;
  font-size: 11px;
  overflow-wrap: anywhere;
}
.task-failures span {
  color: var(--muted);
  line-height: 1.7;
}
@media (max-width: 640px) {
  .task-actions .el-button {
    min-height: 44px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .task-track i {
    transition: none;
  }
}
</style>
