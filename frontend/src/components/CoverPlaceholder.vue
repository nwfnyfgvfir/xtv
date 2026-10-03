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
    <span v-if="caption && size === 'lg'" class="caption num">{{ caption }}</span>
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
  gap: var(--space-3);
  padding: var(--space-3);
  text-align: center;
  /* Warm dark base so a missing poster still feels like part of the library. */
  background:
    radial-gradient(ellipse at 32% 18%, hsla(var(--mono-hue), 48%, 40%, 0.4), transparent 58%),
    linear-gradient(
      158deg,
      oklch(23% 0.016 72) 0%,
      oklch(15% 0.012 75) 58%,
      oklch(18.5% 0.014 68) 100%
    );
  border: 1px solid var(--border-subtle);
  color: var(--text);
  position: relative;
  overflow: hidden;
}
.cover-placeholder::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 46%, oklch(10% 0.01 75 / 0.4));
  pointer-events: none;
}
.glyph {
  position: relative;
  z-index: 1;
  font-family: var(--font-serif);
  font-weight: 500;
  font-size: clamp(2.4rem, 8vw, 3.2rem);
  line-height: 1;
  letter-spacing: var(--tracking-tight);
  color: hsla(var(--mono-hue), 62%, 78%, 0.95);
  text-shadow: 0 2px 22px hsla(var(--mono-hue), 70%, 40%, 0.4);
}
.sm .glyph {
  font-size: clamp(2rem, 6vw, 2.6rem);
}
.lg {
  min-height: 320px;
  border-radius: var(--radius-md);
}
.caption {
  position: relative;
  z-index: 1;
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-wider);
  text-transform: uppercase;
  color: var(--muted);
  max-width: 90%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
