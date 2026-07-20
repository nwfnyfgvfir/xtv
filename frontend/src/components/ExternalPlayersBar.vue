<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { playMedia } from '@/api/media'
import type { PlayInfo } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
import {
  type ExternalPlayer,
  buildPlayerHref,
  copyText,
  filterPlayers,
  isMobileBrowser,
  launchScheme,
  loadShowAllPlayers,
  playerIconSrc,
  saveShowAllPlayers,
  toAbsolutePlayUrl,
} from '@/utils/externalPlayers'

const props = defineProps<{
  mediaId: number
  name: string
  play?: PlayInfo | null
}>()

const emit = defineEmits<{
  'play-resolved': [info: PlayInfo]
}>()

const busy = ref(false)
const prefetching = ref(false)
const showAll = ref(loadShowAllPlayers())
const localPlay = ref<PlayInfo | null>(null)
const absUrl = ref<string | null>(null)
const mobile = isMobileBrowser()

watch(
  () => props.play,
  (v) => {
    if (v) {
      localPlay.value = v
      try {
        absUrl.value = toAbsolutePlayUrl(v)
      } catch {
        /* ignore until prefetch */
      }
    }
  },
  { immediate: true },
)

const visiblePlayers = computed(() => filterPlayers(showAll.value))

const playerHrefs = computed(() => {
  const abs = absUrl.value
  if (!abs) return new Map<string, string>()
  const name = props.name || 'video'
  const map = new Map<string, string>()
  for (const p of visiblePlayers.value) {
    map.set(p.icon, buildPlayerHref(p, abs, name))
  }
  return map
})

function toggleShowAll() {
  showAll.value = !showAll.value
  saveShowAllPlayers(showAll.value)
}

async function ensurePlayInfo(): Promise<PlayInfo> {
  if (localPlay.value) return localPlay.value
  if (props.play) {
    localPlay.value = props.play
    return props.play
  }
  const info = await playMedia(props.mediaId)
  localPlay.value = info
  emit('play-resolved', info)
  return info
}

async function resolveAbsUrl(): Promise<string> {
  if (absUrl.value) return absUrl.value
  const info = await ensurePlayInfo()
  const abs = toAbsolutePlayUrl(info)
  absUrl.value = abs
  return abs
}

/** Prefetch so mobile icon taps stay synchronous (user-gesture) real <a> navigations. */
async function prefetch() {
  if (prefetching.value) return
  if (absUrl.value) return
  prefetching.value = true
  try {
    await resolveAbsUrl()
  } catch (e: unknown) {
    // Soft fail — click will surface error
    console.warn('[ExternalPlayersBar] prefetch failed', e)
  } finally {
    prefetching.value = false
  }
}

onMounted(() => {
  void prefetch()
})

watch(
  () => props.mediaId,
  () => {
    localPlay.value = props.play ?? null
    absUrl.value = null
    if (props.play) {
      try {
        absUrl.value = toAbsolutePlayUrl(props.play)
      } catch {
        absUrl.value = null
      }
    }
    void prefetch()
  },
)

/**
 * Mobile: allow default <a href> navigation so the OS receives a real user gesture
 * (async playMedia after click is blocked by Chrome/Android).
 * Desktop: preventDefault + launchScheme to avoid Chromium mangling potplayer://http://.
 */
function onPlayerClick(e: MouseEvent, player: ExternalPlayer) {
  const href = playerHrefs.value.get(player.icon)
  if (!href || !absUrl.value) {
    e.preventDefault()
    void onLaunchFallback(player)
    return
  }
  if (mobile) {
    // Let the browser follow <a href="intent://..."> / nplayer-... / infuse://...
    ElMessage.info(`正在打开 ${player.name}…`)
    return
  }
  e.preventDefault()
  try {
    launchScheme(href)
    ElMessage.info(
      `正在打开 ${player.name}…若未响应请确认已安装；也可「复制链接」后手动打开`,
    )
  } catch (err: unknown) {
    ElMessage.error(getErrorMessage(err, '打开外部播放器失败'))
  }
}

async function onLaunchFallback(player: ExternalPlayer) {
  if (busy.value) return
  busy.value = true
  try {
    const abs = await resolveAbsUrl()
    const href = buildPlayerHref(player, abs, props.name || 'video')
    if (mobile) {
      // Last resort after async — often blocked; still try + show link
      launchScheme(href)
      ElMessage.warning(
        `若未打开 ${player.name}，请用「复制链接」在播放器中粘贴打开`,
      )
    } else {
      launchScheme(href)
      ElMessage.info(`正在打开 ${player.name}…`)
    }
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '打开外部播放器失败'))
  } finally {
    busy.value = false
  }
}

