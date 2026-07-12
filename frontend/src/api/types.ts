export interface Library {
  id: number
  name: string
  path: string
  type: string
  enabled: boolean
  created_at: string
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
}

export interface Actor {
  id: number
  name: string
  provider?: string | null
  provider_id?: string | null
  image_url?: string | null
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
  disc?: string | null
  subtitle_flag?: string | null
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

export interface PlayInfo {
  play_url: string
  kind: 'local' | 'direct' | 'alist'
  headers?: Record<string, string> | null
}

export interface Progress {
  media_id: number
  position_sec: number
  duration_sec?: number | null
  updated_at?: string | null
}

export interface Settings {
  metatube_base_url: string
  metatube_token_set: boolean
  alist_base_url: string
  alist_token_set: boolean
  media_root: string
  auto_scrape: boolean
  scan_extensions: string
  cors_origins: string
  extra: Record<string, string>
}

export interface ScanJob {
  job_id: string
  status: string
  library_id?: number | null
  scanned: number
  created: number
  scraped: number
  errors: string[]
  message?: string | null
}

export interface Health {
  status: string
  metatube?: { ok?: boolean; data?: unknown; error?: string } | null
}
