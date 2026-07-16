<script setup lang="ts">
withDefaults(
  defineProps<{
    count?: number
    /** media = 3:4 poster grid; actor = square portrait grid */
    variant?: 'media' | 'actor'
  }>(),
  { count: 12, variant: 'media' },
)
</script>

<template>
  <div class="skeleton-grid" :class="variant" aria-hidden="true">
    <div v-for="n in count" :key="n" class="skeleton-card">
      <div class="skeleton-poster" />
      <div class="skeleton-line" />
      <div class="skeleton-line short" />
    </div>
  </div>
</template>

<style scoped>
.skeleton-grid.actor {
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
}
.skeleton-grid.actor .skeleton-poster {
  aspect-ratio: 1;
}
@media (max-width: 640px) {
  .skeleton-grid.actor {
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  }
}
@media (max-width: 380px) {
  .skeleton-grid.actor {
    grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
  }
}
</style>
