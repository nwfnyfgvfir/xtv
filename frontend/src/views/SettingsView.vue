<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHealth, getSettings, updateSettings } from '@/api/media'
import type { Health, Settings } from '@/api/types'

const settings = ref<Settings | null>(null)
const health = ref<Health | null>(null)
const form = ref({
  metatube_base_url: '',
  metatube_token: '',
  alist_base_url: '',
  alist_token: '',
  auto_scrape: true,
  scan_extensions: '',
})
const saving = ref(false)

async function load() {
  settings.value = await getSettings()
  health.value = await getHealth()
  form.value.metatube_base_url = settings.value.metatube_base_url
  form.value.alist_base_url = settings.value.alist_base_url
  form.value.auto_scrape = settings.value.auto_scrape
  form.value.scan_extensions = settings.value.scan_extensions
  form.value.metatube_token = ''
  form.value.alist_token = ''
}

async function save() {
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      metatube_base_url: form.value.metatube_base_url,
      alist_base_url: form.value.alist_base_url,
      auto_scrape: form.value.auto_scrape,
      scan_extensions: form.value.scan_extensions,
    }
    if (form.value.metatube_token) body.metatube_token = form.value.metatube_token
    if (form.value.alist_token) body.alist_token = form.value.alist_token
    settings.value = await updateSettings(body)
    health.value = await getHealth()
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load().catch(() => ElMessage.error('无法读取设置'))
})
</script>

<template>
  <div class="page">
    <h1 class="page-title">设置</h1>

    <el-card class="card" shadow="never">
      <template #header>MetaTube 连通性</template>
      <p v-if="health?.metatube?.ok" class="ok">
        已连接：{{ JSON.stringify(health.metatube.data) }}
      </p>
      <p v-else class="err">
        未连接：{{ health?.metatube?.error || '未知' }}
      </p>
      <p class="muted">MEDIA_ROOT: {{ settings?.media_root }}</p>
      <p class="muted">
        Token 状态：MetaTube {{ settings?.metatube_token_set ? '已配置' : '未配置' }} · Alist
        {{ settings?.alist_token_set ? '已配置' : '未配置' }}
      </p>
    </el-card>

    <el-card class="card" shadow="never">
      <el-form label-width="140px" label-position="left">
        <el-form-item label="MetaTube URL">
          <el-input v-model="form.metatube_base_url" />
        </el-form-item>
        <el-form-item label="MetaTube Token">
          <el-input
            v-model="form.metatube_token"
            type="password"
            show-password
            placeholder="留空则不修改"
          />
        </el-form-item>
        <el-form-item label="Alist URL">
          <el-input v-model="form.alist_base_url" />
        </el-form-item>
        <el-form-item label="Alist Token">
          <el-input
            v-model="form.alist_token"
            type="password"
            show-password
            placeholder="留空则不修改"
          />
        </el-form-item>
        <el-form-item label="自动刮削">
          <el-switch v-model="form.auto_scrape" />
        </el-form-item>
        <el-form-item label="扫描扩展名">
          <el-input v-model="form.scan_extensions" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  margin-bottom: 16px;
  max-width: 720px;
}
.ok {
  color: #67c23a;
}
.err {
  color: #f56c6c;
}
</style>
