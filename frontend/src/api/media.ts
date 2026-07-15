import client from './client'
import type {
  Actor,
  AuthStatus,
  Health,
  Library,
  LoginResult,
  MediaDetail,
  PaginatedActors,
  PaginatedMedia,
  PlayInfo,
  Progress,
  ScanJob,
  Settings,
} from './types'

export const getHealth = () => client.get<Health>('/health').then((r) => r.data)

export const getAuthStatus = () => client.get<AuthStatus>('/auth/status').then((r) => r.data)

export const login = (password: string) =>
  client.post<LoginResult>('/auth/login', { password }).then((r) => r.data)

export const listLibraries = () => client.get<Library[]>('/libraries').then((r) => r.data)

export const createLibrary = (body: {
  name: string
  path: string
  type?: string
  auto_scan_enabled?: boolean
  scan_interval_hours?: number | null
  scan_interval_seconds?: number | null
}) => client.post<Library>('/libraries', body).then((r) => r.data)

export const updateLibrary = (
  id: number,
  body: Partial<{
    name: string
    path: string
    type: string
    enabled: boolean
    auto_scan_enabled: boolean
    scan_interval_hours: number | null
    scan_interval_seconds: number | null
  }>,
) => client.patch<Library>(`/libraries/${id}`, body).then((r) => r.data)

export const deleteLibrary = (id: number) => client.delete(`/libraries/${id}`)

export const scanLibrary = (id: number) =>
  client.post<ScanJob>(`/libraries/${id}/scan`).then((r) => r.data)

export const rescrapePendingLibrary = (id: number) =>
  client.post<ScanJob>(`/libraries/${id}/rescrape-pending`).then((r) => r.data)

export const getScanJob = (jobId: string) =>
  client.get<ScanJob>(`/scan/jobs/${jobId}`).then((r) => r.data)

export const listMedia = (params: {
  q?: string
  library_id?: number
  favorited?: boolean
  sort?: string
  page?: number
  page_size?: number
}) => client.get<PaginatedMedia>('/media', { params }).then((r) => r.data)

export const getMedia = (id: number) => client.get<MediaDetail>(`/media/${id}`).then((r) => r.data)

export const rescrapeMedia = (
  id: number,
  body?: { provider?: string; fallback?: boolean; number?: string },
) => client.post<MediaDetail>(`/media/${id}/rescrape`, body || {}).then((r) => r.data)

export const favoriteMedia = (id: number) =>
  client.post<MediaDetail>(`/media/${id}/favorite`).then((r) => r.data)

export const unfavoriteMedia = (id: number) =>
  client.delete<MediaDetail>(`/media/${id}/favorite`).then((r) => r.data)

export const listFavorites = (params?: { page?: number; page_size?: number; sort?: string }) =>
  client.get<PaginatedMedia>('/favorites', { params }).then((r) => r.data)

export const listFavoriteActors = (params?: { page?: number; page_size?: number }) =>
  client.get<PaginatedActors>('/favorites/actors', { params }).then((r) => r.data)

export const listActors = (params?: { q?: string; page?: number; page_size?: number }) =>
  client.get<PaginatedActors>('/actors', { params }).then((r) => r.data)

export const getActor = (id: number) => client.get<Actor>(`/actors/${id}`).then((r) => r.data)

export const favoriteActor = (id: number) =>
  client.post<Actor>(`/actors/${id}/favorite`).then((r) => r.data)

export const unfavoriteActor = (id: number) =>
  client.delete<Actor>(`/actors/${id}/favorite`).then((r) => r.data)

export const rescrapeActorImage = (id: number) =>
  client.post<Actor>(`/actors/${id}/rescrape-image`).then((r) => r.data)

export const listActorMedia = (
  id: number,
  params?: { page?: number; page_size?: number; sort?: string },
) => client.get<PaginatedMedia>(`/actors/${id}/media`, { params }).then((r) => r.data)

export const playMedia = (id: number) => client.get<PlayInfo>(`/media/${id}/play`).then((r) => r.data)

export const getProgress = (id: number) =>
  client.get<Progress>(`/media/${id}/progress`).then((r) => r.data)

export const putProgress = (id: number, body: { position_sec: number; duration_sec?: number }) =>
  client.put<Progress>(`/media/${id}/progress`, body).then((r) => r.data)

export const getSettings = () => client.get<Settings>('/settings').then((r) => r.data)

export const updateSettings = (body: Record<string, unknown>) =>
  client.put<Settings>('/settings', body).then((r) => r.data)

export const getMovieProviders = () =>
  client
    .get<{
      movie_providers?: string[]
      count?: number
      data?: unknown
      from_cache?: boolean
    }>('/settings/providers')
    .then((r) => r.data)
