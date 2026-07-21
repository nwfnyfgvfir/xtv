export type ListAnchorKind = 'media' | 'actor'

type PendingAnchor = { kind: ListAnchorKind; id: number }

let pending: PendingAnchor | null = null
let restoreGen = 0

const ATTR: Record<ListAnchorKind, string> = {
  media: 'data-media-id',
  actor: 'data-actor-id',
}

export function rememberListAnchor(kind: ListAnchorKind, id: number): void {
  if (!Number.isFinite(id) || id <= 0) return
  pending = { kind, id: Math.floor(id) }
}

export function hasPendingListAnchor(): boolean {
  return pending != null
}

function findCard(kind: ListAnchorKind, id: number): Element | null {
  if (typeof document === 'undefined') return null
  return document.querySelector(`[${ATTR[kind]}="${id}"]`)
}

function scrollToEl(el: Element): void {
  el.scrollIntoView({
    block: 'center',
    inline: 'nearest',
    behavior: 'auto',
  })
}

/**
 * Restore scroll to the pending card of `kind` (consume-once).
 * If pending kind mismatches, leave it untouched for the other list.
 */
export function restoreListAnchor(
  kind: ListAnchorKind,
  opts?: { attempts?: number; intervalMs?: number },
): void {
  const target = pending
  if (!target || target.kind !== kind) return

  const attempts = opts?.attempts ?? 16
  const intervalMs = opts?.intervalMs ?? 45
  const gen = ++restoreGen
  const { id } = target
  let left = attempts

  const tick = () => {
    if (gen !== restoreGen) return
    // Pending may have been replaced by a newer open.
    if (!pending || pending.kind !== kind || pending.id !== id) return

    const el = findCard(kind, id)
    if (el) {
      scrollToEl(el)
      if (pending?.kind === kind && pending.id === id) pending = null
      return
    }

    left -= 1
    if (left <= 0) {
      if (pending?.kind === kind && pending.id === id) pending = null
      return
    }
    if (typeof window === 'undefined') {
      if (pending?.kind === kind && pending.id === id) pending = null
      return
    }
    window.setTimeout(tick, intervalMs)
  }

  if (typeof window === 'undefined') {
    pending = null
    return
  }
  // Defer one frame so keep-alive reactivation can paint first.
  window.requestAnimationFrame(() => {
    if (gen !== restoreGen) return
    tick()
  })
}
