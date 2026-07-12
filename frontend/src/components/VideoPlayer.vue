<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Artplayer from 'artplayer'
import { getProgress, putProgress } from '@/api/media'

const props = defineProps<{ mediaId: number; src: string; autoplay?: boolean }>()
const containerRef = ref<HTMLDivElement | null>(null)
let player: Artplayer | null = null
let timer: number | undefined

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

function destroy() {
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
    layers: [
      {
        name: 'seek-left',
        html: '',
        style: {
          position: 'absolute',
          left: '0',
          top: '0',
          width: '40%',
          height: '100%',
          zIndex: '10',
        },
        click: undefined as unknown as () => void,
      },
    ],
  })

  // Double-click left/right seek zones
  const el = containerRef.value
  const onDbl = (e: MouseEvent) => {
    if (!player) return
    const rect = el.getBoundingClientRect()
    const x = e.clientX - rect.left
    const ratio = x / rect.width
    if (ratio < 0.4) {
      player.currentTime = Math.max(0, player.currentTime - 10)
    } else if (ratio > 0.6) {
      player.currentTime = Math.min(player.duration || 1e9, player.currentTime + 10)
    } else {
      player.toggle()
    }
  }
  el.addEventListener('dblclick', onDbl)

  player.on('ready', () => {
    void restore()
    if (props.autoplay) {
      void player?.play().catch(() => undefined)
    }
  })
  player.on('pause', save)
  player.on('video:ended', save)

  timer = window.setInterval(save, 5000)
  ;(player as unknown as { _dbl?: (e: MouseEvent) => void })._dbl = onDbl
}

onMounted(create)
onBeforeUnmount(() => {
  if (player && containerRef.value) {
    const dbl = (player as unknown as { _dbl?: (e: MouseEvent) => void })._dbl
    if (dbl) containerRef.value.removeEventListener('dblclick', dbl)
  }
  destroy()
})

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
