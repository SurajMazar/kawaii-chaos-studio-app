import { create } from 'zustand'
import { api } from './api'
import type { Edit, Job, Line, Media } from './types'

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))

interface State {
  pid: string | null
  file: string
  edit: Edit | null
  savedJson: string            // JSON of the last saved edit (dirty check)
  past: Edit[]
  future: Edit[]
  sel: number                  // selected line index (in edit.lines order)
  playhead: number             // song seconds
  playing: boolean
  media: Media | null
  job: Job | null
  toast: string | null
  pxPerSec: number

  open: (pid: string, file?: string) => Promise<void>
  reloadMedia: () => Promise<void>
  /** Apply a change. coalesce = key: consecutive changes with the same key make ONE undo step (typing, dragging). */
  change: (fn: (e: Edit) => void, coalesce?: string) => void
  updateLine: (i: number, patch: Partial<Line>, coalesce?: string) => void
  undo: () => void
  redo: () => void
  save: () => Promise<void>
  setSel: (i: number) => void
  setPlayhead: (t: number) => void
  setPlaying: (p: boolean) => void
  setPx: (p: number) => void
  notify: (m: string) => void
  startRender: (q: 'preview' | 'final', bakeAudio: boolean) => Promise<void>
  cancelRender: () => Promise<void>
}

let lastCoalesce: string | undefined
let lastCoalesceAt = 0

export const useStore = create<State>((set, get) => ({
  pid: null, file: 'lyric_edit.json', edit: null, savedJson: '', past: [], future: [],
  sel: 0, playhead: 0, playing: false, media: null, job: null, toast: null, pxPerSec: 40,

  open: async (pid, file = 'lyric_edit.json') => {
    const [edit, media] = await Promise.all([api.edit(pid, file), api.media(pid)])
    localStorage.setItem('ls.pid', pid); localStorage.setItem('ls.file', file)
    set({ pid, file, edit, media, toast: null, savedJson: JSON.stringify(edit), past: [], future: [], sel: 0, playhead: edit.start, playing: false, job: null })
  },

  reloadMedia: async () => { const { pid } = get(); if (pid) set({ media: await api.media(pid) }) },

  change: (fn, coalesce) => {
    const { edit, past } = get(); if (!edit) return
    const next = clone(edit); fn(next)
    const now = performance.now()
    const merge = coalesce && coalesce === lastCoalesce && now - lastCoalesceAt < 1200
    lastCoalesce = coalesce; lastCoalesceAt = now
    set({ edit: next, past: merge ? past : [...past.slice(-199), edit], future: [] })
  },

  updateLine: (i, patch, coalesce) => get().change(e => {
    const l = e.lines[i]; Object.assign(l, patch)
    for (const k of Object.keys(patch) as (keyof Line)[]) if (patch[k] === undefined) delete l[k]
  }, coalesce),

  undo: () => {
    const { past, edit, future } = get(); if (!past.length || !edit) return
    lastCoalesce = undefined
    set({ edit: past[past.length - 1], past: past.slice(0, -1), future: [edit, ...future] })
  },
  redo: () => {
    const { past, edit, future } = get(); if (!future.length || !edit) return
    lastCoalesce = undefined
    set({ edit: future[0], future: future.slice(1), past: [...past, edit] })
  },

  save: async () => {
    const { pid, file, edit } = get(); if (!pid || !edit) return
    await api.save(pid, file, edit)
    set({ savedJson: JSON.stringify(edit) }); get().notify(`Saved ${file}`)
  },

  setSel: sel => set({ sel }),
  setPlayhead: playhead => set({ playhead }),
  setPlaying: playing => set({ playing }),
  setPx: pxPerSec => set({ pxPerSec }),
  notify: toast => { set({ toast }); setTimeout(() => get().toast === toast && set({ toast: null }), 2600) },

  startRender: async (q, bakeAudio) => {
    const { pid, file, edit } = get(); if (!pid || !edit) return
    if (q === 'final') await get().save()
    try {
      let job = await api.render(pid, edit, file, q, bakeAudio); set({ job })
      while (job.state === 'queued' || job.state === 'running') {
        await new Promise(r => setTimeout(r, 400))
        job = await api.job(job.id); set({ job })
      }
      if (job.state === 'done') { await get().reloadMedia(); get().notify(`${q === 'final' ? 'Final video' : 'Quick preview'} ready: ${String(job.result?.output ?? '')}`) }
      if (job.state === 'error') get().notify(`Render failed: ${job.error}`)
    } catch (e) { get().notify(String((e as Error).message)) }
  },
  cancelRender: async () => { const j = get().job; if (j) await api.cancel(j.id) },
}))

export const useDirty = () => useStore(s => !!s.edit && JSON.stringify(s.edit) !== s.savedJson)
