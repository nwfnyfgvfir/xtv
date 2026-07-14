<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Artplayer from 'artplayer'
import { getProgress, putProgress } from '@/api/media'

const props = defineProps<{ mediaId: number; src: string; autoplay?: boolean }>()
const containerRef = ref<HTMLDivElement | null>(null)
let player: Artplayer | null = null
let timer: number | undefined
let unlockFabEl: HTMLElement | null = null
let gestureLayerEl: HTMLElement | null = null

const DBLCLICK_MS = 300
const DRAG_THRESHOLD_PX = 8
const SEEK_RATIO = 0.5
// Artplayer default is 3000ms; too short after single-tap show.
const CONTROL_HIDE_MS = 6000

type DragState = {
  pointerId: number
  startX: number
  startY: number
  startTime: number
  width: number
  dragging: boolean
  moved: boolean
}

type MutableLockPlayer = Artplayer & { isLock: boolean }

let drag: DragState | null = null
let lastTapAt = 0
let lastTapX = 0
let suppressClickUntil = 0
let singleTapTimer: number | undefined
// Snapshot at pointerdown so deferred single-tap is not flipped by desktop-path
// mousemove (tablets often synthesize mousemove → Artplayer show=true before toggle).
let controlsVisibleOnPointerDown = false
const gestureCleanups: Array<() => void> = []

function isPlayerLocked(art: Artplayer | null): boolean {
  if (!art) return false
  if (art.isLock) return true
  try {
    return art.template.$player.classList.contains('art-lock')
  } catch {
    return false
  }
}

function setPlayerLock(art: Artplayer, locked: boolean) {
  const mutable = art as MutableLockPlayer
  try {
    const root = art.template.$player
    if (locked) root.classList.add('art-lock')
    else root.classList.remove('art-lock')
  } catch {
    /* ignore */
  }
  mutable.isLock = locked
  art.emit('lock', locked)
}

function syncUnlockFab(locked: boolean) {
  if (!unlockFabEl) return
  // Floating unlock for all platforms (Artplayer built-in lock layer is mobile-only
  // and sits under our full-area gesture layer, so it is not usable).
  unlockFabEl.style.display = locked ? 'flex' : 'none'
  unlockFabEl.style.pointerEvents = locked ? 'auto' : 'none'
}

function syncGestureLayer(_locked: boolean) {
  // Keep the full-area gesture layer capturing while locked. Unlock FAB sits at a
  // higher z-index and does not need the layer disabled; pointer-events:none lets
  // clicks fall through to $video, where Artplayer's desktop click toggles play
  // without checking isLock.
  if (gestureLayerEl) {
    gestureLayerEl.style.pointerEvents = 'auto'
  }
}

function clearSingleTapTimer() {
  if (singleTapTimer != null) {
    window.clearTimeout(singleTapTimer)
    singleTapTimer = undefined
  }
}

function applySingleTapControls() {
  if (!player || isPlayerLocked(player)) return
  // Use visibility at pointerdown, not live state — on desktop-classified tablets a
  // compatibility mousemove may already have forced show=true before this runs.
  const next = !controlsVisibleOnPointerDown
  try {
    player.controls.show = next
  } catch {
    /* ignore */
  }
}

