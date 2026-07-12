import type { MediaSort } from '@/api/types'

export const MEDIA_SORT_KEY = 'tv.media_sort'
export const DEFAULT_MEDIA_SORT: MediaSort = 'created_desc'

export const MEDIA_SORT_OPTIONS: { value: MediaSort; label: string }[] = [
  { value: 'created_desc', label: '入库时间 · 新→旧' },
  { value: 'created_asc', label: '入库时间 · 旧→新' },
  { value: 'number_asc', label: '番号 · A→Z' },
  { value: 'number_desc', label: '番号 · Z→A' },
  { value: 'release_desc', label: '发行日期 · 新→旧' },
  { value: 'release_asc', label: '发行日期 · 旧→新' },
]

const VALID = new Set(MEDIA_SORT_OPTIONS.map((o) => o.value))

export function loadMediaSort(): MediaSort {
  try {
    const v = localStorage.getItem(MEDIA_SORT_KEY) || ''
    if (VALID.has(v as MediaSort)) return v as MediaSort
  } catch {
    /* ignore */
  }
  return DEFAULT_MEDIA_SORT
}

export function saveMediaSort(sort: MediaSort) {
  try {
    localStorage.setItem(MEDIA_SORT_KEY, sort)
  } catch {
    /* ignore */
  }
}
