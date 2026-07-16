import type { ActorSort } from '@/api/types'

export const ACTOR_SORT_KEY = 'tv.actor_sort'
export const DEFAULT_ACTOR_SORT: ActorSort = 'media_count_desc'

export const ACTOR_SORT_OPTIONS: { value: ActorSort; label: string }[] = [
  { value: 'media_count_desc', label: '作品数 · 多→少' },
  { value: 'debut_desc', label: '出道日期 · 新→旧' },
  { value: 'debut_asc', label: '出道日期 · 旧→新' },
]

const VALID = new Set(ACTOR_SORT_OPTIONS.map((o) => o.value))

export function loadActorSort(): ActorSort {
  try {
    const v = localStorage.getItem(ACTOR_SORT_KEY) || ''
    if (VALID.has(v as ActorSort)) return v as ActorSort
  } catch {
    /* ignore */
  }
  return DEFAULT_ACTOR_SORT
}

export function saveActorSort(sort: ActorSort) {
  try {
    localStorage.setItem(ACTOR_SORT_KEY, sort)
  } catch {
    /* ignore */
  }
}
