<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getHealth, getMovieProviders, getSettings, updateSettings } from '@/api/media'
import type { Health, ImageProxyMode, ScrapeSource, Settings, TranslateProvider } from '@/api/types'
import { getErrorMessage } from '@/utils/errors'
import { APP_VERSION } from '@/utils/version'
import AppIcon from '@/components/AppIcon.vue'
import { normalizeScrapeSource, scrapeSources } from '@/utils/scrapeSources'

const router = useRouter()
const appVersion = APP_VERSION

const settings = ref<Settings | null>(null)
const health = ref<Health | null>(null)
const form = ref({
  task_concurrency: 3,
  scrape_source: 'metatube' as ScrapeSource,
  stashscrapers_base_url: '',
  stashscrapers_token: '',
  stashscrapers_scraper_priority: [] as string[],
  stash_base_url: '',
  stash_api_key: '',
  stash_scraper_priority: [] as string[],
  metatube_base_url: '',
  metatube_token: '',
  metatube_provider_priority: [] as string[],
  auto_scrape: true,
  auto_translate: true,
  translate_provider: 'google' as TranslateProvider,
  translate_google_proxy: false,
  translate_google_proxy_url: '',
  translate_deepl_api_key: '',
  translate_deepl_api_url: '',
  translate_deepl_free: true,
  translate_deepl_proxy: false,
  translate_deepl_proxy_url: '',
  translate_ai_api_url: 'https://api.openai.com/v1/chat/completions',
  translate_ai_api_key: '',
  translate_ai_model: '',
  image_proxy_mode: 'site' as ImageProxyMode,
  image_external_proxy_url: '',
  image_local_cache: false,
  scan_extensions: '',
})
const saving = ref(false)
const providersRefreshing = ref(false)
const pageLoading = ref(true)
const healthChecking = ref(true)
const initialSnapshot = ref('')
const lastSavedAt = ref('')
const activeSection = ref('metadata')
const sections = [
  { id: 'libraries', label: '媒体库', icon: 'folder' },
  { id: 'metadata', label: '刮削来源', icon: 'server' },
  { id: 'translation', label: '自动翻译', icon: 'translate' },
  { id: 'images', label: '图片与缓存', icon: 'image' },
  { id: 'system', label: '系统状态', icon: 'shield' },
] as const
const isDirty = computed(
  () => Boolean(initialSnapshot.value) && JSON.stringify(form.value) !== initialSnapshot.value,
)
const priorityPick = ref<string[]>([])
const isStash = computed(() => form.value.scrape_source === 'stash')
const isStashScrapers = computed(() => form.value.scrape_source === 'stashscrapers')
const activeSourceFields = computed(() => scrapeSources[form.value.scrape_source])
const activePriority = computed({
  get: () => form.value[activeSourceFields.value.priority],
  set: (value: string[]) => {
    form.value[activeSourceFields.value.priority] = value
  },
})
const savedSource = computed(() => normalizeScrapeSource(settings.value?.scrape_source))
const connectedSource = computed(() => scrapeSources[savedSource.value].label)
const sourceHealth = computed(() => health.value?.[savedSource.value])
const watcherIssues = computed(() => (health.value?.watcher?.libraries || []).filter((entry) => entry.error))
const sourceCredentialSet = computed(
  () => settings.value?.[scrapeSources[savedSource.value].credentialSet],
)

watch(
  () => form.value.scrape_source,
  () => {
    priorityPick.value = [...activePriority.value]
  },
)

const showExternalTpl = computed(() => form.value.image_proxy_mode === 'external')
const showGoogleProxy = computed(() => form.value.translate_provider === 'google')
const showGoogleProxyUrl = computed(
  () => showGoogleProxy.value && form.value.translate_google_proxy,
)
const showDeepL = computed(() => form.value.translate_provider === 'deepl')
const showAI = computed(() => form.value.translate_provider === 'ai')
const showDeepLProxyUrl = computed(() => showDeepL.value && form.value.translate_deepl_proxy)
const movieProviders = computed(() =>
  form.value.scrape_source === (settings.value?.scrape_source || 'metatube')
    ? settings.value?.movie_providers || []
    : [],
)
const providerCount = computed(() => movieProviders.value.length)

function providerLabel(id: string): string {
  return settings.value?.scrape_source === form.value.scrape_source
    ? settings.value?.movie_provider_labels?.[id] || id
    : id
}

/**
 * MetaTube / Cloudflare can return a multi-KB blob as the error string — and it
 * is not always valid JSON (the backend may pass a Python repr). Never dump it
 * raw: try JSON, then a loose key match, then fall back to a clamped string.
 */
