import type { PlayInfo } from '@/api/types'

export type Platform = 'Windows' | 'MacOS' | 'Linux' | 'Android' | 'iOS' | 'Unknown'

export interface ExternalPlayer {
  icon: string
  name: string
  scheme: string
  platforms: Platform[]
}

/** Aligned with OpenList-Frontend video_box.tsx players list. */
export const EXTERNAL_PLAYERS: ExternalPlayer[] = [
  {
    icon: 'iina',
    name: 'IINA',
    scheme: 'iina://weblink?url=$edurl',
    platforms: ['MacOS'],
  },
  {
    icon: 'potplayer',
    name: 'PotPlayer',
    scheme: 'potplayer://$durl',
    platforms: ['Windows'],
  },
  {
    icon: 'vlc',
    name: 'VLC',
    scheme: 'vlc://$durl',
    platforms: ['Windows', 'MacOS', 'Linux', 'Android', 'iOS'],
  },
  {
    icon: 'android',
    name: 'Android',
    scheme: 'intent:$durl#Intent;type=video/*;S.title=$name;end',
    platforms: ['Android'],
  },
  {
    icon: 'nplayer',
    name: 'nPlayer',
    scheme: 'nplayer-$durl',
    platforms: ['Android', 'iOS'],
  },
  {
    icon: 'omniplayer',
    name: 'OmniPlayer',
    scheme: 'omniplayer://weblink?url=$durl',
    platforms: ['MacOS'],
  },
  {
    icon: 'figplayer',
    name: 'Fig Player',
    scheme: 'figplayer://weblink?url=$durl',
    platforms: ['Windows', 'MacOS'],
  },
  {
    icon: 'vivid',
    name: 'Vivid Player',
    scheme: 'vividplayer://play?src=direct&u=$edurl&title=$name',
    platforms: ['Windows'],
  },
  {
    icon: 'infuse',
    name: 'Infuse',
    scheme: 'infuse://x-callback-url/play?url=$durl',
    platforms: ['MacOS', 'iOS'],
  },
  {
    icon: 'fileball',
    name: 'Fileball',
    scheme: 'filebox://play?url=$durl',
    platforms: ['MacOS', 'iOS'],
  },
  {
    icon: 'mxplayer',
    name: 'MX Player',
    scheme: 'intent:$durl#Intent;package=com.mxtech.videoplayer.ad;S.title=$name;end',
    platforms: ['Android'],
  },
  {
    icon: 'mxplayer-pro',
    name: 'MX Player Pro',
    scheme: 'intent:$durl#Intent;package=com.mxtech.videoplayer.pro;S.title=$name;end',
    platforms: ['Android'],
  },
  {
    icon: 'iPlay',
    name: 'iPlay',
    scheme: 'iplay://play/any?type=url&url=$bdurl',
    platforms: ['iOS'],
  },
  {
    icon: 'mpv',
    name: 'mpv',
    scheme: 'mpv://$edurl',
    platforms: ['Windows', 'MacOS', 'Linux', 'Android'],
  },
]

const SHOW_ALL_KEY = 'tv_show_all_players'

export function getPlatform(): Platform {
  if (typeof window === 'undefined') return 'Unknown'
  const ua = window.navigator.userAgent
  const platform = window.navigator.platform ?? ''

  if (/android/i.test(ua)) return 'Android'
  if (
    /iPad|iPhone|iPod/.test(ua) ||
    (platform.includes('Mac') && navigator.maxTouchPoints > 1)
  ) {
    return 'iOS'
  }
  if (/windows/i.test(ua)) return 'Windows'
  if (/macintosh|mac os x/i.test(ua)) return 'MacOS'
  if (/linux/i.test(ua)) return 'Linux'
  return 'Unknown'
}

export type ConvertURLArgs = {
  raw_url: string
  name: string
  d_url: string
}

/** Port of OpenList convertURL (str.ts) — $name / $[eb_]*url / $[eb_]*durl. */
export function convertURL(scheme: string, args: ConvertURLArgs): string {
  let ans = scheme
  ans = ans.replaceAll('$name', args.name)

  const applyOps = (url: string, token: string): string => {
    const op = token.match(/[eb]/g)
    let u = url
    if (op) {
      for (const o of op.reverse()) {
        if (o === 'e') {
          u = encodeURIComponent(u)
        } else if (o === 'b') {
          u = window.btoa(u)
        }
      }
    }
    return u
  }

  // Match $durl / $edurl / $bdurl before $url / $eurl / $burl
  ans = ans.replace(/\$[eb_]*durl/g, (old) => applyOps(args.d_url, old))
  ans = ans.replace(/\$[eb_]*url/g, (old) => applyOps(args.raw_url, old))
  return ans
}

/**
 * Base origin for local /api/stream URLs.
 * External apps cannot use the Vite :5173 proxy — point at backend :8000.
 * Prefer current hostname (LAN IP) over hard-coded 127.0.0.1 so intranet clients work.
 */
