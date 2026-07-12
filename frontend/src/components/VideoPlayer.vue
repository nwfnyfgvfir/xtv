<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Artplayer from 'artplayer'
import { getProgress, putProgress } from '@/api/media'

const props = defineProps<{ mediaId: number; src: string; autoplay?: boolean }>()
const containerRef = ref<HTMLDivElement | null>(null)
let player: Artplayer | null = null
let timer: number | undefined

const DBLCLICK_MS = 300
const DRAG_THRESHOLD_PX = 8
const SEEK_RATIO = 0.5

type DragState = {
  pointerId: number
  startX: number
  startY: number
  startTime: number
  width: number
  dragging: boolean
  moved: boolean
}

let drag: DragState | null = null
let lastTapAt = 0
let lastTapX = 0
let suppressClickUntil = 0
let singleTapTimer: number | undefined
const gestureCleanups: Array<() => void> = []

function clearSingleTapTimer() {
  if (singleTapTimer != null) {
    window.clearTimeout(singleTapTimer)
    singleTapTimer = undefined
  }
}

function toggleControls() {
  if (!player) return
  try {
    player.controls.toggle()
  } catch {
    try {
      player.controls.show = !player.controls.show
    } catch {
      /* ignore */
    }
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
  if (!player) return
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
  if (!player) return
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
    // Only primary pointer
    if (drag) return
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
        toggleControls()
      }, DBLCLICK_MS)
    }
  }

  const onClick = (e: MouseEvent) => {
    // Layer click is also fired by Artplayer's component proxy; ignore after drag
    // and ignore single clicks (double handled in pointerup).
    if (Date.now() < suppressClickUntil) {
      e.preventDefault()
      e.stopPropagation()
      return
    }
    // Prevent Artplayer from treating residual events oddly; we own gestures.
    e.preventDefault()
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
    mutex: true,
    backdrop: true,
    playsInline: true,
    lang: 'zh-cn',
    // Full-area gesture layer sits above video (z40) but below controls (z60).
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
          bindGestureLayer(el)
        },
        beforeUnmount() {
          clearGestureCleanups()
        },
      },
    ],
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
    <p class="hint muted">滑动快进/快退 · 双击左 -10s · 双击右 +10s · 双击中切换 · 单击显示/隐藏控制栏</p>
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
}
</style>
