<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { Library } from '@/api/types'
import { updateLibrary } from '@/api/media'
import { getErrorMessage } from '@/utils/errors'

const props = defineProps<{ modelValue: boolean; library: Library | null }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const busy = ref(false)
const policy = ref({
  auto_scan_enabled: true,
})
watch(
  () => props.modelValue,
  (open) => {
    if (!open || !props.library) return
    const lib = props.library
    policy.value = {
      auto_scan_enabled: lib.auto_scan_enabled,
    }
  },
)
async function save() {
  if (!props.library) return
  busy.value = true
  try {
    await updateLibrary(props.library.id, policy.value)
    emit('saved')
    ElMessage.success('扫描设置已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="扫描设置" width="min(720px, 94vw)">
    <p class="tool-intro">{{ library?.name }} · {{ library?.path }}</p>
    <p v-if="library?.watch_error" class="tool-hint" role="alert">{{ library.watch_error }}</p>
    <el-form label-position="top">
      <el-form-item label="自动扫描">
        <el-switch v-model="policy.auto_scan_enabled" aria-label="启用自动扫描" />
        <span class="tool-hint">关闭后仅手动扫描；与自动刮削分别控制。</span>
      </el-form-item>
      <p class="tool-hint">
        只扫描媒体库根目录中的文件，不进入任何子目录。下载完成的文件移入根目录后直接入库。
      </p>
      <p class="tool-hint">
        自动扫描通过文件事件增量处理变化路径，不定时遍历媒体库。首次入库、服务停机期间的变化或事件遗漏，可手动扫描。监听不可用时会提示，可检查后重新保存设置以重试。
      </p>
      <el-button type="primary" :loading="busy" @click="save">保存扫描策略</el-button>
    </el-form>
  </el-dialog>
</template>

<style scoped>
.tool-intro {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
  margin: 0 0 20px;
}
.tool-hint {
  display: block;
  font-size: 11px;
  line-height: 1.8;
  color: var(--muted);
  margin: 8px 0 18px;
}
@media (max-width: 640px) {
  .el-button {
    min-height: 44px;
  }
}
</style>
