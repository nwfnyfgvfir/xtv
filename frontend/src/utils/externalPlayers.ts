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

/** Base origin for local /api/stream URLs (Vite proxy is not usable by external apps). */
export function streamBaseOrigin(): string {
  if (typeof window === 'undefined') return ''
  const { origin, port } = window.location
  if (import.meta.env.DEV && (port === '5173' || origin.includes(':5173'))) {
    return 'http://127.0.0.1:8000'
  }
  return origin
}

export function toAbsolutePlayUrl(play: PlayInfo): string {
  const url = (play.play_url || '').trim()
  if (!url) throw new Error('empty play_url')
  if (play.kind === 'local' || url.startsWith('/')) {
    return new URL(url, streamBaseOrigin() || window.location.origin).href
  }
  return url
}

export function filterPlayers(showAll: boolean): ExternalPlayer[] {
  if (showAll) return EXTERNAL_PLAYERS
  const platform = getPlatform()
  if (platform === 'Unknown') return EXTERNAL_PLAYERS
  return EXTERNAL_PLAYERS.filter((p) => p.platforms.includes(platform))
}

export function buildPlayerHref(
  player: ExternalPlayer,
  absUrl: string,
  name: string,
): string {
  return convertURL(player.scheme, {
    d_url: absUrl,
    raw_url: absUrl,
    name: name || 'video',
  })
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
