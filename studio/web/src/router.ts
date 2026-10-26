import { useSyncExternalStore } from 'react'

/** Tiny hash router: #/p/strip/166_x/qa -> ['p','strip','166_x','qa'] (+ ?query) */
function snapshot() { return window.location.hash || '#/' }
function subscribe(cb: () => void) { window.addEventListener('hashchange', cb); return () => window.removeEventListener('hashchange', cb) }

export function useRoute() {
  const h = useSyncExternalStore(subscribe, snapshot)
  const [path, query = ''] = h.replace(/^#\/?/, '').split('?')
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  return { parts, query: new URLSearchParams(query), hash: h }
}

export function go(path: string) {
  const h = '#' + (path.startsWith('/') ? path : '/' + path)
  if (window.location.hash !== h) window.location.hash = h
}

export const href = (path: string) => '#' + (path.startsWith('/') ? path : '/' + path)

/** Guards for pages with unsaved changes (lyric editor, reel editor, text editors). */
const guards = new Set<() => boolean>()
export function addLeaveGuard(fn: () => boolean) { guards.add(fn); return () => { guards.delete(fn) } }
export function canLeave() {
  for (const g of guards) if (g() && !window.confirm('You have unsaved changes on this page. Leave without saving?')) return false
  return true
}
