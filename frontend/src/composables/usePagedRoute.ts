import { ref } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { pageQueryPatch, parsePage, scrollListTop } from '@/utils/pageQuery'

/**
 * Shared page + route.query helpers for list views.
 * Parent still owns data loading; this only keeps `page` and URL in sync.
 */
export function usePagedRoute() {
  const route = useRoute()
  const router = useRouter()
  const page = ref(parsePage(route.query))

  /** Replace query keys and set page (default 1 when not passed via nextPage). */
  function replaceQuery(patch: LocationQueryRaw, nextPage?: number) {
    const p = nextPage ?? page.value
    page.value = p
    router.replace({
      query: {
        ...route.query,
        ...patch,
        ...pageQueryPatch(p),
      },
    })
  }

  /**
   * Change page in URL. Returns false if unchanged.
   * @param scroll scroll to top (default true)
   */
  function goPage(p: number, opts?: { scroll?: boolean }): boolean {
    if (p === page.value) return false
    page.value = p
    router.replace({
      query: {
        ...route.query,
        ...pageQueryPatch(p),
      },
    })
    if (opts?.scroll !== false) scrollListTop()
    return true
  }

  /** Sync local page from route (e.g. browser back). Returns true if page changed. */
  function syncPageFromRoute(): boolean {
    const p = parsePage(route.query)
    if (p !== page.value) {
      page.value = p
      return true
    }
    return false
  }

  return {
    route,
    router,
    page,
    replaceQuery,
    goPage,
    syncPageFromRoute,
    scrollListTop,
  }
}
