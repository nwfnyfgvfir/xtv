<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Artplayer from 'artplayer'
import { getProgress, putProgress } from '@/api/media'

const props = defineProps<{ mediaId: number; src: string; autoplay?: boolean }>()
const containerRef = ref<HTMLDivElement | null>(null)
let player: Artplayer | null = null
let timer: number | undefined
let clickTimer: number | undefined

const CLICK_DELAY_MS = 280

function clearClickTimer() {
  if (clickTimer !== undefined) {
    window.clearTimeout(clickTimer)
    clickTimer = undefined
  }
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

function seekOrToggleByX(clientX: number, target: HTMLElement) {
  if (!player) return
  const rect = target.getBoundingClientRect()
  const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0.5
  if (ratio < 0.4) {
    player.currentTime = Math.max(0, player.currentTime - 10)
  } else if (ratio > 0.6) {
    player.currentTime = Math.min(player.duration || 1e9, player.currentTime + 10)
  } else {
    player.toggle()
  }
}

function destroy() {
  clearClickTimer()
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
    // Capturing clicks here prevents Artplayer's built-in first-click toggle.
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
        click(_component, event) {
          if (!player) return
          const e = event as MouseEvent
          const target = event.currentTarget as HTMLElement | null
          if (!target) return

          if (clickTimer !== undefined) {
            clearClickTimer()
            seekOrToggleByX(e.clientX, target)
            return
          }

          clickTimer = window.setTimeout(() => {
            clickTimer = undefined
            player?.toggle()
          }, CLICK_DELAY_MS)
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
    <p class="hint muted">双击左侧 -10s · 双击右侧 +10s · 中间切换播放</p>
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
