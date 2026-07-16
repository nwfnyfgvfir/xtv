import { computed, ref } from 'vue'
import client from '@/api/client'
import { getAuthStatus, login as apiLogin } from '@/api/media'

const TOKEN_KEY = 'tv-token'
const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
const authEnabled = ref(false)
const ready = ref(false)
let statusPromise: Promise<void> | null = null

export function useAuth() {
  const isAuthenticated = computed(() => {
    if (!authEnabled.value) return true
    return Boolean(token.value)
  })

  async function refreshStatus() {
    try {
      const s = await getAuthStatus()
      authEnabled.value = s.auth_enabled
      if (!s.auth_enabled) {
        // dev mode: ensure a token exists for consistency
        if (!token.value) {
          const res = await apiLogin('dev')
          setToken(res.access_token)
        }
      }
    } catch {
      authEnabled.value = false
    } finally {
      ready.value = true
    }
  }

  function setToken(t: string | null) {
    token.value = t
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
  }

  async function login(password: string) {
    const res = await apiLogin(password)
    setToken(res.access_token)
    authEnabled.value = res.auth_enabled
    return res
  }

  function logout() {
    setToken(null)
  }

  function authHeader(): Record<string, string> {
    if (!token.value) return {}
    return { Authorization: `Bearer ${token.value}` }
  }

  return {
    token,
    authEnabled,
    ready,
    isAuthenticated,
    refreshStatus,
    login,
    logout,
    setToken,
    authHeader,
  }
}

/** Single-flight auth bootstrap for router guards (avoids first-nav race). */
export function ensureAuthReady(): Promise<void> {
  const { ready, refreshStatus } = useAuth()
  if (ready.value) return Promise.resolve()
  if (!statusPromise) {
    statusPromise = refreshStatus().finally(() => {
      /* ready is set inside refreshStatus */
    })
  }
  return statusPromise
}

// attach axios interceptor once
let interceptorReady = false
export function setupAuthInterceptor(onUnauthorized: () => void) {
  if (interceptorReady) return
  interceptorReady = true
  client.interceptors.request.use((config) => {
    const t = localStorage.getItem(TOKEN_KEY)
    if (t) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${t}`
    }
    return config
  })
  client.interceptors.response.use(
    (r) => r,
    (err) => {
      if (err?.response?.status === 401) {
        localStorage.removeItem(TOKEN_KEY)
        token.value = null
        onUnauthorized()
      }
      return Promise.reject(err)
    },
  )
}
