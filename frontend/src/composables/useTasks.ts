import { computed, ref } from 'vue'
import { listTasks, taskAction } from '@/api/tasks'
import type { BackgroundTask } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'

const tasks = ref<BackgroundTask[]>([])
const panelOpen = ref(false)
const connectionError = ref('')
const busy = ref('')
let timer: number | undefined
let enabled = false
let generation = 0
let flight: Promise<void> | null = null
let controller: AbortController | null = null

export function isActiveTask(task: BackgroundTask) {
  return ['pending', 'running', 'cancelling'].includes(task.status)
}

export function taskStatus(task: BackgroundTask): string {
  if (task.status === 'done' && task.failed) return '部分失败'
  return (
    (
      {
        pending: '排队中',
        running: '执行中',
        cancelling: '正在取消',
        done: '已完成',
        error: '执行失败',
        cancelled: '已取消',
        interrupted: '已中断',
      } as Record<string, string>
    )[task.status] || task.status
  )
}

export function taskTitle(task: BackgroundTask): string {
  return { scan: '扫描媒体库', rescrape_pending: '批量补刮', rescrape: '单片重刮' }[task.kind]
}

function schedule(delay = 2000) {
  window.clearTimeout(timer)
  if (enabled) timer = window.setTimeout(() => void refreshTasks(), delay)
}

export function refreshTasks(): Promise<void> {
  if (flight) return flight
  const version = generation
  const knownAtStart = new Set(tasks.value.map((task) => task.job_id))
  const requestController = new AbortController()
  controller = requestController
  const signal = requestController.signal
  flight = (async () => {
    try {
      const [recent, active] = await Promise.all([
        listTasks(undefined, signal),
        listTasks({ active_only: true, limit: 200 }, signal),
      ])
      if (version !== generation) return
      const merged = new Map<string, BackgroundTask>()
      for (const task of [...recent, ...active]) {
        const previous = merged.get(task.job_id)
        if (!previous || task.updated_at > previous.updated_at) merged.set(task.job_id, task)
      }
      // An older in-flight response must not erase a just-submitted task or action.
      for (const task of tasks.value) {
        const previous = merged.get(task.job_id)
        if (previous ? task.updated_at > previous.updated_at : !knownAtStart.has(task.job_id))
          merged.set(task.job_id, task)
      }
      tasks.value = [...merged.values()].sort(
        (a, b) =>
          Number(isActiveTask(b)) - Number(isActiveTask(a)) ||
          b.created_at.localeCompare(a.created_at),
      )
      connectionError.value = ''
    } catch (error) {
      requestController.abort()
      if (version === generation)
        connectionError.value = getErrorMessage(error, '暂时无法获取进度，连接恢复后会自动重试')
    } finally {
      if (version === generation) {
        flight = null
        schedule(tasks.value.some(isActiveTask) || connectionError.value ? 2000 : 10000)
      }
    }
  })()
  return flight
}

export function startTaskPolling() {
  if (enabled) return
  enabled = true
  void refreshTasks()
}

export function stopTaskPolling() {
  enabled = false
  generation++
  controller?.abort()
  flight = null
  window.clearTimeout(timer)
  tasks.value = []
  panelOpen.value = false
}

export function acceptTask(task: BackgroundTask) {
  tasks.value = [task, ...tasks.value.filter((row) => row.job_id !== task.job_id)]
  schedule(500)
}

export function useTasks() {
  async function control(task: BackgroundTask, action: 'cancel' | 'resume' | 'retry') {
    if (busy.value) return
    busy.value = task.job_id
    try {
      acceptTask(await taskAction(task.job_id, action))
      await refreshTasks()
    } finally {
      busy.value = ''
    }
  }
  return {
    tasks,
    activeTasks: computed(() => tasks.value.filter(isActiveTask)),
    panelOpen,
    connectionError,
    busy,
    control,
    refreshTasks,
    acceptTask,
  }
}
