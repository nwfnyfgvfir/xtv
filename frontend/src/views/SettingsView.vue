<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHealth, getMovieProviders, getSettings, updateSettings } from '@/api/media'
import type { Health, ImageProxyMode, Settings, TranslateProvider } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'

const settings = ref<Settings | null>(null)
const health = ref<Health | null>(null)
const form = ref({
  metatube_base_url: '',
  metatube_token: '',
  metatube_provider: '',
  metatube_provider_priority: [] as string[],
  metatube_fallback: true,
  alist_base_url: '',
  alist_token: '',
  auto_scrape: true,
  auto_translate: true,
  translate_provider: 'google' as TranslateProvider,
  image_proxy_mode: 'site' as ImageProxyMode,
  image_external_proxy_url: '',
  image_local_cache: false,
  scan_extensions: '',
})
const saving = ref(false)
const providersRefreshing = ref(false)
const priorityPick = ref<string[]>([])

const showExternalTpl = computed(() => form.value.image_proxy_mode === 'external')
const movieProviders = computed(() => settings.value?.movie_providers || [])
const providerCount = computed(() => movieProviders.value.length)
const hasPriority = computed(() => form.value.metatube_provider_priority.length > 0)

const allProviderOptions = computed(() => {
  const set = new Set(movieProviders.value)
  for (const p of form.value.metatube_provider_priority) {
    if (p) set.add(p)
  }
  if (form.value.metatube_provider) set.add(form.value.metatube_provider)
  return Array.from(set).sort((a, b) => a.localeCompare(b))
})

function normalizeMode(mode: string | undefined): ImageProxyMode {
  if (mode === 'metatube' || mode === 'external') return mode
  return 'site'
}

function normalizeProvider(mode: string | undefined): TranslateProvider {
  return mode === 'bing' ? 'bing' : 'google'
}

function applySettingsToForm(s: Settings) {
  form.value.metatube_base_url = s.metatube_base_url
  form.value.alist_base_url = s.alist_base_url
  form.value.auto_scrape = s.auto_scrape
  form.value.auto_translate = s.auto_translate !== false
  form.value.translate_provider = normalizeProvider(s.translate_provider)
  form.value.image_proxy_mode = normalizeMode(s.image_proxy_mode)
  form.value.image_external_proxy_url = s.image_external_proxy_url || ''
  form.value.image_local_cache = Boolean(s.image_local_cache)
  form.value.scan_extensions = s.scan_extensions
  form.value.metatube_provider = s.metatube_provider || ''
  form.value.metatube_provider_priority = [...(s.metatube_provider_priority || [])]
  form.value.metatube_fallback = s.metatube_fallback !== false
  form.value.metatube_token = ''
  form.value.alist_token = ''
  priorityPick.value = [...form.value.metatube_provider_priority]
}

async function load() {
  settings.value = await getSettings()
  health.value = await getHealth()
  applySettingsToForm(settings.value)
}

async function refreshProviders() {
  providersRefreshing.value = true
  try {
    try {
      const data = await getMovieProviders()
      if (data.movie_providers?.length && settings.value) {
        settings.value = {
          ...settings.value,
          movie_providers: data.movie_providers,
          movie_providers_error: null,
          movie_providers_from_cache: Boolean(data.from_cache),
        }
      }
    } catch {
      /* fall through to full settings reload */
    }
    settings.value = await getSettings()
    ElMessage.success(`已刷新：共 ${settings.value.movie_providers?.length || 0} 个源`)
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '刷新源列表失败'))
  } finally {
    providersRefreshing.value = false
  }
}

function onPriorityPickChange(vals: string[]) {
  const prev = form.value.metatube_provider_priority
  const next: string[] = []
  for (const p of prev) {
    if (vals.includes(p)) next.push(p)
  }
  for (const p of vals) {
    if (!next.includes(p)) next.push(p)
  }
  form.value.metatube_provider_priority = next
  priorityPick.value = [...next]
}

function movePriority(index: number, dir: -1 | 1) {
  const list = [...form.value.metatube_provider_priority]
  const j = index + dir
  if (j < 0 || j >= list.length) return
  ;[list[index], list[j]] = [list[j], list[index]]
  form.value.metatube_provider_priority = list
  priorityPick.value = [...list]
}

function removePriority(index: number) {
  const list = form.value.metatube_provider_priority.filter((_, i) => i !== index)
  form.value.metatube_provider_priority = list
  priorityPick.value = [...list]
}

