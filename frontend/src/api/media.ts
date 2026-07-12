import client from './client'
import type {
  Health,
  Library,
  MediaDetail,
  PaginatedMedia,
  PlayInfo,
  Progress,
  ScanJob,
  Settings,
} from './types'

export const getHealth = () => client.get<Health>('/health').then((r) => r.data)

export const listLibraries = () => client.get<Library[]>('/libraries').then((r) => r.data)

export const createLibrary = (body: { name: string; path: string; type?: string }) =>
  client.post<Library>('/libraries', body).then((r) => r.data)

export const deleteLibrary = (id: number) => client.delete(`/libraries/${id}`)

export const scanLibrary = (id: number) =>
  client.post<ScanJob>(`/libraries/${id}/scan`).then((r) => r.data)

export const getScanJob = (jobId: string) =>
  client.get<ScanJob>(`/scan/jobs/${jobId}`).then((r) => r.data)

export const listMedia = (params: {
  q?: string
  library_id?: number
  page?: number
  page_size?: number
}) => client.get<PaginatedMedia>('/media', { params }).then((r) => r.data)

export const getMedia = (id: number) => client.get<MediaDetail>(`/media/${id}`).then((r) => r.data)

export const rescrapeMedia = (id: number) =>
  client.post<MediaDetail>(`/media/${id}/rescrape`).then((r) => r.data)

export const playMedia = (id: number) => client.get<PlayInfo>(`/media/${id}/play`).then((r) => r.data)

export const getProgress = (id: number) =>
  client.get<Progress>(`/media/${id}/progress`).then((r) => r.data)

export const putProgress = (id: number, body: { position_sec: number; duration_sec?: number }) =>
  client.put<Progress>(`/media/${id}/progress`, body).then((r) => r.data)

export const getSettings = () => client.get<Settings>('/settings').then((r) => r.data)

export const updateSettings = (body: Record<string, unknown>) =>
  client.put<Settings>('/settings', body).then((r) => r.data)