function shortenError(raw: string | null | undefined, fallback = '未知'): string {
  if (!raw) return fallback
  let text: unknown = raw
  try {
    const obj = JSON.parse(raw)
    text = obj?.title || obj?.detail || obj?.error?.message || raw
  } catch {
    /* not valid JSON — try to pull a readable field out of the blob */
    const m = raw.match(/["'](?:title|detail|message)["']\s*:\s*["']([^"']{4,200})["']/)
    if (m) text = m[1]
  }
  const s = String(text).replace(/\s+/g, ' ').trim()
  return s.length > 180 ? `${s.slice(0, 177)}…` : s
}

const shortError = computed(() => shortenError(sourceHealth.value?.error))
const shortProvidersError = computed(() => shortenError(settings.value?.movie_providers_error, ''))

const allProviderOptions = computed(() => {
  const set = new Set(movieProviders.value)
  for (const p of activePriority.value) {
    if (p) set.add(p)
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b))
})

function normalizeMode(mode: string | undefined): ImageProxyMode {
  if (mode === 'metatube' || mode === 'external') return mode
  return 'site'
}

function normalizeProvider(mode: string | undefined): TranslateProvider {
  if (mode === 'bing') return 'bing'
  if (mode === 'deepl') return 'deepl'
  if (mode === 'ai') return 'ai'
  return 'google'
}

function applySettingsToForm(s: Settings) {
  form.value.task_concurrency = s.task_concurrency ?? 3
  form.value.scrape_source = normalizeScrapeSource(s.scrape_source)
  form.value.stashscrapers_base_url = s.stashscrapers_base_url || ''
  form.value.stashscrapers_token = ''
  form.value.stashscrapers_scraper_priority = [...(s.stashscrapers_scraper_priority || [])]
  form.value.stash_base_url = s.stash_base_url || ''
  form.value.stash_api_key = ''
  form.value.stash_scraper_priority = [...(s.stash_scraper_priority || [])]
  form.value.metatube_base_url = s.metatube_base_url
  form.value.auto_scrape = s.auto_scrape
  form.value.auto_translate = s.auto_translate !== false
  form.value.translate_provider = normalizeProvider(s.translate_provider)
  form.value.translate_google_proxy = Boolean(s.translate_google_proxy)
  form.value.translate_google_proxy_url = s.translate_google_proxy_url || ''
  form.value.translate_deepl_free = s.translate_deepl_free !== false
  form.value.translate_deepl_api_url = s.translate_deepl_api_url || ''
  form.value.translate_deepl_proxy = Boolean(s.translate_deepl_proxy)
  form.value.translate_deepl_proxy_url = s.translate_deepl_proxy_url || ''
  form.value.translate_ai_api_url =
    s.translate_ai_api_url ?? 'https://api.openai.com/v1/chat/completions'
  form.value.translate_ai_model = s.translate_ai_model || ''
  form.value.image_proxy_mode = normalizeMode(s.image_proxy_mode)
  form.value.image_external_proxy_url = s.image_external_proxy_url || ''
  form.value.image_local_cache = Boolean(s.image_local_cache)
  form.value.scan_extensions = s.scan_extensions
  form.value.metatube_provider_priority = [...(s.metatube_provider_priority || [])]
  form.value.metatube_token = ''
  form.value.translate_deepl_api_key = ''
  form.value.translate_ai_api_key = ''
  priorityPick.value = [...activePriority.value]
  initialSnapshot.value = JSON.stringify(form.value)
}

async function refreshHealth() {
  healthChecking.value = true
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  } finally {
    healthChecking.value = false
  }
}

async function load() {
  pageLoading.value = true
  try {
    settings.value = await getSettings()
    applySettingsToForm(settings.value)
  } finally {
    pageLoading.value = false
  }
  void refreshHealth()
}

async function refreshProviders() {
  if (form.value.scrape_source !== settings.value?.scrape_source) {
    ElMessage.warning('切换刮削后端后，请先保存配置')
    return
  }
  providersRefreshing.value = true
  try {
    try {
      const data = await getMovieProviders()
      if (data.movie_providers?.length && settings.value) {
        settings.value = {
          ...settings.value,
          movie_providers: data.movie_providers,
          movie_provider_labels: data.movie_provider_labels,
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
  const prev = activePriority.value
  const next: string[] = []
  for (const p of prev) {
    if (vals.includes(p)) next.push(p)
  }
  for (const p of vals) {
    if (!next.includes(p)) next.push(p)
  }
  activePriority.value = next
  priorityPick.value = [...next]
}

function movePriority(index: number, dir: -1 | 1) {
  const list = [...activePriority.value]
  const j = index + dir
  if (j < 0 || j >= list.length) return
  ;[list[index], list[j]] = [list[j], list[index]]
  activePriority.value = list
  priorityPick.value = [...list]
}

const priorityList = ref<HTMLUListElement | null>(null)
const draggingProvider = ref<string | null>(null)
let priorityDrag: { pointer: number; source: ScrapeSource; original: string[] } | null = null

function startPriorityDrag(event: PointerEvent, provider: string) {
  if (event.button !== 0 || activePriority.value.length < 2) return
  priorityDrag = { pointer: event.pointerId, source: form.value.scrape_source, original: [...activePriority.value] }
  draggingProvider.value = provider
  priorityList.value?.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function movePriorityDrag(event: PointerEvent) {
  if (!priorityDrag || event.pointerId !== priorityDrag.pointer || !priorityList.value) return
  const rows = [...priorityList.value.querySelectorAll<HTMLLIElement>('li')]
  const index = rows.findIndex((row) => {
    const rect = row.getBoundingClientRect()
    return event.clientY >= rect.top && event.clientY <= rect.bottom
  })
  const from = activePriority.value.indexOf(draggingProvider.value || '')
  if (index < 0 || from < 0 || from === index) return
  const list = [...activePriority.value]
  list.splice(index, 0, ...list.splice(from, 1))
  activePriority.value = list
  priorityPick.value = [...list]
}

function endPriorityDrag(event: PointerEvent) {
  if (!priorityDrag || event.pointerId !== priorityDrag.pointer) return
  if (event.type === 'pointercancel' || event.type === 'lostpointercapture') {
    form.value[scrapeSources[priorityDrag.source].priority] = priorityDrag.original
    priorityPick.value = [...activePriority.value]
  }
  priorityDrag = null
  draggingProvider.value = null
}

function removePriority(index: number) {
  const list = activePriority.value.filter((_, i) => i !== index)
  activePriority.value = list
  priorityPick.value = [...list]
}

async function save() {
  if (isStashScrapers.value && !form.value.stashscrapers_base_url.trim()) {
    activeSection.value = 'metadata'
    ElMessage.warning('请填写 StashScrapers 服务地址')
    return
  }
  if (isStash.value && !form.value.stash_base_url.trim()) {
    activeSection.value = 'metadata'
    ElMessage.warning('请填写 Stash 服务地址')
    return
  }
  if (
    form.value.auto_translate &&
    showAI.value &&
    (!form.value.translate_ai_api_url.trim() || !form.value.translate_ai_model.trim())
  ) {
    activeSection.value = 'translation'
    ElMessage.warning('请填写 AI API 地址和模型名称')
    return
  }
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      scrape_source: form.value.scrape_source,
      stashscrapers_base_url: form.value.stashscrapers_base_url.trim(),
      stashscrapers_scraper_priority: form.value.stashscrapers_scraper_priority,
      stash_base_url: form.value.stash_base_url.trim(),
      stash_scraper_priority: form.value.stash_scraper_priority,
      metatube_base_url: form.value.metatube_base_url,
      auto_scrape: form.value.auto_scrape,
      auto_translate: form.value.auto_translate,
      translate_provider: form.value.translate_provider,
      translate_google_proxy: form.value.translate_google_proxy,
      translate_google_proxy_url: form.value.translate_google_proxy_url,
      translate_deepl_free: form.value.translate_deepl_free,
      translate_deepl_api_url: form.value.translate_deepl_api_url,
      translate_deepl_proxy: form.value.translate_deepl_proxy,
      translate_deepl_proxy_url: form.value.translate_deepl_proxy_url,
      translate_ai_api_url: form.value.translate_ai_api_url.trim(),
      translate_ai_model: form.value.translate_ai_model.trim(),
      image_proxy_mode: form.value.image_proxy_mode,
      image_external_proxy_url: form.value.image_external_proxy_url,
      image_local_cache: form.value.image_local_cache,
      scan_extensions: form.value.scan_extensions,
      task_concurrency: form.value.task_concurrency,
      metatube_provider_priority: form.value.metatube_provider_priority,
    }
    if (form.value.metatube_token) body.metatube_token = form.value.metatube_token
    if (form.value.stashscrapers_token.trim())
      body.stashscrapers_token = form.value.stashscrapers_token.trim()
    if (form.value.stash_api_key.trim()) body.stash_api_key = form.value.stash_api_key.trim()
    if (form.value.translate_deepl_api_key) {
      body.translate_deepl_api_key = form.value.translate_deepl_api_key
    }
    if (form.value.translate_ai_api_key.trim()) {
      body.translate_ai_api_key = form.value.translate_ai_api_key.trim()
    }
    settings.value = await updateSettings(body)
    applySettingsToForm(settings.value)
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    })
    void refreshHealth()
    ElMessage.success('设置已保存')
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
  <div class="page settings-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">按照你的方式运行</p>
        <h1 class="page-title">设置</h1>
        <p class="page-description">媒体库、刮削与翻译，一处管理。</p>
      </div>
      <el-button type="primary" :loading="saving" :disabled="pageLoading || !settings" @click="save"
        ><AppIcon name="check" :size="16" />保存设置</el-button
      >
    </header>
    <div v-if="pageLoading" class="settings-loading" role="status">
      <div />
      <div />
      <div />
      <p>正在读取配置…</p>
    </div>
    <div v-else-if="!settings" class="settings-error">
      <AppIcon name="server" :size="32" />
      <p>暂时无法读取设置</p>
      <el-button @click="load">重新加载</el-button>
    </div>
    <div v-else class="settings-layout">
      <nav class="settings-navigation" aria-label="设置分类">
        <button
          v-for="section in sections"
          :key="section.id"
          type="button"
          :class="{ active: activeSection === section.id }"
          :aria-pressed="activeSection === section.id"
          @click="activeSection = section.id"
        >
          <AppIcon :name="section.icon" :size="17" /><span>{{ section.label }}</span>
        </button>
      </nav>
      <div class="settings-content">
        <section
          v-show="activeSection === 'metadata'"
          class="settings-panel"
          aria-labelledby="metadata-heading"
        >
          <header class="panel-heading">
            <div>
              <h2 id="metadata-heading">刮削来源</h2>
              <p>连接元数据服务，选择适合你收藏的刮削器。</p>
            </div>
            <span
              class="connection-badge"
              :class="{
                healthy: sourceHealth?.ok,
                failed: !healthChecking && health && !sourceHealth?.ok,
              }"
              ><i />{{
                healthChecking
                  ? '正在检查连接'
                  : sourceHealth?.ok
                    ? `${connectedSource} 已连接`
                    : '连接待检查'
              }}</span
            >
          </header>
          <el-form class="settings-form" label-position="top" @submit.prevent="save">
            <el-form-item label="刮削后端">
              <el-select v-model="form.scrape_source" style="width: 100%">
                <el-option label="MetaTube" value="metatube" />
                <el-option label="Stash（社区刮削器 / Stash-box）" value="stash" />
                <el-option label="拾录 / StashScrapers（独立刮削服务）" value="stashscrapers" />
              </el-select>
            </el-form-item>
            <template v-if="isStashScrapers">
              <el-form-item label="StashScrapers 服务地址">
                <el-input
                  v-model="form.stashscrapers_base_url"
                  placeholder="http://stashscrapers:8080"
                />
                <span class="field-hint muted block"
                  >填写拾录服务的根地址，也支持以 /api 结尾的地址</span
                >
              </el-form-item>
              <el-form-item label="StashScrapers Bearer Token">
                <el-input
                  v-model="form.stashscrapers_token"
                  type="password"
                  show-password
                  placeholder="留空则不修改"
                />
                <span class="field-hint muted block"
                  >{{ settings?.stashscrapers_token_set ? '已配置' : '未配置' }} · 填写服务的
                  STASHSCRAPERS_TOKEN；未开启鉴权可留空</span
                >
              </el-form-item>
              <p class="field-hint muted span-full">
                使用独立的拾录服务，无需运行完整
                Stash。先在拾录中安装规则并启用所需刮削器，再保存连接配置、刷新源列表。仅列出已启用且具有可用影片动作的源；仅
                URL 的源需在详情页填写来源 URL。规则每日更新由拾录服务管理。
              </p>
            </template>
            <template v-else-if="isStash">
              <el-form-item label="Stash 服务地址">
                <el-input v-model="form.stash_base_url" placeholder="http://stash:9999" />
                <span class="field-hint muted block">填写服务根地址或完整的 /graphql 地址</span>
              </el-form-item>
              <el-form-item label="Stash API Key">
                <el-input
                  v-model="form.stash_api_key"
                  type="password"
                  show-password
                  placeholder="留空则不修改"
                />
                <span class="field-hint muted block">
                  {{ settings?.stash_api_key_set ? '已配置' : '未配置' }} · 在 Stash「设置 → 安全 →
                  身份验证」中获取；未开启鉴权可留空
                </span>
              </el-form-item>
              <p class="field-hint muted span-full">
                自动读取 Stash 中已安装的社区刮削器和已配置的 Stash-box（如
                StashDB）。保存连接配置后刷新源列表，再设置优先级；Stash-box 的地址和凭证由 Stash
                管理。仅支持 URL 的刮削器需在详情页填写来源 URL。
              </p>
            </template>
            <template v-else>
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
            </template>

            <el-form-item label="源列表">
              <div class="providers-meta">
                <span class="muted">共 {{ providerCount }} 个源</span>
                <el-button :loading="providersRefreshing" @click="refreshProviders">
                  刷新源列表
                </el-button>
              </div>
              <p
                v-if="
                  settings?.scrape_source === form.scrape_source && settings?.movie_providers_error
                "
                class="warn-line"
                :title="settings.movie_providers_error"
              >
                实时拉取失败：{{ shortProvidersError }}
                <span v-if="settings.movie_providers_from_cache">（已使用缓存列表）</span>
              </p>
            </el-form-item>

            <el-form-item label="刮削源优先级" class="span-full">
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
                    :label="providerLabel(p)"
                    :value="p"
                  />
                </el-select>
                <ul v-if="activePriority.length" ref="priorityList" class="priority-list"
                  @pointermove="movePriorityDrag" @pointerup="endPriorityDrag"
                  @pointercancel="endPriorityDrag" @lostpointercapture="endPriorityDrag">
                  <li v-for="(p, i) in activePriority" :key="p" :class="{ 'is-dragging': draggingProvider === p }">
                    <button
                      type="button"
                      class="priority-drag-handle"
                      :aria-label="`拖动调整 ${providerLabel(p)} 的优先级`"
                      :aria-pressed="draggingProvider === p"
                      :disabled="activePriority.length < 2"
                      @pointerdown="startPriorityDrag($event, p)"
                    ><span aria-hidden="true">⠿</span></button>
                    <span class="pri-idx">{{ i + 1 }}</span>
                    <span class="pri-name" :title="providerLabel(p)">{{ providerLabel(p) }}</span>
                    <span class="pri-actions">
                      <el-button size="small" text :disabled="i === 0" :aria-label="`上移 ${providerLabel(p)}`" @click="movePriority(i, -1)">
                        ↑
                      </el-button>
                      <el-button
                        size="small"
                        text
                        :disabled="i === activePriority.length - 1"
                        :aria-label="`下移 ${providerLabel(p)}`"
                        @click="movePriority(i, 1)"
                      >
                        ↓
                      </el-button>
                      <el-button size="small" text type="danger" :aria-label="`移除优先源 ${providerLabel(p)}`" @click="removePriority(i)">
                        ×
                      </el-button>
                    </span>
                  </li>
                </ul>
                <span class="field-hint muted block">
                  优先按列表从上到下尝试；全部失败或无结果后，继续尝试其余可用源。拖动手柄可调整顺序，命中后停止。
                </span>
              </div>
            </el-form-item>

          </el-form>
        </section>
        <section
          v-show="activeSection === 'libraries'"
          class="settings-panel"
          aria-labelledby="libraries-heading"
        >
          <header class="panel-heading">
            <div>
              <h2 id="libraries-heading">媒体库</h2>
              <p>管理扫描与目录变更，保持你的收藏井然有序。</p>
            </div>
          </header>
          <el-form class="settings-form" label-position="top" @submit.prevent="save">
            <el-form-item label="自动刮削">
              <el-switch v-model="form.auto_scrape" />
            </el-form-item>
            <el-form-item label="并发刮削数量">
              <el-input-number v-model="form.task_concurrency" :min="1" :max="8" aria-label="并发刮削数量" />
              <span class="field-hint muted block">默认同时处理 3 部影片，每部影片按来源优先级依次查询。修改将在当前任务结束后生效。</span>
            </el-form-item>
            <el-form-item label="扫描扩展名">
              <el-input v-model="form.scan_extensions" />
            </el-form-item>
          </el-form>
          <div class="directory-info">
            <AppIcon name="folder" :size="18" />
            <div>
              <span>媒体根目录</span><code>{{ settings.media_root }}</code>
            </div>
          </div>
          <div class="maintenance-link">
            <div>
              <h3>整理重复影片</h3>
              <p>查找跨库和同库重复项，选择需要保留的版本。</p>
            </div>
            <el-button @click="router.push({ name: 'duplicates' })"
              >查看重复项<AppIcon name="chevron" :size="14"
            /></el-button>
          </div>
        </section>
        <section
          v-show="activeSection === 'translation'"
          class="settings-panel"
          aria-labelledby="translation-heading"
        >
          <header class="panel-heading">
            <div>
              <h2 id="translation-heading">自动翻译</h2>
              <p>将标题、简介和标签翻译为简体中文，演员姓名保持原样。</p>
            </div>
          </header>
          <el-form class="settings-form" label-position="top" @submit.prevent="save">
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
                <el-option label="DeepL（需 API Key）" value="deepl" />
                <el-option label="AI 翻译（OpenAI 兼容）" value="ai" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="showGoogleProxy" label="Google 走代理">
              <el-switch v-model="form.translate_google_proxy" />
              <span class="field-hint muted">仅 Google gtx；关闭则直连</span>
            </el-form-item>
            <el-form-item v-if="showGoogleProxyUrl" label="Google 代理地址">
              <el-input
                v-model="form.translate_google_proxy_url"
                placeholder="http://127.0.0.1:7890"
              />
              <span class="field-hint muted block">
                支持 <code>http://</code> / <code>https://</code> / <code>socks5://</code> /
                <code>socks5h://</code>
              </span>
            </el-form-item>
            <template v-if="showDeepL">
              <el-form-item label="DeepL API Key">
                <el-input
                  v-model="form.translate_deepl_api_key"
                  type="password"
                  show-password
                  placeholder="留空则不修改"
                />
                <span class="field-hint muted block">
                  {{ settings?.translate_deepl_api_key_set ? '已配置' : '未配置' }} · 免费 Key 以
                  <code>:fx</code> 结尾，自动走 api-free 端点
                </span>
              </el-form-item>
              <el-form-item label="DeepL API 地址">
                <el-input
                  v-model="form.translate_deepl_api_url"
                  placeholder="留空自动：api-free.deepl.com 或 api.deepl.com"
                />
                <span class="field-hint muted block">
                  可填完整地址或域名根路径（自动补 <code>/v2/translate</code>）； 已含
                  <code>/translate</code> 的 DeepLX 地址会原样使用
                </span>
              </el-form-item>
              <el-form-item label="DeepL 免费端点">
                <el-switch
                  v-model="form.translate_deepl_free"
                  :disabled="!!form.translate_deepl_api_url.trim()"
                />
                <span class="field-hint muted">Pro Key 请关闭；自定义地址时忽略</span>
              </el-form-item>
              <el-form-item label="DeepL 走代理">
                <el-switch v-model="form.translate_deepl_proxy" />
                <span class="field-hint muted">关闭则直连 DeepL API</span>
              </el-form-item>
              <el-form-item v-if="showDeepLProxyUrl" label="DeepL 代理地址">
                <el-input
                  v-model="form.translate_deepl_proxy_url"
                  placeholder="http://127.0.0.1:7890"
                />
                <span class="field-hint muted block">
                  支持 <code>http://</code> / <code>https://</code> / <code>socks5://</code> /
                  <code>socks5h://</code>
                </span>
              </el-form-item>
            </template>
            <template v-if="showAI">
              <el-form-item label="AI API 地址">
                <el-input
                  v-model="form.translate_ai_api_url"
                  placeholder="https://api.example.com/v1/chat/completions"
                />
                <span class="field-hint muted block">
                  支持域名根地址、<code>/v1</code> 或完整的 <code>/v1/chat/completions</code> 地址
                </span>
              </el-form-item>
              <el-form-item label="AI 模型名称">
                <el-input
                  v-model="form.translate_ai_model"
                  placeholder="填写接口服务支持的模型名称"
                />
              </el-form-item>
              <el-form-item label="AI API Key">
                <el-input
                  v-model="form.translate_ai_api_key"
                  type="password"
                  show-password
                  placeholder="留空则不修改"
                />
                <span class="field-hint muted block">
                  {{ settings?.translate_ai_api_key_set ? '已配置' : '未配置' }} ·
                  本地免鉴权服务可不填；翻译失败时回退必应，仍失败则保留原文
                </span>
              </el-form-item>
            </template>
          </el-form>
        </section>
        <section
          v-show="activeSection === 'images'"
          class="settings-panel"
          aria-labelledby="images-heading"
        >
          <header class="panel-heading">
            <div>
              <h2 id="images-heading">图片与缓存</h2>
              <p>选择封面加载方式，按需开启磁盘缓存。</p>
            </div>
          </header>
          <el-form class="settings-form" label-position="top" @submit.prevent="save">
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
          </el-form>
          <p class="section-note">
            通过 Stash 刮削并保存的封面与头像由本站直接提供，不依赖 MetaTube 图片接口。
          </p>
        </section>
        <section
          v-show="activeSection === 'system'"
          class="settings-panel"
          aria-labelledby="system-heading"
        >
          <header class="panel-heading">
            <div>
              <h2 id="system-heading">系统状态</h2>
              <p>查看连接、目录监听与服务信息。</p>
            </div>
            <el-button :loading="healthChecking" @click="refreshHealth"
              ><AppIcon name="refresh" :size="14" />刷新状态</el-button
            >
          </header>
          <dl class="system-facts">
            <div>
              <dt>元数据服务</dt>
              <dd>
                <span
                  class="status-text"
                  :class="{
                    ok: sourceHealth?.ok,
                    err: !healthChecking && health && !sourceHealth?.ok,
                  }"
                  >{{ connectedSource }} ·
                  {{ healthChecking ? '检查中' : sourceHealth?.ok ? '已连接' : '未连接' }}</span
                >
              </dd>
            </div>
            <div v-if="!healthChecking && !sourceHealth?.ok">
              <dt>连接信息</dt>
              <dd class="err">{{ shortError }}</dd>
            </div>
            <div>
              <dt>服务凭证</dt>
              <dd>
                {{ sourceCredentialSet ? '已配置' : '未配置' }}
              </dd>
            </div>
            <div>
              <dt>登录验证</dt>
              <dd>{{ settings.auth_enabled ? '已启用' : '未启用' }}</dd>
            </div>
            <div>
              <dt>目录监听</dt>
              <dd>
                {{ health?.watcher?.running ? '运行中' : healthChecking ? '检查中' : '未运行'
                }}<span v-if="health?.watcher?.watched_library_ids?.length">
                  · {{ health.watcher.watched_library_ids.length }} 个媒体库</span
                >
              </dd>
            </div>
            <div v-for="entry in watcherIssues" :key="`watcher-${entry.id}`">
              <dt>{{ entry.name || `媒体库 ${entry.id}` }} 监听</dt>
              <dd class="err">{{ entry.error }}</dd>
            </div>
            <div>
              <dt>媒体根目录</dt>
              <dd class="mono">{{ settings.media_root }}</dd>
            </div>
            <div>
              <dt>应用版本</dt>
              <dd class="mono">{{ appVersion }}</dd>
            </div>
          </dl>
          <details v-if="sourceHealth?.data" class="connection-details">
            <summary>查看连接详情<AppIcon name="down" :size="14" /></summary>
            <pre>{{ JSON.stringify(sourceHealth.data, null, 2) }}</pre>
          </details>
          <p class="section-note">
            登录密码通过服务端 <code>ADMIN_PASSWORD</code> 配置。调试日志使用
            <code>LOG_LEVEL</code> / <code>DEBUG</code> 环境变量。
          </p>
        </section>
        <footer class="save-bar">
          <span :class="{ dirty: isDirty }"
            ><i v-if="isDirty" />{{
              isDirty
                ? '有尚未保存的修改'
                : lastSavedAt
                  ? `上次保存 ${lastSavedAt}`
                  : '已配置的密钥留空会保留原值'
            }}</span
          ><el-button type="primary" :loading="saving" @click="save"
            ><AppIcon name="check" :size="15" />保存设置</el-button
          >
        </footer>
      </div>
    </div>
  </div>
</template>
<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: 174px minmax(0, 1fr);
  gap: 30px;
  align-items: start;
}
.settings-navigation {
  display: grid;
  gap: 5px;
  position: sticky;
  top: 108px;
}
.settings-navigation button {
  display: flex;
  align-items: center;
  gap: 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  min-height: 43px;
  padding: 0 13px;
  text-align: left;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.settings-navigation button.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.settings-navigation button:hover:not(.active) {
  background: var(--panel-hover);
  color: var(--text);
}
.settings-content {
  min-width: 0;
}
.settings-panel {
  border: 1px solid var(--border-subtle);
  background: var(--bg-elevated);
  padding: 28px;
  border-radius: 12px;
}
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding-bottom: 25px;
  margin-bottom: 27px;
  border-bottom: 1px solid var(--border-subtle);
}
.panel-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.015em;
}
.panel-heading p {
  margin: 7px 0 0;
  color: var(--faint);
  font-size: 11px;
  line-height: 1.8;
}
.connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--faint);
  font-size: 10px;
  white-space: nowrap;
}
.connection-badge i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.connection-badge.healthy {
  color: var(--ok);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.connection-badge.failed {
  color: var(--danger);
}
.settings-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 24px;
  align-items: start;
}
.settings-form :deep(.el-form-item) {
  margin-bottom: 0;
  min-width: 0;
}
.settings-form > .span-full,
.settings-form :deep(.el-form-item.span-full) {
  grid-column: 1 / -1;
}
.settings-form :deep(.el-form-item__label) {
  margin-bottom: 9px;
  font-size: 12px !important;
  line-height: 1.5;
}
.settings-form :deep(.el-form-item__content) {
  min-width: 0;
  align-items: flex-start;
}
.settings-form :deep(.el-select),
.settings-form :deep(.el-input) {
  width: 100%;
}
.settings-form :deep(.el-input__wrapper),
.settings-form :deep(.el-select__wrapper) {
  background: var(--bg) !important;
}
.field-hint,
.settings-form :deep(.field-hint) {
  display: block;
  width: 100%;
  font-size: 11px;
  color: var(--faint);
  line-height: 1.8;
  margin: 7px 0 0;
}
.field-hint code {
  font-size: 10px;
}
.providers-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11px;
}
.providers-meta :deep(.el-button) {
  font-size: 11px;
}
.warn-line {
  margin: 9px 0 0;
  font-size: 10px;
  line-height: 1.8;
  color: var(--danger);
}
.priority-block {
  width: 100%;
}
.priority-list {
  list-style: none;
  margin: 13px 0 0;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  overflow: hidden;
}
.priority-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg);
}
.priority-list li:last-child {
  border-bottom: 0;
}
.priority-list li.is-dragging {
  background: var(--accent-soft);
  box-shadow: inset 3px 0 var(--accent);
}
.priority-drag-handle {
  display: grid;
  place-items: center;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--muted);
  font-size: 24px;
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.priority-drag-handle:active {
  color: var(--accent);
  cursor: grabbing;
}
.priority-drag-handle:disabled {
  opacity: 0.4;
}
.pri-idx {
  width: 23px;
  height: 23px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--faint);
  flex-shrink: 0;
}
.pri-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-soft);
}
.pri-actions {
  display: flex;
  gap: 2px;
}
.pri-actions :deep(.el-button.is-text) {
  padding: 3px 7px;
  min-width: 27px;
}
.pri-actions :deep(.el-button.is-disabled) {
  opacity: 0.35;
}
.directory-info {
  display: flex;
  gap: 12px;
  padding: 17px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  margin-top: 27px;
  color: var(--faint);
}
.directory-info span {
  display: block;
  font-size: 10px;
  margin-bottom: 4px;
}
.directory-info code {
  display: block;
  font-size: 11px;
  color: var(--text-soft);
  overflow-wrap: anywhere;
}
.maintenance-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 26px;
  margin-top: 26px;
  border-top: 1px solid var(--border-subtle);
}
.maintenance-link h3 {
  font-size: 13px;
  margin: 0 0 5px;
  font-weight: 500;
}
.maintenance-link p {
  font-size: 11px;
  color: var(--faint);
  margin: 0;
}
.maintenance-link :deep(.el-button) {
  flex-shrink: 0;
  font-size: 11px;
}
.system-facts {
  margin: 0;
}
.system-facts > div {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  padding: 16px 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
  gap: 16px;
}
.system-facts > div:first-child {
  padding-top: 0;
}
.system-facts > div:last-child {
  border-bottom: 0;
}
.system-facts dt {
  color: var(--faint);
}
.system-facts dd {
  margin: 0;
  color: var(--text-soft);
  overflow-wrap: anywhere;
}
.system-facts dd.ok,
.ok {
  color: var(--ok);
}
.system-facts dd.err,
.err {
  color: var(--danger);
}
.mono {
  font-family: var(--font-mono);
  font-size: 11px;
}
.connection-details {
  margin-top: 20px;
  font-size: 11px;
}
.connection-details summary {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  color: var(--muted);
}
.connection-details pre {
  overflow-x: auto;
  padding: 15px;
  background: var(--bg);
  border-radius: 7px;
  color: var(--faint);
  font-size: 10px;
}
.section-note {
  margin: 27px 0 0;
  padding-top: 21px;
  border-top: 1px solid var(--border-subtle);
  color: var(--faint);
  font-size: 11px;
  line-height: 1.9;
}
.save-bar {
  position: sticky;
  bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  padding: 13px 18px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 9px;
  box-shadow: var(--shadow-sm);
  z-index: 5;
}
.save-bar > span {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--faint);
}
.save-bar > span.dirty {
  color: var(--accent);
}
.save-bar i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.settings-loading {
  display: grid;
  gap: 17px;
  padding: 30px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
}
.settings-loading > div {
  height: 38px;
  background: var(--skeleton);
  border-radius: 6px;
  width: 70%;
}
.settings-loading > div:nth-child(2) {
  width: 90%;
}
.settings-loading p {
  font-size: 12px;
  color: var(--faint);
}
.settings-error {
  text-align: center;
  color: var(--faint);
  padding: 60px 20px;
}
.settings-error p {
  margin-bottom: 25px;
  font-size: 13px;
}
@media (max-width: 1100px) {
  .settings-layout {
    grid-template-columns: 145px minmax(0, 1fr);
    gap: 20px;
  }
  .settings-panel {
    padding: 23px;
  }
  .settings-form {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 860px) {
  .save-bar {
    bottom: calc(84px + env(safe-area-inset-bottom));
  }
}
@media (max-width: 700px) {
  .priority-list li {
    display: grid;
    grid-template-columns: 44px 23px minmax(0, 1fr);
    gap: 6px 8px;
    padding: 8px;
  }
  .priority-drag-handle {
    grid-row: 1 / 3;
    height: 100%;
  }
  .pri-actions {
    grid-column: 2 / -1;
    justify-content: flex-end;
  }
  .pri-actions :deep(.el-button.is-text) {
    min-width: 44px;
    min-height: 44px;
    margin-left: 0;
  }
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 19px;
  }
  .settings-navigation {
    display: flex;
    gap: 3px;
    overflow-x: auto;
    scrollbar-width: none;
    position: sticky;
    top: 68px;
    background: var(--bg);
    padding: 6px 0;
    z-index: 8;
    margin: -4px 0 0;
  }
  .settings-navigation button {
    flex-shrink: 0;
    min-height: 40px;
    padding: 0 11px;
    gap: 7px;
    font-size: 11px;
  }
  .settings-navigation button :deep(svg) {
    width: 14px;
    height: 14px;
  }
  .settings-panel {
    padding: 20px 17px;
  }
  .panel-heading {
    margin-bottom: 24px;
    padding-bottom: 21px;
    gap: 13px;
  }
  .panel-heading h2 {
    font-size: 16px;
  }
  .panel-heading p {
    font-size: 11px;
  }
  .field-hint,
  .settings-form :deep(.field-hint) {
    font-size: 11px;
  }
  .save-bar {
    padding: 12px;
  }
  .save-bar > span {
    font-size: 10px;
  }
  .save-bar :deep(.el-button) {
    padding: 0 12px;
    height: 40px;
  }
  .maintenance-link {
    flex-wrap: wrap;
  }
  .system-facts > div {
    grid-template-columns: 80px minmax(0, 1fr);
    gap: 12px;
    font-size: 11px;
  }
}
</style>
