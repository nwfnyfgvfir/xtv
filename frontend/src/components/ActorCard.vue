<script setup lang="ts">
import type { Actor } from '@/api/types'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { favoriteActor, unfavoriteActor } from '@/api/media'
import { getErrorMessage } from '@/utils/errors'
import { rememberListAnchor } from '@/utils/listScrollAnchor'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = defineProps<{ actor: Actor }>()
const emit = defineEmits<{ refreshed: [Actor] }>()
const router = useRouter()
const imgFailed = ref(false)
const favLoading = ref(false)
const favorited = ref(Boolean(props.actor.favorited))

watch(
  () => props.actor.favorited,
  (v) => {
    favorited.value = Boolean(v)
  },
)
watch(
  () => props.actor.image_url,
  () => {
    imgFailed.value = false
  },
)

function open() {
  rememberListAnchor('actor', props.actor.id)
  router.push(`/actors/${props.actor.id}`)
}

function onImgError() {
  imgFailed.value = true
}

async function toggleFav(e: Event) {
  e.stopPropagation()
  favLoading.value = true
  try {
    const res = favorited.value
      ? await unfavoriteActor(props.actor.id)
      : await favoriteActor(props.actor.id)
    favorited.value = Boolean(res.favorited)
    emit('refreshed', res)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '收藏操作失败'))
  } finally {
    favLoading.value = false
  }
}
</script>

<template>
  <article
    class="actor-card"
    :data-actor-id="actor.id"
    role="button"
    tabindex="0"
    @click="open"
    @keyup.enter="open"
  >
    <div class="portrait">
      <img
        v-if="actor.image_url && !imgFailed"
        :src="actor.image_url"
        :alt="actor.name"
        width="200"
        height="200"
        loading="lazy"
        decoding="async"
        @error="onImgError"
      />
      <div v-else class="mono" :style="monogramStyle(actor.name)">
        {{ monogramChar({ title: actor.name }) }}
      </div>
      <button
        class="fav"
        type="button"
        :class="{ on: favorited, loading: favLoading }"
        :disabled="favLoading"
        :aria-label="favorited ? '取消收藏' : '收藏'"
        :aria-pressed="favorited"
        @click="toggleFav"
      >
        <span v-if="favLoading" class="fav-spin" aria-hidden="true" />
        <svg
          v-else
          class="fav-icon"
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
        >
          <path
            v-if="favorited"
            fill="currentColor"
            d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
          />
          <path
            v-else
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            d="M12.1 8.64l-.1.1-.11-.11C10.14 6.6 7.1 6.48 5.4 8.2c-1.7 1.72-1.6 4.46.2 6.06L12 20.5l6.4-6.24c1.8-1.6 1.9-4.34.2-6.06-1.7-1.72-4.74-1.6-6.5.44z"
          />
        </svg>
      </button>
    </div>
    <div class="info">
      <div class="name">{{ actor.name }}</div>
      <div class="muted count">{{ actor.media_count ?? 0 }} 部作品</div>
    </div>
  </article>
</template>

<style scoped>
.actor-card {
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  color: inherit;
  box-shadow: var(--shadow-card);
  transition: border-color 0.18s ease, transform 0.18s ease;
}
.actor-card:hover,
.actor-card:focus-visible {
  border-color: var(--accent);
  outline: none;
  transform: translateY(-2px);
}
.portrait {
  position: relative;
}
.portrait img {
  width: 100%;
  height: auto; /* override HTML height presentational hint so aspect-ratio works */
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
  background: var(--bg-elevated);
}
.mono {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 42px;
  color: var(--accent);
  background: var(--bg-elevated);
}
.fav {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  border: 1px solid rgba(255, 255, 255, 0.12);
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: 999px;
  background: rgba(8, 10, 14, 0.58);
  backdrop-filter: blur(6px);
  color: var(--text);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition:
    transform 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}
.fav:hover:not(:disabled) {
  transform: scale(1.08);
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  box-shadow: 0 0 14px var(--accent-glow);
}
.fav.on {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: color-mix(in srgb, var(--accent) 18%, rgba(8, 10, 14, 0.65));
  box-shadow: 0 0 12px var(--accent-glow);
}
.fav:disabled {
  opacity: 0.75;
  cursor: wait;
}
.fav-icon {
  display: block;
}
.fav-spin {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--accent) 35%, transparent);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: fav-rotate 0.7s linear infinite;
}
@keyframes fav-rotate {
  to {
    transform: rotate(360deg);
  }
}
.info {
  padding: 10px;
}
.name {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.count {
  font-size: 12px;
  margin-top: 2px;
}
@media (max-width: 640px) {
  .fav {
    width: 32px;
    height: 32px;
    min-width: 32px;
    top: 6px;
    left: 6px;
  }
  .fav-icon {
    width: 15px;
    height: 15px;
  }
}
</style>
