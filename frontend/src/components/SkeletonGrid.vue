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
/* Media cards have no card chrome — the skeleton must match that. */
.skeleton-card {
  background: transparent;
}
.skeleton-poster {
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--border-subtle);
}
.skeleton-line {
  margin-left: 2px;
  margin-right: 2px;
}
.skeleton-line:first-of-type {
  margin-top: var(--space-3);
}
.skeleton-grid {
  gap: var(--space-6) var(--space-4);
}

.skeleton-grid.actor {
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
}
.skeleton-grid.actor .skeleton-poster {
  aspect-ratio: 1;
}
@media (max-width: 640px) {
  .skeleton-grid {
    gap: var(--space-4) var(--space-2);
  }
  .skeleton-grid.actor {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 380px) {
  .skeleton-grid.actor {
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3) 6px;
  }
}
</style>
