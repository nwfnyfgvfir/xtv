<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHealth, getSettings, updateSettings } from '@/api/media'
import type { Health, ImageProxyMode, Settings } from '@/api/types'

const settings = ref<Settings | null>(null)
const health = ref<Health | null>(null)
const form = ref({
  metatube_base_url: '',
  metatube_token: '',
  metatube_provider: '',
  metatube_fallback: true,
  alist_base_url: '',
  alist_token: '',
  auto_scrape: true,
  auto_translate: true,
  image_proxy_mode: 'site' as ImageProxyMode,
  image_external_proxy_url: '',
  image_local_cache: false,
  scan_extensions: '',
})
const saving = ref(false)

const showExternalTpl = computed(() => form.value.image_proxy_mode === 'external')

function normalizeMode(mode: string | undefined): ImageProxyMode {
  if (mode === 'metatube' || mode === 'external') return mode
  return 'site'
}

async function load() {
  settings.value = await getSettings()
  health.value = await getHealth()
  form.value.metatube_base_url = settings.value.metatube_base_url
  form.value.alist_base_url = settings.value.alist_base_url
  form.value.auto_scrape = settings.value.auto_scrape
  form.value.auto_translate = settings.value.auto_translate !== false
  form.value.image_proxy_mode = normalizeMode(settings.value.image_proxy_mode)
  form.value.image_external_proxy_url = settings.value.image_external_proxy_url || ''
  form.value.image_local_cache = Boolean(settings.value.image_local_cache)
  form.value.scan_extensions = settings.value.scan_extensions
  form.value.metatube_provider = settings.value.metatube_provider || ''
  form.value.metatube_fallback = settings.value.metatube_fallback !== false
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
      auto_translate: form.value.auto_translate,
      image_proxy_mode: form.value.image_proxy_mode,
      image_external_proxy_url: form.value.image_external_proxy_url,
      image_local_cache: form.value.image_local_cache,
      scan_extensions: form.value.scan_extensions,
      metatube_provider: form.value.metatube_provider,
      metatube_fallback: form.value.metatube_fallback,
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
    <p class="muted intro">MetaTube 刮削源、图片代理、翻译与系统状态</p>

    <el-card class="card" shadow="never">
      <template #header>
        <span class="card-title">连通性</span>
      </template>
      <p v-if="health?.metatube?.ok" class="ok">
        MetaTube 已连接：{{ JSON.stringify(health.metatube.data) }}
      </p>
      <p v-else class="err">未连接：{{ health?.metatube?.error || '未知' }}</p>
      <p class="muted line">MEDIA_ROOT: {{ settings?.media_root }}</p>
      <p class="muted line">
        Token：MetaTube {{ settings?.metatube_token_set ? '已配置' : '未配置' }} · Alist
        {{ settings?.alist_token_set ? '已配置' : '未配置' }}
      </p>
      <p class="muted line">
        鉴权：{{ settings?.auth_enabled ? '已启用 (ADMIN_PASSWORD)' : '关闭（开发模式）' }}
      </p>
      <p class="muted line">
        调度器：{{ health?.scheduler?.running ? '运行中' : '未运行' }}
        <span v-if="health?.scheduler?.jobs?.length">
          · jobs {{ health.scheduler.jobs.length }}
        </span>
      </p>
    </el-card>

    <el-card class="card" shadow="never">
      <template #header>
        <span class="card-title">连接与刮削源</span>
      </template>
      <el-form label-width="150px" label-position="left">
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
        <el-form-item label="优先刮削源">
          <el-select
            v-model="form.metatube_provider"
            clearable
            filterable
            placeholder="自动（全部源 fallback）"
            style="width: 100%"
          >
            <el-option label="自动" value="" />
            <el-option
              v-for="p in settings?.movie_providers || []"
              :key="p"
              :label="p"
              :value="p"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="失败时 fallback">
          <el-switch v-model="form.metatube_fallback" />
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
        <el-form-item label="刮削后自动翻译">
          <el-switch v-model="form.auto_translate" />
          <span class="field-hint muted">日文标题/简介/演员/标签 → 简中（免费 Google）</span>
        </el-form-item>
        <el-form-item label="图片代理">
          <el-select v-model="form.image_proxy_mode" style="width: 100%">
            <el-option label="本站代理（/api/images/proxy）" value="site" />
            <el-option label="MetaTube 图片代理" value="metatube" />
            <el-option label="外部代理（模板 {url}）" value="external" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="showExternalTpl" label="外部代理模板">
          <el-input
            v-model="form.image_external_proxy_url"
            placeholder="https://wsrv.nl/?url={url}"
          />
          <span class="field-hint muted block">
            须包含 <code>{url}</code>，会替换为 URL-encode 后的原始图片地址
          </span>
        </el-form-item>
        <el-form-item label="图片本地缓存">
          <el-switch v-model="form.image_local_cache" />
          <span class="field-hint muted">
            仅对本站代理生效；写入 data/image-cache，优先读本地
          </span>
        </el-form-item>
        <el-form-item label="扫描扩展名">
          <el-input v-model="form.scan_extensions" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </el-form-item>
      </el-form>
      <p class="muted tip">
        定时扫描请在媒体库页对单个库开启「定时扫描」。登录密码通过环境变量
        <code>ADMIN_PASSWORD</code> 配置。调试日志用 <code>LOG_LEVEL</code> /
        <code>DEBUG</code>（环境变量，不在此页）。
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.intro {
  margin: -4px 0 18px;
  font-size: 13px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  margin-bottom: 16px;
  max-width: 760px;
  border-radius: 14px;
}
.card-title {
  font-weight: 600;
  letter-spacing: 0.04em;
}
.ok {
  color: var(--ok);
}
.err {
  color: var(--danger);
}
.line {
  margin: 6px 0;
  font-size: 13px;
}
.tip {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}
.field-hint {
  margin-left: 10px;
  font-size: 12px;
}
.field-hint.block {
  display: block;
  margin: 6px 0 0;
  margin-left: 0;
}
code {
  color: var(--accent);
}
</style>