export function streamBaseOrigin(): string {
  if (typeof window === 'undefined') return ''
  const { origin, port, protocol, hostname } = window.location
  if (import.meta.env.DEV && (port === '5173' || port === '5174')) {
    return `${protocol}//${hostname}:8000`
  }
  return origin
}

export function toAbsolutePlayUrl(play: PlayInfo): string {
  const url = (play.play_url || '').trim()
  if (!url) throw new Error('empty play_url')
  if (play.kind === 'local' || url.startsWith('/')) {
    const base = streamBaseOrigin() || window.location.origin
    // Ensure single leading slash path join via URL
    return new URL(url.startsWith('/') ? url : `/${url}`, base.endsWith('/') ? base : `${base}/`)
      .href
  }
  return url
}

/**
 * Launch a custom-protocol URL (potplayer://, vlc://, …).
 *
 * Chromium often rewrites nested URLs when assigning to location/href on an <a>
 * (potplayer://http://host → potplayer://http//host, dropping the colon). Keep the
 * raw scheme string out of the HTML parser by using an iframe + location.assign.
 */
export function launchScheme(href: string): void {
  if (!href) throw new Error('empty scheme href')

  // 1) Hidden iframe — does not parse href as a nested URL attribute as aggressively
  try {
    const iframe = document.createElement('iframe')
    iframe.style.cssText = 'display:none;width:0;height:0;border:0;position:absolute'
    iframe.setAttribute('aria-hidden', 'true')
    document.body.appendChild(iframe)
    const idoc = iframe.contentWindow
    if (idoc) {
      idoc.location.href = href
    } else {
      iframe.src = href
    }
    window.setTimeout(() => iframe.remove(), 3000)
  } catch {
    /* fall through */
  }

  // 2) Temporary anchor with the scheme written via setAttribute (string, not URL API)
  try {
    const a = document.createElement('a')
    a.setAttribute('href', href)
    a.rel = 'noopener noreferrer'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch {
    /* ignore */
  }
}

/**
 * Copy text that works on plain HTTP intranet (Clipboard API needs secure context).
 */
export async function copyText(text: string): Promise<void> {
  if (!text) throw new Error('empty text')

  const canUseClipboardApi =
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof navigator !== 'undefined' &&
    !!navigator.clipboard &&
    typeof navigator.clipboard.writeText === 'function'

  if (canUseClipboardApi) {
    await navigator.clipboard.writeText(text)
    return
  }

  // Fallback: execCommand('copy') works on HTTP LAN pages
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  ta.setSelectionRange(0, ta.value.length)
  let ok = false
  try {
    ok = document.execCommand('copy')
  } finally {
    ta.remove()
  }
  if (!ok) throw new Error('clipboard unavailable')
}

export function filterPlayers(showAll: boolean): ExternalPlayer[] {
  if (showAll) return EXTERNAL_PLAYERS
  const platform = getPlatform()
  if (platform === 'Unknown') return EXTERNAL_PLAYERS
  return EXTERNAL_PLAYERS.filter((p) => p.platforms.includes(platform))
}

/**
 * Chrome Android requires intent://host/path#Intent;scheme=http;... form.
 * OpenList-style intent:http://host/path#Intent;... is often ignored after async clicks.
 */
export function normalizeAndroidIntent(href: string): string {
  const m = href.match(/^intent:(https?):\/\/([^#]+)(#Intent;[\s\S]*)$/i)
  if (!m) return href
  const httpScheme = m[1].toLowerCase()
  const hostAndPath = m[2]
  let intentPart = m[3]
  if (!/;\s*scheme=/i.test(intentPart) && !intentPart.includes('scheme=')) {
    intentPart = intentPart.replace(/#Intent;/, `#Intent;scheme=${httpScheme};`)
  }
  if (!/;\s*type=/i.test(intentPart) && !intentPart.includes('type=')) {
    intentPart = intentPart.replace(/#Intent;/, '#Intent;type=video/*;')
  }
  return `intent://${hostAndPath}${intentPart}`
}

export function buildPlayerHref(
  player: ExternalPlayer,
  absUrl: string,
  name: string,
): string {
  const raw = convertURL(player.scheme, {
    d_url: absUrl,
    raw_url: absUrl,
    name: name || 'video',
  })
  if (raw.startsWith('intent:')) {
    return normalizeAndroidIntent(raw)
  }
  return raw
}

/** True when browser enforces user-gesture for custom schemes (mobile). */
export function isMobileBrowser(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
    navigator.userAgent,
  )
}

export function playerIconSrc(icon: string): string {
  return `/players/${icon}.webp`
}

export function loadShowAllPlayers(): boolean {
  try {
    return localStorage.getItem(SHOW_ALL_KEY) === 'true'
  } catch {
    return false
  }
}

export function saveShowAllPlayers(value: boolean): void {
  try {
    localStorage.setItem(SHOW_ALL_KEY, value ? 'true' : 'false')
  } catch {
    /* ignore */
  }
}
