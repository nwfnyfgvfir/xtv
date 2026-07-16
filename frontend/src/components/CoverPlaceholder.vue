<script setup lang="ts">
import { computed } from 'vue'
import { monogramChar, monogramStyle } from '@/utils/monogram'

const props = withDefaults(
  defineProps<{
    number?: string | null
    title?: string | null
    filename?: string | null
    size?: 'sm' | 'lg'
  }>(),
  { size: 'sm' },
)

const glyph = computed(() =>
  monogramChar({ number: props.number, title: props.title, filename: props.filename }),
)
const seed = computed(() => props.number || props.title || props.filename || glyph.value)
const style = computed(() => monogramStyle(seed.value))
const caption = computed(() => props.number || props.title || '')
</script>

<template>
  <div class="cover-placeholder" :class="size" :style="style" aria-hidden="true">
    <span class="glyph">{{ glyph }}</span>
    <span v-if="caption && size === 'lg'" class="caption">{{ caption }}</span>
  </div>
</template>

<style scoped>
.cover-placeholder {
  width: 100%;
  aspect-ratio: 3 / 4;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px;
  text-align: center;
  background:
    radial-gradient(ellipse at 30% 20%, hsla(var(--mono-hue), 55%, 42%, 0.35), transparent 55%),
    linear-gradient(155deg, #1a1f2b 0%, #0d1018 55%, #121018 100%);
  border: 1px solid rgba(232, 168, 56, 0.12);
  color: var(--text);
  position: relative;
  overflow: hidden;
}
.cover-placeholder::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 40%, rgba(0, 0, 0, 0.35));
  pointer-events: none;
}
.glyph {
  position: relative;
  z-index: 1;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(2.4rem, 8vw, 3.2rem);
  line-height: 1;
  letter-spacing: 0.04em;
  color: hsla(var(--mono-hue), 70%, 72%, 0.95);
  text-shadow: 0 0 28px hsla(var(--mono-hue), 80%, 50%, 0.35);
}
.sm .glyph {
  font-size: clamp(2rem, 6vw, 2.6rem);
}
.lg {
  min-height: 320px;
  border-radius: 14px;
}
.caption {
  position: relative;
  z-index: 1;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  max-width: 90%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* Card (sm) only — keep detail (lg) portrait on mobile */
@media (max-width: 640px) {
  .cover-placeholder.sm {
    aspect-ratio: 1;
  }
}
</style>
