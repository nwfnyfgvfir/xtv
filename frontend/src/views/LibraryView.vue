<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MediaGrid from '@/components/MediaGrid.vue'
import {
  createLibrary,
  getScanJob,
  listLibraries,
  listMedia,
  scanLibrary,
  deleteLibrary,
} from '@/api/media'
import type { Library, MediaListItem } from '@/api/types'

const items = ref<MediaListItem[]>([])
const libraries = ref<Library[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const scanning = ref(false)

const showCreate = ref(false)
const form = ref({ name: '番号', path: 'local', type: 'mixed' })

async function load() {
  loading.value = true
  try {
    libraries.value = await listLibraries()
    const data = await listMedia({ page: page.value, page_size: 48 })
    items.value = data.items
    total.value = data.total
  } catch {
    ElMessage.error('加载失败，请确认后端已启动')
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  try {
    await createLibrary(form.value)
    showCreate.value = false
    ElMessage.success('媒体库已创建')
    await load()
  } catch {
    ElMessage.error('创建失败')
  }
}

async function onScan(lib: Library) {
  scanning.value = true
  try {
    const job = await scanLibrary(lib.id)
    ElMessage.info(`扫描已开始: ${job.job_id}`)
    await pollJob(job.job_id)
    await load()
  } catch {
    ElMessage.error('扫描失败')
  } finally {
    scanning.value = false
  }
}

async function pollJob(jobId: string) {
  for (let i = 0; i < 120; i++) {
    const job = await getScanJob(jobId)
    if (job.status === 'done' || job.status === 'error') {
      if (job.status === 'done') {
        ElMessage.success(job.message || '扫描完成')
      } else {
        ElMessage.error(job.message || '扫描出错')
      }
      return
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
}

async function onDelete(lib: Library) {
  await deleteLibrary(lib.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading || scanning">
    <div class="head">
      <div>
        <h1 class="page-title">媒体库</h1>
        <p class="muted intro">本地影片与 strm 直链，刮削封面经 MetaTube 代理展示</p>
      </div>
      <div class="actions">
        <el-button type="primary" @click="showCreate = true">添加媒体库</el-button>
      </div>
    </div>

    <div v-if="libraries.length" class="libs">
      <div v-for="lib in libraries" :key="lib.id" class="lib-row">
        <div>
          <strong>{{ lib.name }}</strong>
          <span class="muted"> · {{ lib.path }} · {{ lib.type }}</span>
        </div>
        <div class="lib-actions">
          <el-button size="small" type="warning" :loading="scanning" @click="onScan(lib)">扫描</el-button>
          <el-button size="small" type="danger" plain @click="onDelete(lib)">删除</el-button>
        </div>
      </div>
    </div>
    <p v-else class="muted hint">
      尚未添加媒体库。路径可填相对 MEDIA_ROOT 的路径，例如 <code>local</code> 或 <code>strm</code>。
    </p>

    <MediaGrid :items="items" />
    <div v-if="total > 48" class="pager">
      <el-pagination
        background
        layout="prev, pager, next"
        :total="total"
        :page-size="48"
        v-model:current-page="page"
        @current-change="load"
      />
    </div>

    <el-dialog v-model="showCreate" title="添加媒体库" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="form.path" placeholder="local 或绝对路径" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="mixed" value="mixed" />
            <el-option label="local" value="local" />
            <el-option label="strm" value="strm" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.intro {
  margin: -8px 0 16px;
  font-size: 13px;
}
.libs {
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.lib-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
}
.lib-actions {
  display: flex;
  gap: 8px;
}
.hint {
  margin-bottom: 18px;
}
.pager {
  margin-top: 22px;
  display: flex;
  justify-content: center;
}
code {
  color: var(--accent);
}
</style>
