/** Normalize API / unknown errors into a user-facing Chinese message. */
export function getErrorMessage(e: unknown, fallback = '操作失败'): string {
  if (e == null) return fallback
  if (typeof e === 'string' && e.trim()) return e

  const err = e as {
    message?: string
    response?: { data?: { detail?: unknown }; status?: number }
  }

  const detail = err.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return ''
      })
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const m = (detail as { message?: unknown }).message
    if (typeof m === 'string' && m.trim()) return m
  }

  if (e instanceof Error && e.message && !e.message.startsWith('Request failed')) {
    return e.message
  }
  if (typeof err.message === 'string' && err.message && !err.message.startsWith('Request failed')) {
    return err.message
  }
  return fallback
}
