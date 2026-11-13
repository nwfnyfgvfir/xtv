<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })

const paths: Record<string, string[]> = {
  grid: ['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
  film: ['M5 3h14v18H5z M5 8h14 M5 16h14 M9 3v5 M15 3v5 M9 16v5 M15 16v5'],
  users: [
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M16 3a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.87',
    'M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  ],
  heart: [
    'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z',
  ],
  search: ['M21 21l-4.5-4.5', 'M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0'],
  settings: [
    'M4 7h9 M17 7h3 M4 17h3 M11 17h9',
    'M17 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M11 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
  ],
  sun: [
    'M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1.5 1.5 M17.5 17.5 19 19 M5 19l1.5-1.5 M17.5 6.5 19 5',
    'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  ],
  moon: ['M21 12.8A9 9 0 0 1 11.2 3 9 9 0 1 0 21 12.8z'],
  logout: ['M9 5H4v14h5 M9 12h12 M17 8l4 4-4 4'],
  back: ['M19 12H5 M11 6l-6 6 6 6'],
  chevron: ['M9 5l7 7-7 7'],
  down: ['M6 9l6 6 6-6'],
  play: ['M8 4l12 8-12 8z'],
  plus: ['M12 5v14 M5 12h14'],
  folder: ['M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
  refresh: ['M20 7v5h-5 M4 17v-5h5 M6.1 6.1A8 8 0 0 1 20 12 M4 12a8 8 0 0 0 13.9 5.9'],
  check: ['M5 12l4 4L19 6'],
  server: ['M3 3h18v7H3z M3 14h18v7H3z M7 6.5h.01 M7 17.5h.01'],
  translate: ['M3 5h12 M9 2v3 M5 5c0 5 4 9 8 11 M13 5c0 5-4 9-8 11 M13 21l4-10 4 10 M14.2 18h5.6'],
  image: ['M3 3h18v18H3z M3 16l5-5 5 5 3-3 5 5', 'M17 7a1 1 0 1 1-2 0 1 1 0 0 1 2 0'],
  shield: ['M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6'],
  dots: ['M5 12h.01 M12 12h.01 M19 12h.01'],
  star: ['M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z'],
  clock: ['M12 7v5l3 2', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'],
  external: ['M14 3h7v7 M21 3l-9 9 M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5'],
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="app-icon"
  >
    <path v-for="(path, index) in paths[name] || paths.film" :key="index" :d="path" />
  </svg>
</template>

<style scoped>
.app-icon {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
}
</style>
