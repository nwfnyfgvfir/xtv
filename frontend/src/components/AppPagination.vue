<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { DEFAULT_PAGE_SIZE } from '@/utils/pageQuery'

const props = withDefaults(
  defineProps<{
    total: number
    page: number
    pageSize?: number
  }>(),
  { pageSize: DEFAULT_PAGE_SIZE },
)

const emit = defineEmits<{
  'update:page': [page: number]
}>()

const visible = computed(() => props.total > props.pageSize)
const isNarrow = ref(false)
let mql: MediaQueryList | null = null

function syncNarrow() {
  isNarrow.value = Boolean(mql?.matches)
}

const layout = computed(() =>
  isNarrow.value
    ? 'total, prev, next, jumper'
    : 'total, prev, pager, next, jumper',
)

const pagerCount = computed(() => (isNarrow.value ? 3 : 7))

function onChange(p: number) {
  if (p === props.page) return
  emit('update:page', p)
}

onMounted(() => {
  if (typeof window === 'undefined' || !window.matchMedia) return
  mql = window.matchMedia('(max-width: 640px)')
  syncNarrow()
  mql.addEventListener('change', syncNarrow)
})

onBeforeUnmount(() => {
  mql?.removeEventListener('change', syncNarrow)
  mql = null
})
</script>

<template>
  <div v-if="visible" class="pager">
    <el-pagination
      background
      :layout="layout"
      :pager-count="pagerCount"
      :total="total"
      :page-size="pageSize"
      :current-page="page"
      @current-change="onChange"
    />
  </div>
</template>

<style scoped>
.pager {
  margin-top: 22px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  width: 100%;
  max-width: 100%;
  padding: 0 4px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.pager :deep(.el-pagination) {
  flex-wrap: wrap;
  justify-content: center;
  row-gap: 8px;
  max-width: 100%;
}

.pager :deep(.el-pagination__jump) {
  margin-left: 4px;
}

.pager :deep(.el-pagination__editor.el-input) {
  width: 48px;
}

@media (max-width: 640px) {
  .pager {
    margin-top: 16px;
  }

  .pager :deep(.el-pagination) {
    font-size: 13px;
  }

  .pager :deep(.el-pagination__total) {
    font-size: 12px;
  }
}
</style>
