import type { Edit, Line, Shot } from './types'

/** 83.4 -> "1:23.40" */
export function fmt(s: number): string {
  if (!isFinite(s)) return '–'
  const neg = s < 0; s = Math.abs(s)
  const m = Math.floor(s / 60), r = s - m * 60
  return `${neg ? '-' : ''}${m}:${r.toFixed(2).padStart(5, '0')}`
}

/** "1:23.4" / "83.4" / "[01:23.40]" -> 83.4 (null if not a time) */
export function parseTime(v: string): number | null {
  const t = v.trim().replace(/^\[|\]$/g, '')
  if (/^-?\d+(\.\d+)?$/.test(t)) return parseFloat(t)
  const m = t.match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/)
  return m ? parseInt(m[1]) * 60 + parseFloat(m[2]) : null
}

export interface LrcRow { t: number; text: string }
/** Parses [mm:ss.xx]text lines (several stamps per line allowed). */
export function parseLrc(src: string): LrcRow[] {
  const out: LrcRow[] = []
  for (const raw of src.split(/\r?\n/)) {
    const stamps = [...raw.matchAll(/\[(\d+):(\d{1,2}(?:\.\d+)?)\]/g)]
    if (!stamps.length) continue
    const text = raw.replace(/\[[^\]]*\]/g, '').trim()
    for (const s of stamps) out.push({ t: parseInt(s[1]) * 60 + parseFloat(s[2]), text })
  }
  return out.sort((a, b) => a.t - b.t)
}

/** "*BIG* / small row" -> rows of {w, big} (mirrors lyric_edit.py parse + block auto-split) */
export function previewRows(line: Line): { w: string; big: boolean }[][] {
  let rows = line.text.split('/').map(g => g.trim().split(/\s+/).filter(Boolean)
    .map(w => ({ w: w.replace(/^\*|\*$/g, ''), big: w.length > 2 && w.startsWith('*') && w.endsWith('*') })))
    .filter(r => r.length)
  if (rows.length === 1) {
    const lim = { verse: 15, stack: 12, chorus: 12, block: 11 }[line.style ?? 'stack']
    const split: typeof rows = []; let cur: typeof rows[0] = []
    for (const w of rows[0]) {
      if (cur.length && [...cur, w].map(x => x.w).join(' ').length > lim) { split.push(cur); cur = [] }
      cur.push(w)
    }
    if (cur.length) split.push(cur); rows = split
  }
  if ((line.style ?? 'stack') === 'block' && rows.length && !rows.some(r => r.some(w => w.big))) rows[0][0] = { ...rows[0][0], big: true }
  return rows
}

/** The shots of a line with their real cut times (same rule as the renderer). */
export function shotsOf(line: Line): (Shot & { t: number; idx: number })[] {
  const sh = line.shots ?? (line.image ? [{ image: line.image }] : [])
  return sh.map((s, j) => ({ ...s, idx: j, t: s.at ?? line.start + (line.end - line.start) * j / sh.length }))
}

export function videoEnd(e: Edit): number {
  const last = e.end ?? Math.max(...e.lines.map(l => l.end))
  return last + (e.signature ? e.signature_seconds ?? 1.6 : 0)
}
export const lastLineEnd = (e: Edit) => e.end ?? Math.max(...e.lines.map(l => l.end))

/** Image used at a song second (for thumbnails in the timeline). */
export function imageAt(e: Edit, t: number): string | undefined {
  let cur: string | undefined
  let best: string | undefined, bestT = -Infinity
  for (const l of [...e.lines].sort((a, b) => a.start - b.start)) {
    for (const s of shotsOf(l)) {
      if (s.image) cur = s.image
      if (s.t <= t && s.t >= bestT) { bestT = s.t; best = cur }
    }
  }
  return best
}

export const round2 = (x: number) => Math.round(x * 100) / 100
export const clamp = (x: number, a: number, b: number) => Math.min(Math.max(x, a), b)
