<script setup lang="ts">
withDefaults(defineProps<{ count?: number }>(), { count: 12 })
</script>

<template>
  <div class="skeleton-grid" aria-hidden="true">
    <div v-for="n in count" :key="n" class="skeleton-card">
      <div class="skeleton-poster" />
      <div class="skeleton-line" />
      <div class="skeleton-line short" />
    </div>
  </div>
</template>
