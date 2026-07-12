<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getProgress, putProgress } from '@/api/media'

const props = defineProps<{ mediaId: number; src: string }>()
const videoRef = ref<HTMLVideoElement | null>(null)
let timer: number | undefined

async function restore() {
  try {
    const p = await getProgress(props.mediaId)
    if (videoRef.value && p.position_sec > 5) {
      videoRef.value.currentTime = p.position_sec
    }
  } catch {
    /* ignore */
  }
}

function save() {
  const v = videoRef.value
  if (!v || !Number.isFinite(v.currentTime)) return
  void putProgress(props.mediaId, {
    position_sec: v.currentTime,
    duration_sec: Number.isFinite(v.duration) ? v.duration : undefined,
  })
}

onMounted(() => {
  void restore()
  timer = window.setInterval(save, 5000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  save()
})

watch(
  () => props.src,
  () => {
    void restore()
  },
)
</script>

<template>
  <video ref="videoRef" class="player" :src="src" controls playsinline @pause="save" @ended="save" />
</template>

<style scoped>
.player {
  width: 100%;
  max-height: 70vh;
  background: #000;
  border-radius: 12px;
}
</style>
