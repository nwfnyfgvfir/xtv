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
  height: 100%;
  aspect-ratio: 3 / 4;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 18px;
  overflow: hidden;
  background: hsl(var(--mono-hue), 12%, 19%);
  color: #d0ddd6;
}
.cover-placeholder::before {
  content: '';
  position: absolute;
  inset: 15px;
  border: 1px solid #e1f0e214;
  border-radius: 4px;
}
.cover-placeholder::after {
  content: '';
  width: 30px;
  height: 2px;
  background: #d5eee330;
  position: absolute;
  bottom: 35px;
}
.glyph {
  position: relative;
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 400;
  opacity: 0.8;
  line-height: 1;
}
.lg .glyph {
  font-size: 76px;
}
.caption {
  max-width: 90%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: #b5c8bd;
}
.lg {
  min-height: 280px;
  border-radius: 12px;
}
</style>