function clearGestureCleanups() {
  clearSingleTapTimer()
  while (gestureCleanups.length) {
    const fn = gestureCleanups.pop()
    try {
      fn?.()
    } catch {
      /* ignore */
    }
  }
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const s = Math.floor(sec % 60)
  const m = Math.floor(sec / 60) % 60
  const h = Math.floor(sec / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

async function restore() {
  if (!player) return
  try {
    const p = await getProgress(props.mediaId)
    if (p.position_sec > 5) {
      player.currentTime = p.position_sec
    }
  } catch {
    /* ignore */
  }
}

function save() {
  if (!player) return
  const t = player.currentTime
  const d = player.duration
  if (!Number.isFinite(t)) return
  void putProgress(props.mediaId, {
    position_sec: t,
    duration_sec: Number.isFinite(d) ? d : undefined,
  })
}

function setPlayedBar(next: number, duration: number) {
  if (!player || !(duration > 0)) return
  const ratio = clamp(next / duration, 0, 1)
  try {
    // ArtPlayer progress UI listens to setBar; keep bar in sync during custom seek.
    player.emit('setBar', 'played', ratio)
  } catch {
    /* ignore */
  }
}

function commitSeek(next: number) {
  if (!player || isPlayerLocked(player)) return
  const duration = Number.isFinite(player.duration) ? player.duration : 0
  if (!(duration > 0)) return
  const t = clamp(next, 0, duration)
  try {
    // Prefer seek setter (drives events); fall back to currentTime.
    ;(player as Artplayer & { seek?: number }).seek = t
  } catch {
    player.currentTime = t
  }
  setPlayedBar(t, duration)
  try {
    player.notice.show = `${formatTime(t)} / ${formatTime(duration)}`
  } catch {
    /* ignore */
  }
}

function seekOrToggleByX(clientX: number, target: HTMLElement) {
  if (!player || isPlayerLocked(player)) return
  const rect = target.getBoundingClientRect()
  const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0.5
  if (ratio < 0.4) {
    commitSeek(Math.max(0, (player.currentTime || 0) - 10))
  } else if (ratio > 0.6) {
    const duration = Number.isFinite(player.duration) ? player.duration : 1e9
    commitSeek(Math.min(duration, (player.currentTime || 0) + 10))
  } else {
    player.toggle()
  }
}

function bindGestureLayer(el: HTMLElement) {
  el.style.touchAction = 'pan-y'
  el.style.userSelect = 'none'
  ;(el.style as CSSStyleDeclaration & { webkitUserSelect?: string }).webkitUserSelect = 'none'

  const onPointerDown = (e: PointerEvent) => {
    if (!player || e.button !== 0) return
    if (isPlayerLocked(player)) {
      // Swallow so clicks never reach $video (Artplayer desktop click toggles play).
      e.preventDefault()
      e.stopPropagation()
      return
    }
    // Only primary pointer
    if (drag) return
    try {
      controlsVisibleOnPointerDown = Boolean(player.controls.show)
    } catch {
      controlsVisibleOnPointerDown = false
    }
    const rect = el.getBoundingClientRect()
    drag = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startTime: player.currentTime || 0,
      width: rect.width || 1,
      dragging: false,
      moved: false,
    }
    try {
      el.setPointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  const onPointerMove = (e: PointerEvent) => {
    if (!player || !drag || e.pointerId !== drag.pointerId) return
    if (isPlayerLocked(player)) {
      e.preventDefault()
      e.stopPropagation()
      return
    }
    const dx = e.clientX - drag.startX
    const dy = e.clientY - drag.startY
    if (!drag.dragging) {
      if (Math.abs(dx) < DRAG_THRESHOLD_PX && Math.abs(dy) < DRAG_THRESHOLD_PX) return
      // Prefer horizontal swipe for seek
      if (Math.abs(dx) < Math.abs(dy)) {
        drag = null
        return
      }
      drag.dragging = true
      drag.moved = true
      lastTapAt = 0
      clearSingleTapTimer()
    }
    e.preventDefault()
    const duration = Number.isFinite(player.duration) ? player.duration : 0
    if (!(duration > 0)) return
    const delta = (dx / drag.width) * duration * SEEK_RATIO
    const next = clamp(drag.startTime + delta, 0, duration)
    // Optimistic UI only while dragging — avoid thrashing media seek on remote streams.
    setPlayedBar(next, duration)
    try {
      player.notice.show = `${formatTime(next)} / ${formatTime(duration)}`
    } catch {
      /* ignore */
    }
  }

  const endPointer = (e: PointerEvent) => {
    if (isPlayerLocked(player)) {
      e.preventDefault()
      e.stopPropagation()
      drag = null
      try {
        el.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
      lastTapAt = 0
      clearSingleTapTimer()
      return
    }
    if (!drag || e.pointerId !== drag.pointerId) return
    const wasDrag = drag.dragging
    const clientX = e.clientX
    const startTime = drag.startTime
    const width = drag.width
    const startX = drag.startX
    drag = null
    try {
      el.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
    if (wasDrag) {
      const duration = player && Number.isFinite(player.duration) ? player.duration : 0
      if (player && duration > 0) {
        const dx = clientX - startX
        const delta = (dx / width) * duration * SEEK_RATIO
        commitSeek(startTime + delta)
      }
      // Suppress the synthetic click that follows a drag.
      suppressClickUntil = Date.now() + 350
      lastTapAt = 0
      clearSingleTapTimer()
      return
    }
    // Deferred single-tap toggles controls; second tap within DBLCLICK_MS seeks/plays.
    const now = Date.now()
    if (now - lastTapAt <= DBLCLICK_MS && Math.abs(clientX - lastTapX) < 40) {
      clearSingleTapTimer()
      lastTapAt = 0
      seekOrToggleByX(clientX, el)
    } else {
      lastTapAt = now
      lastTapX = clientX
      clearSingleTapTimer()
      singleTapTimer = window.setTimeout(() => {
        singleTapTimer = undefined
        lastTapAt = 0
        applySingleTapControls()
      }, DBLCLICK_MS)
    }
  }

  const onClick = (e: MouseEvent) => {
    // Always own clicks on the gesture layer (including while locked) so they
    // never bubble/fall through to Artplayer's $video click → toggle.
    e.preventDefault()
    e.stopPropagation()
    if (isPlayerLocked(player) || Date.now() < suppressClickUntil) return
  }

  el.addEventListener('pointerdown', onPointerDown)
  el.addEventListener('pointermove', onPointerMove)
  el.addEventListener('pointerup', endPointer)
  el.addEventListener('pointercancel', endPointer)
  el.addEventListener('click', onClick)

  gestureCleanups.push(() => {
    el.removeEventListener('pointerdown', onPointerDown)
    el.removeEventListener('pointermove', onPointerMove)
    el.removeEventListener('pointerup', endPointer)
    el.removeEventListener('pointercancel', endPointer)
    el.removeEventListener('click', onClick)
  })
}

function destroy() {
  clearGestureCleanups()
  clearSingleTapTimer()
  drag = null
  lastTapAt = 0
  unlockFabEl = null
  gestureLayerEl = null
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
  save()
  if (player) {
    player.destroy()
    player = null
  }
}

function create() {
  destroy()
  if (!containerRef.value || !props.src) return

  // Prefer custom seek gestures over Artplayer's default dblclick-fullscreen.
  Artplayer.DBCLICK_FULLSCREEN = false
  Artplayer.CONTROL_HIDE_TIME = CONTROL_HIDE_MS

  player = new Artplayer({
    container: containerRef.value,
    url: props.src,
    theme: '#e8a838',
    autoplay: Boolean(props.autoplay),
    autoSize: false,
    autoMini: false,
    screenshot: false,
    setting: true,
    playbackRate: true,
    aspectRatio: true,
    fullscreen: true,
    fullscreenWeb: true,
    pip: true,
    // Mobile native fullscreen: try screen.orientation.lock when aspect mismatches.
    autoOrientation: true,
    mutex: true,
    backdrop: true,
    playsInline: true,
    // Do not use Artplayer mobile-only lock plugin: our full-area gesture layer
    // covers its side button. Unified custom lock works on phone + desktop.
    lock: false,
    lang: 'zh-cn',
    controls: [
      {
        name: 'screen-lock',
        position: 'right',
        index: 10,
        html: '锁',
        tooltip: '锁屏',
        style: {
          padding: '0 8px',
          color: '#fff',
        },
        click() {
          if (!player || isPlayerLocked(player)) return
          setPlayerLock(player, true)
          try {
            player.controls.show = false
          } catch {
            /* ignore */
          }
        },
      },
    ],
    // Full-area gesture layer sits above video but below controls.
    // Blocks Artplayer's built-in first-click toggle / dblclick fullscreen.
    layers: [
      {
        name: 'gesture',
        html: '',
        style: {
          position: 'absolute',
          inset: '0',
          width: '100%',
          height: '100%',
          zIndex: '10',
          background: 'transparent',
        },
        // Swallow Artplayer component click; single-tap toggle lives in pointerup.
        click() {
          /* intentional no-op */
        },
        mounted(el) {
          gestureLayerEl = el
          bindGestureLayer(el)
        },
        beforeUnmount() {
          clearGestureCleanups()
          gestureLayerEl = null
        },
      },
      {
        name: 'unlock-fab',
        html: '开锁',
        style: {
          position: 'absolute',
          right: '12px',
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: '80',
          display: 'none',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: '48px',
          height: '48px',
          padding: '0 14px',
          borderRadius: '999px',
          background: 'rgba(0,0,0,.6)',
          color: '#fff',
          fontSize: '14px',
          cursor: 'pointer',
          userSelect: 'none',
          WebkitUserSelect: 'none',
          touchAction: 'manipulation',
          pointerEvents: 'none',
        },
        click() {
          if (!player) return
          setPlayerLock(player, false)
        },
        mounted(el) {
          unlockFabEl = el
          // Direct listeners: more reliable than Artplayer proxy click on mobile.
          const unlock = (e: Event) => {
            e.preventDefault()
            e.stopPropagation()
            if (!player || !isPlayerLocked(player)) return
            setPlayerLock(player, false)
          }
          el.addEventListener('pointerup', unlock)
          el.addEventListener('click', unlock)
          ;(el as HTMLElement & { __unlockHandlers?: () => void }).__unlockHandlers = () => {
            el.removeEventListener('pointerup', unlock)
            el.removeEventListener('click', unlock)
          }
          syncUnlockFab(isPlayerLocked(player))
        },
        beforeUnmount(el) {
          const node = el as HTMLElement & { __unlockHandlers?: () => void }
          try {
            node.__unlockHandlers?.()
          } catch {
            /* ignore */
          }
          unlockFabEl = null
        },
      },
    ],
  })

  player.on('lock', (state: boolean) => {
    syncUnlockFab(state)
    syncGestureLayer(state)
    if (state) {
      drag = null
      clearSingleTapTimer()
      lastTapAt = 0
      try {
        player!.controls.show = false
      } catch {
        /* ignore */
      }
      try {
        player!.notice.show = '已锁屏'
      } catch {
        /* ignore */
      }
    } else {
      try {
        player!.notice.show = '已解锁'
      } catch {
        /* ignore */
      }
    }
  })

  player.on('ready', () => {
    void restore()
    if (props.autoplay) {
      void player?.play().catch(() => undefined)
    }
  })
  player.on('pause', save)
  player.on('video:ended', save)

  timer = window.setInterval(save, 5000)
}

onMounted(create)
onBeforeUnmount(destroy)

watch(
  () => props.src,
  () => create(),
)
</script>

<template>
  <div class="player-wrap">
    <div ref="containerRef" class="player" />
    <p class="hint muted">
      滑动快进/快退 · 双击左 -10s · 双击右 +10s · 双击中切换 · 单击显示/隐藏控制栏 · 「锁」锁屏 · 锁屏后点「开锁」
    </p>
  </div>
</template>

<style scoped>
.player-wrap {
  width: 100%;
}
.player {
  width: 100%;
  height: min(70vh, 520px);
  background: #000;
  border-radius: 12px;
  overflow: hidden;
}
.hint {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.45;
}
.muted {
  color: var(--muted);
}
@media (max-width: 640px) {
  .player {
    height: 52vw;
    min-height: 200px;
    border-radius: 8px;
  }
  .hint {
    font-size: 11px;
  }
  /* Slim Artplayer bar so 锁 + setting + fullscreen stay on-screen. */
  .player :deep(.art-video-player) {
    --art-control-height: 36px;
    --art-control-icon-size: 32px;
    --art-padding: 6px;
  }
}
/* Very narrow phones: drop volume control (system volume still works). */
@media (max-width: 400px) {
  .player :deep(.art-control-volume) {
    display: none;
  }
}
</style>
