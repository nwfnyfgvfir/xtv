export interface Library {
  id: number
  name: string
  path: string
  type: string
  enabled: boolean
  auto_scan_enabled?: boolean
  scan_interval_hours?: number | null
  scan_interval_seconds?: number | null
  media_count?: number
  /** Bumped when library media is added/removed/scraped (LibraryChanged-style). */
  content_revision?: number
  created_at: string
}

/** Subdirectory entry under MEDIA_ROOT (library path picker). */
export interface BrowseDirEntry {
  name: string
  path: string
}

export interface BrowseDirsOut {
  path: string
  parent: string | null
  directories: BrowseDirEntry[]
}

export interface MediaListItem {
  id: number
  library_id: number
  filename: string
  number?: string | null
  title?: string | null
  cover_url?: string | null
  thumb_url?: string | null
  source_type: string
  provider?: string | null
  release_date?: string | null
  score?: number | null
  scraped_at?: string | null
  favorited?: boolean
  subtitle_flag?: string | null
  disc?: string | null
}

export interface Actor {
  id: number
  name: string
  provider?: string | null
  provider_id?: string | null
  image_url?: string | null
  media_count?: number
  favorited?: boolean
}

export interface MediaDetail extends MediaListItem {
  path: string
  plot?: string | null
  provider_id?: string | null
  runtime?: number | null
  studio?: string | null
  backdrop_url?: string | null
  strm_target?: string | null
  tags_json?: string | null
  file_size?: number | null
  created_at: string
  updated_at: string
  actors: Actor[]
}

export interface PaginatedMedia {
  items: MediaListItem[]
  total: number
  page: number
  page_size: number
}

export interface PaginatedActors {
  items: Actor[]
  total: number
  page: number
  page_size: number
}

export interface SubtitleTrack {
  name: string
  url: string
  type: 'srt' | 'vtt' | 'ass'
  filename: string
  default?: boolean
}

export interface PlayInfo {
  play_url: string
  kind: 'local' | 'direct' | 'alist'
  headers?: Record<string, string> | null
  subtitles?: SubtitleTrack[]
}

export interface Progress {
  media_id: number
  position_sec: number
  duration_sec?: number | null
  updated_at?: string | null
}

export type ImageProxyMode = 'site' | 'metatube' | 'external'

export type TranslateProvider = 'google' | 'bing'

export type MediaSort =
  | 'number_asc'
  | 'number_desc'
  | 'created_asc'
  | 'created_desc'
  | 'release_asc'
  | 'release_desc'

export type ActorSort = 'media_count_desc' | 'debut_asc' | 'debut_desc'

export interface Settings {
  metatube_base_url: string
  metatube_token_set: boolean
  metatube_provider?: string
  metatube_provider_priority?: string[]
  metatube_fallback?: boolean
  alist_base_url: string
  alist_token_set: boolean
  media_root: string
  auto_scrape: boolean
  auto_translate?: boolean
  translate_provider?: TranslateProvider
  image_proxy_mode?: ImageProxyMode
  image_external_proxy_url?: string
  image_local_cache?: boolean
  scan_extensions: string
  cors_origins: string
  auth_enabled?: boolean
  movie_providers?: string[]
  movie_providers_error?: string | null
  movie_providers_from_cache?: boolean
  extra: Record<string, string>
}

export interface ScanJob {
  job_id: string
  status: string
  library_id?: number | null
  scanned: number
  created: number
  scraped: number
  removed?: number
  errors: string[]
  message?: string | null
}

export interface Health {
  status: string
  metatube?: { ok?: boolean; data?: unknown; error?: string } | null
  auth_enabled?: boolean
  scheduler?: { running?: boolean; jobs?: { id: string; next_run_time?: string | null }[] } | null
}

export interface AuthStatus {
  auth_enabled: boolean
  authenticated: boolean
}

export interface LoginResult {
  access_token: string
  token_type: string
  auth_enabled: boolean
}
