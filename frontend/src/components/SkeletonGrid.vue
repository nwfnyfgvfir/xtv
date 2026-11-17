<script setup lang="ts">
withDefaults(
  defineProps<{
    count?: number
    /** media = landscape poster grid; actor = square portrait grid */
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
.skeleton-card {
  background: transparent;
}
.skeleton-poster {
  border-radius: 10px;
}
.skeleton-line {
  margin: 12px 1px 0;
}
.skeleton-line.short {
  margin-top: 8px;
}
.skeleton-grid {
  gap: 28px 20px;
}
.skeleton-grid.media {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--media-card-min-width)), 1fr));
}
.skeleton-grid.actor {
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
}
.skeleton-grid.actor .skeleton-poster {
  aspect-ratio: 1;
}
@media (max-width: 640px) {
  .skeleton-grid.media {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px 14px;
  }
  .skeleton-grid.actor {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
