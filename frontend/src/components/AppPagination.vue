<script setup lang="ts">
import { computed } from 'vue'
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

function onChange(p: number) {
  if (p === props.page) return
  emit('update:page', p)
}
</script>

<template>
  <div v-if="visible" class="pager">
    <el-pagination
      background
      layout="total, prev, pager, next, jumper"
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
}
</style>