async function save() {
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      metatube_base_url: form.value.metatube_base_url,
      alist_base_url: form.value.alist_base_url,
      auto_scrape: form.value.auto_scrape,
      auto_translate: form.value.auto_translate,
      translate_provider: form.value.translate_provider,
      image_proxy_mode: form.value.image_proxy_mode,
      image_external_proxy_url: form.value.image_external_proxy_url,
      image_local_cache: form.value.image_local_cache,
      scan_extensions: form.value.scan_extensions,
      metatube_provider: form.value.metatube_provider,
      metatube_provider_priority: form.value.metatube_provider_priority,
      metatube_fallback: form.value.metatube_fallback,
    }
    if (form.value.metatube_token) body.metatube_token = form.value.metatube_token
    if (form.value.alist_token) body.alist_token = form.value.alist_token
    settings.value = await updateSettings(body)
    applySettingsToForm(settings.value)
    health.value = await getHealth()
    ElMessage.success('已保存')
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load().catch((e: unknown) => ElMessage.error(getErrorMessage(e, '无法读取设置')))
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

        <el-form-item label="源列表">
          <div class="providers-meta">
            <span class="muted">共 {{ providerCount }} 个源</span>
            <el-button size="small" :loading="providersRefreshing" @click="refreshProviders">
              刷新源列表
            </el-button>
          </div>
          <p v-if="settings?.movie_providers_error" class="warn-line">
            实时拉取失败：{{ settings.movie_providers_error }}
            <span v-if="settings.movie_providers_from_cache">（已使用缓存列表）</span>
          </p>
        </el-form-item>

        <el-form-item label="刮削源优先级">
          <div class="priority-block">
            <el-select
              :model-value="priorityPick"
              multiple
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="从全部源中选择并按顺序排列"
              style="width: 100%"
              @update:model-value="onPriorityPickChange"
            >
              <el-option
                v-for="p in allProviderOptions"
                :key="p"
                :label="p"
                :value="p"
              />
            </el-select>
            <ul v-if="form.metatube_provider_priority.length" class="priority-list">
              <li v-for="(p, i) in form.metatube_provider_priority" :key="`${p}-${i}`">
                <span class="pri-idx">{{ i + 1 }}</span>
                <span class="pri-name">{{ p }}</span>
                <span class="pri-actions">
                  <el-button size="small" text :disabled="i === 0" @click="movePriority(i, -1)">
                    ↑
                  </el-button>
                  <el-button
                    size="small"
                    text
                    :disabled="i === form.metatube_provider_priority.length - 1"
                    @click="movePriority(i, 1)"
                  >
                    ↓
                  </el-button>
                  <el-button size="small" text type="danger" @click="removePriority(i)">
                    ×
                  </el-button>
                </span>
              </li>
            </ul>
            <span class="field-hint muted block">
              刮削时按顺序尝试；全部未命中后由下方 fallback 决定是否再搜其余源。为空时走兼容单源。
            </span>
          </div>
        </el-form-item>

        <el-form-item label="兼容单源">
          <el-select
            v-model="form.metatube_provider"
            clearable
            filterable
            allow-create
            default-first-option
            :disabled="hasPriority"
            placeholder="自动（优先级为空时生效）"
            style="width: 100%"
          >
            <el-option label="自动" value="" />
            <el-option
              v-for="p in allProviderOptions"
              :key="p"
              :label="p"
              :value="p"
            />
          </el-select>
          <span class="field-hint muted block">
            优先级列表为空时生效；非空时刮削按优先级顺序尝试
          </span>
        </el-form-item>

        <el-form-item label="失败时 fallback">
          <el-switch v-model="form.metatube_fallback" />
          <span class="field-hint muted">优先级全部未命中后是否再搜索其余源</span>
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
          <span class="field-hint muted">日文标题/简介/标签 → 简中（不翻译演员名）</span>
        </el-form-item>
        <el-form-item label="翻译服务">
          <el-select
            v-model="form.translate_provider"
            style="width: 100%"
            :disabled="!form.auto_translate"
          >
            <el-option label="免费 Google（gtx）" value="google" />
            <el-option label="免费必应（Edge）" value="bing" />
          </el-select>
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
.providers-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.warn-line {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--danger);
  line-height: 1.45;
}
.priority-block {
  width: 100%;
}
.priority-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.priority-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
}
.priority-list li:last-child {
  border-bottom: none;
}
.pri-idx {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  background: var(--accent-soft);
  color: var(--accent);
  flex-shrink: 0;
}
.pri-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.pri-actions {
  display: inline-flex;
  gap: 0;
  flex-shrink: 0;
}
.pri-actions :deep(.el-button.is-text) {
  color: var(--muted) !important;
  min-width: 28px;
  padding: 4px 6px;
}
.pri-actions :deep(.el-button.is-text:not(.is-disabled):hover) {
  color: var(--accent) !important;
}
.pri-actions :deep(.el-button.is-text.is-disabled) {
  color: var(--muted) !important;
  opacity: 0.4;
}
.pri-actions :deep(.el-button.is-text.el-button--danger) {
  color: var(--danger) !important;
}
code {
  color: var(--accent);
}
@media (max-width: 640px) {
  :deep(.el-form-item) {
    flex-direction: column;
    align-items: stretch;
  }
  :deep(.el-form-item__label) {
    justify-content: flex-start;
    height: auto;
    line-height: 1.4;
    margin-bottom: 6px;
  }
}
</style>
