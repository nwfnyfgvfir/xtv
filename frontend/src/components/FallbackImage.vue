<script setup lang="ts">
import { useCoverImage } from '@/composables/useCoverImage'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  urls: (string | null | undefined)[]
  alt: string
  loading?: 'lazy' | 'eager'
}>(), { loading: 'lazy' })
const { src, showImage, onError } = useCoverImage(() => props.urls)
</script>

<template>
  <img v-if="showImage" v-bind="$attrs" :src="src" :alt="alt" :loading="loading" decoding="async" @error="onError" />
  <slot v-else />
</template>