async function showUrlFallback(abs: string, title = '播放链接') {
  try {
    await ElMessageBox.alert(abs, title, {
      confirmButtonText: '关闭',
      closeOnClickModal: true,
      dangerouslyUseHTMLString: false,
    })
  } catch {
    /* dismissed */
  }
}

async function onCopy() {
  if (busy.value) return
  busy.value = true
  try {
    const abs = await resolveAbsUrl()
    try {
      await copyText(abs)
      ElMessage.success('播放链接已复制')
    } catch {
      ElMessage.warning('当前环境无法自动复制，请手动选择下方链接')
      await showUrlFallback(abs)
    }
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '获取播放链接失败'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="external-players" :class="{ busy: busy || prefetching }">
    <div class="ep-toolbar">
      <span class="ep-label">外部播放</span>
      <span v-if="prefetching && !absUrl" class="ep-status">准备地址…</span>
      <button type="button" class="ep-action" :disabled="busy" @click="onCopy">复制链接</button>
      <button
        type="button"
        class="ep-toggle"
        :aria-pressed="showAll"
        :title="showAll ? '仅显示本平台播放器' : '显示全部播放器'"
        @click="toggleShowAll"
      >
        <svg
          class="ep-arrow"
          :class="{ open: showAll }"
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
        >
          <path
            fill="currentColor"
            d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z"
          />
        </svg>
        <span class="ep-toggle-text">{{ showAll ? '收起' : '全部' }}</span>
      </button>
    </div>
    <div class="ep-icons" role="list" aria-label="外部播放器">
      <!--
        Real <a href> so mobile Chrome keeps user-gesture for intent:// / nplayer- / etc.
        href is empty until prefetch finishes; click then falls back with a tip.
      -->
      <a
        v-for="p in visiblePlayers"
        :key="p.icon"
        class="ep-icon-btn"
        role="listitem"
        :title="p.name"
        :aria-label="p.name"
        :href="playerHrefs.get(p.icon) || undefined"
        :class="{ disabled: busy || (!absUrl && prefetching) }"
        @click="onPlayerClick($event, p)"
      >
        <img :src="playerIconSrc(p.icon)" :alt="p.name" width="32" height="32" draggable="false" />
      </a>
    </div>
  </div>
</template>

<style scoped>
.external-players {
  margin: 4px 0 14px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
}
.external-players.busy {
  opacity: 0.85;
}
.ep-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 10px;
}
.ep-label {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--muted);
}
.ep-status {
  font-size: 12px;
  color: var(--muted);
}
.ep-action,
.ep-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    color 0.15s ease,
    background 0.15s ease;
}
.ep-action:hover:not(:disabled),
.ep-toggle:hover {
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
  color: var(--accent);
  background: var(--accent-soft);
}
.ep-action:disabled {
  opacity: 0.6;
  cursor: wait;
}
.ep-toggle[aria-pressed='true'] {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  color: var(--accent);
  background: var(--accent-soft);
}
.ep-arrow {
  transition: transform 0.2s ease;
  flex-shrink: 0;
}
.ep-arrow.open {
  transform: rotate(180deg);
}
.ep-icons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-start;
}
.ep-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
  -webkit-touch-callout: none;
  transition:
    transform 0.15s ease,
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease;
}
.ep-icon-btn img {
  width: 32px;
  height: 32px;
  object-fit: contain;
  border-radius: 6px;
  pointer-events: none;
}
.ep-icon-btn:hover:not(.disabled) {
  transform: translateY(-1px) scale(1.06);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  background: var(--accent-soft);
  box-shadow: 0 4px 12px color-mix(in srgb, var(--accent) 12%, transparent);
}
.ep-icon-btn.disabled {
  opacity: 0.55;
  cursor: wait;
  pointer-events: none;
}
@media (max-width: 720px) {
  .external-players {
    padding: 10px 12px;
  }
  .ep-icons {
    gap: 6px;
  }
  /* Larger tap targets on phone/tablet */
  .ep-icon-btn {
    width: 48px;
    height: 48px;
  }
  .ep-icon-btn img {
    width: 36px;
    height: 36px;
  }
}
</style>
