<script setup lang="ts">
import TaskProgress from './TaskProgress.vue'
import { useTasks } from '@/composables/useTasks'
const { tasks, activeTasks, panelOpen, connectionError, refreshTasks } = useTasks()
</script>
<template>
  <el-drawer v-model="panelOpen" title="后台任务" size="min(480px, 100vw)" append-to-body>
    <div class="task-intro">
      <p>执行中 {{ activeTasks.length }} · 最近任务 {{ tasks.length }}</p>
      <span>任务进度保存在服务端，刷新或关闭网页后仍可查看。</span>
    </div>
    <p v-if="connectionError" role="status" class="task-connection">
      暂时无法连接，正在自动恢复进度。<el-button text @click="refreshTasks">立即重连</el-button>
    </p>
    <div v-if="tasks.length" class="task-list">
      <TaskProgress v-for="task in tasks" :key="task.job_id" :task="task" />
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
</style>
