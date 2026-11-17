export interface Library {
  id: number
  name: string
  path: string
  type: string
  enabled: boolean
  auto_scan_enabled: boolean
  scan_mode: 'poll' | 'native'
  ts_policy: 'auto' | 'complete'
  scan_interval_seconds: number | null
  file_settle_seconds: number | null
  ignore_dirs: string | null
  effective_settle_seconds: number
  effective_poll_interval_seconds: number
  effective_ignore_dirs: string
  waiting_files: number
  watch_mode?: string | null
  watch_error?: string | null
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
  backdrop_url?: string | null
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

export interface DuplicateMediaItem extends MediaListItem {
  path: string
  file_size?: number | null
  library_name: string
}

export interface DuplicateGroup {
  number: string
  count: number
  items: DuplicateMediaItem[]
}

export interface PaginatedDuplicateGroups {
  items: DuplicateGroup[]
  total: number
  page: number
  page_size: number
}

export interface BatchDeleteResult {
  deleted: number[]
  failed: { id: number; error: string }[]
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
  kind: 'local' | 'direct'
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
export type ScrapeSource = 'metatube' | 'stash' | 'stashscrapers'

export type TranslateProvider = 'google' | 'bing' | 'deepl' | 'ai'

export type MediaSort =
  'number_asc' | 'number_desc' | 'created_asc' | 'created_desc' | 'release_asc' | 'release_desc'

export type ActorSort = 'media_count_desc' | 'debut_asc' | 'debut_desc'

export interface Settings {
  task_concurrency?: number
  scrape_source?: ScrapeSource
  stashscrapers_base_url?: string
  stashscrapers_token_set?: boolean
  stashscrapers_scraper?: string
  stashscrapers_scraper_priority?: string[]
  stashscrapers_fallback?: boolean
  stash_base_url?: string
  stash_api_key_set?: boolean
  stash_scraper?: string
  stash_scraper_priority?: string[]
  stash_fallback?: boolean
  metatube_base_url: string
  metatube_token_set: boolean
  metatube_provider?: string
  metatube_provider_priority?: string[]
  metatube_fallback?: boolean
  media_root: string
  auto_scrape: boolean
  auto_translate?: boolean
  translate_provider?: TranslateProvider
  translate_google_proxy?: boolean
  translate_google_proxy_url?: string
  translate_deepl_api_key_set?: boolean
  translate_deepl_api_url?: string
  translate_deepl_free?: boolean
  translate_deepl_proxy?: boolean
  translate_deepl_proxy_url?: string
  translate_ai_api_url?: string
  translate_ai_api_key_set?: boolean
  translate_ai_model?: string
  image_proxy_mode?: ImageProxyMode
  image_external_proxy_url?: string
  image_local_cache?: boolean
  scan_extensions: string
  cors_origins: string
  auth_enabled?: boolean
  movie_providers?: string[]
  movie_provider_labels?: Record<string, string>
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

export interface BackgroundTask extends ScanJob {
  running_items?: number
  kind: 'scan' | 'rescrape_pending' | 'rescrape'
  waiting: number
  media_id: number | null
  media_label: string | null
  library_name: string
  parent_id: string | null
  phase: string
  current: string | null
  total: number
  processed: number
  succeeded: number
  failed: number
  skipped: number
  cancel_requested: boolean
  retryable: boolean
  resumable: boolean
  created_at: string
  updated_at: string
  finished_at: string | null
}

export interface WaitingFile {
  path: string
  filename: string
  state: string
  reason: string
}
export interface CleanupItem extends WaitingFile {
  id: number
  number: string | null
}
export interface CleanupPreview {
  items: CleanupItem[]
  scanned: number
  total_indexed: number
  next_cursor: number | null
  read_only: boolean
}

export interface TaskItem {
  id: number
  phase: string
  label: string
  media_id: number | null
  status: string
  error: string | null
}

export interface Health {
  status: string
  metatube?: { ok?: boolean; data?: unknown; error?: string } | null
  stash?: { ok?: boolean; data?: unknown; error?: string } | null
  stashscrapers?: { ok?: boolean; data?: unknown; error?: string } | null
  scrape_source?: ScrapeSource
  auth_enabled?: boolean
  watcher?: {
    running?: boolean
    watched_library_ids?: number[]
    pending_scans?: number[]
    libraries?: { id: number; name?: string; mode: string; error: string | null }[]
  } | null
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
