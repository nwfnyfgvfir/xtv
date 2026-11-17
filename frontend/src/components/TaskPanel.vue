<script setup lang="ts">
import TaskProgress from './TaskProgress.vue'
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getErrorMessage } from '@/utils/errors'
import { isActiveTask, useTasks } from '@/composables/useTasks'
const { tasks, activeTasks, panelOpen, connectionError, refreshTasks, busy, removeRecord } =
  useTasks()
const history = computed(() => tasks.value.filter((task) => !isActiveTask(task)))
async function clearHistory() {
  try {
    await ElMessageBox.confirm(
      '清空后将无法继续这些历史任务；影片和磁盘文件不受影响。',
      '清空任务历史',
      { confirmButtonText: '清空历史', cancelButtonText: '保留', type: 'warning' },
    )
    await removeRecord()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}
</script>
<template>
  <el-drawer v-model="panelOpen" title="消息" size="min(480px, 100vw)" append-to-body>
    <div class="task-intro">
      <p>执行中 {{ activeTasks.length }} · 最近任务 {{ tasks.length }}</p>
      <span>任务进度保存在服务端，刷新或关闭网页后仍可查看。</span>
    </div>
    <p v-if="connectionError" role="status" class="task-connection">
      暂时无法连接，正在自动恢复进度。<el-button text @click="refreshTasks">立即重连</el-button>
    </p>
    <div v-if="tasks.length" class="task-list">
      <TaskProgress v-for="task in activeTasks" :key="task.job_id" :task="task" />
      <div v-if="history.length" class="task-history-heading">
        <h3 class="task-history-title">历史记录</h3>
        <el-button text size="small" :disabled="!!busy" @click="clearHistory">清空历史</el-button>
      </div>
      <TaskProgress v-for="task in history" :key="task.job_id" :task="task" history />
    </div>
    <p v-else class="task-empty">暂无后台任务</p>
  </el-drawer>
</template>
<style scoped>
.task-intro {
  margin-bottom: 22px;
}
.task-intro p {
  font-size: 13px;
  margin: 0 0 8px;
}
.task-intro span,
.task-connection,
.task-empty {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
}
.task-list {
  display: grid;
  gap: 12px;
}
.task-empty {
  padding: 60px 0;
  text-align: center;
}
.task-history-title {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
}
.task-history-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
}
</style>
