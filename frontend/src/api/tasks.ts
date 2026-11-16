import client from './client'
import type { BackgroundTask, TaskItem } from './types'

export const listTasks = (
  params?: { active_only?: boolean; limit?: number; offset?: number },
  signal?: AbortSignal,
) => client.get<BackgroundTask[]>('/tasks', { params, signal }).then((r) => r.data)

export const taskAction = (id: string, action: 'cancel' | 'resume' | 'retry') =>
  client.post<BackgroundTask>(`/tasks/${id}/${action}`).then((r) => r.data)

export const listFailedItems = (id: string, offset = 0) =>
  client
    .get<TaskItem[]>(`/tasks/${id}/items`, { params: { status: 'failed', limit: 50, offset } })
    .then((r) => r.data)
