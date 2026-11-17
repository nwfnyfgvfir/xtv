import { computed, ref, watch } from 'vue'

export function useCoverImage(getCandidates: () => (string | null | undefined)[]) {
  const candidates = computed(() =>
    [...new Set(getCandidates().filter((url): url is string => Boolean(url?.trim())))],
  )
  const attempt = ref(0)
  const src = computed(() => candidates.value[attempt.value] || '')
  const showImage = computed(() => Boolean(src.value))
  const failed = computed(() => candidates.value.length > 0 && !showImage.value)
  function reset() {
    attempt.value = 0
  }
  function onError() {
    attempt.value += 1
  }
  watch(candidates, reset, { flush: 'sync' })
  return { src, showImage, failed, onError, reset }
}
