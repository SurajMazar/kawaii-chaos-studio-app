import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Slider } from 'antd'
import { api } from '../api'
import { useStore } from '../store'
import { clamp, fmt, lastLineEnd, round2, shotsOf, videoEnd } from '../lib'
import type { Edit } from '../types'

type Drag =
  | { kind: 'move' | 'start' | 'end'; i: number; x0: number; s0: number; e0: number; prevEnd?: number; nextStart?: number; key: string }
  | { kind: 'shot'; i: number; j: number; x0: number; t0: number; key: string }
  | { kind: 'vstart' | 'vend'; x0: number; t0: number; key: string }
  | { kind: 'scrub' }

const LINE_COLORS = ['#ff5d8f', '#ffd84d', '#7cc8ff', '#9be38a', '#c59bff', '#ff9f5d']

export default function Timeline() {
  const pid = useStore(s => s.pid)!
  const edit = useStore(s => s.edit)!
  const sel = useStore(s => s.sel)
  const playhead = useStore(s => s.playhead)
  const px = useStore(s => s.pxPerSec)
  const { setSel, setPlayhead, setPx, change } = useStore.getState()
  const scroller = useRef<HTMLDivElement>(null)
  const drag = useRef<Drag | null>(null)
  const peaks = usePeaks(pid, edit.audio ?? null)

  const tMin = Math.floor(edit.start - 2)
  const tMax = Math.ceil(Math.max(videoEnd(edit), ...edit.lines.map(l => l.end)) + 2)
  const W = (tMax - tMin) * px
  const X = (t: number) => (t - tMin) * px
  const T = (clientX: number) => {
    const r = scroller.current!.getBoundingClientRect()
    return tMin + (clientX - r.left + scroller.current!.scrollLeft) / px
  }

  // keep the playhead visible while playing
  useEffect(() => {
    const el = scroller.current; if (!el) return
    const x = X(playhead)
    if (x < el.scrollLeft + 40 || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - el.clientWidth * 0.3
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playhead, px])

  const begin = (e: React.PointerEvent, d: Drag) => {
    e.stopPropagation(); (e.target as Element).setPointerCapture(e.pointerId); drag.current = d
    if (d.kind === 'scrub') setPlayhead(clamp(T(e.clientX), tMin, tMax))
  }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    if (d.kind === 'scrub') { setPlayhead(clamp(T(e.clientX), tMin, tMax)); return }
    if (Math.abs(e.clientX - d.x0) < 2) return            // a click, not a drag
    const dt = (e.clientX - d.x0) / px
    const snap = (t: number) => Math.abs(X(t) - X(playhead)) < 6 ? playhead : round2(t)
    change(ed => {
      if (d.kind === 'vstart') { ed.start = clamp(snap(d.t0 + dt), 0, lastLineEnd(ed) - 0.5); return }
      if (d.kind === 'vend') { ed.end = clamp(snap(d.t0 + dt), ed.start + 0.5, 9999); return }
      if (d.kind === 'shot') {
        const l = ed.lines[d.i]; const s = l.shots![d.j]
        s.at = clamp(snap(d.t0 + dt), l.start + 0.05, l.end - 0.05); return
      }
      if (d.kind !== 'move' && d.kind !== 'start' && d.kind !== 'end') return
      const l = ed.lines[d.i]; const prev = ed.lines[d.i - 1], next = ed.lines[d.i + 1]
      const shiftShots = (delta: number) => l.shots?.forEach(s => { if (s.at !== undefined) s.at = round2(s.at + delta) })
      if (d.kind === 'move') {
        const ns = snap(d.s0 + dt), delta = ns - l.start
        l.start = ns; l.end = round2(d.e0 + (ns - d.s0)); shiftShots(delta)
      } else if (d.kind === 'start') {
        l.start = clamp(snap(d.s0 + dt), 0, l.end - 0.1)
        if (prev && d.prevEnd !== undefined) prev.end = Math.max(prev.start + 0.1, l.start)   // linked edge
      } else {
        l.end = Math.max(snap(d.e0 + dt), l.start + 0.1)
        if (next && d.nextStart !== undefined) next.start = Math.min(next.end - 0.1, l.end)   // linked edge
      }
    }, d.key)
  }
  const onUp = () => { drag.current = null }

  const startLineDrag = (e: React.PointerEvent, i: number, kind: 'move' | 'start' | 'end') => {
    setSel(i)
    const l = edit.lines[i], prev = edit.lines[i - 1], next = edit.lines[i + 1]
    begin(e, {
      kind, i, x0: e.clientX, s0: l.start, e0: l.end, key: `drag${Math.random()}`,
      prevEnd: prev && Math.abs(prev.end - l.start) < 0.03 ? prev.end : undefined,
      nextStart: next && Math.abs(next.start - l.end) < 0.03 ? next.start : undefined,
    })
  }

  const ticks = useMemo(() => {
    const step = px > 120 ? 0.5 : px > 30 ? 1 : px > 12 ? 5 : 10
    const out: number[] = []; for (let t = Math.ceil(tMin / step) * step; t <= tMax; t += step) out.push(round2(t)); return out
  }, [tMin, tMax, px])

  const vEnd = lastLineEnd(edit)
  return (
    <div className="flex flex-col h-full min-w-0 bg-panel border-t border-line select-none">
      <div className="flex items-center gap-3 px-3 py-1.5 text-xs text-muted border-b border-line">
        <span className="label">Timeline</span>
        <span>drag a lyric to move · drag its edges to retime (joined neighbours move too) · drag ✂ cut points · click to scrub</span>
        <span className="ml-auto">zoom</span>
        <Slider className="!my-0 w-32" min={10} max={260} value={px} onChange={v => setPx(v)} tooltip={{ open: false }} />
        <Button size="small" onClick={() => setPx(Math.max(10, (scroller.current!.clientWidth - 20) / (tMax - tMin)))}>fit</Button>
      </div>
      <div ref={scroller} className="relative flex-1 overflow-x-auto overflow-y-hidden"
        onPointerMove={onMove} onPointerUp={onUp}
        onWheel={e => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setPx(clamp(px * (e.deltaY < 0 ? 1.15 : 0.87), 10, 260)) } }}>
        <div className="relative h-full" style={{ width: W }}>
          {/* ruler */}
          <div className="absolute inset-x-0 top-0 h-6 border-b border-line cursor-text" onPointerDown={e => begin(e, { kind: 'scrub' })}>
            {ticks.map(t => (
              <div key={t} className="absolute top-0 h-full border-l border-line/80 text-[10px] text-muted pl-1" style={{ left: X(t) }}>
                {Number.isInteger(t) ? fmt(t).replace(/\.00$/, '') : ''}
              </div>
            ))}
          </div>
          {/* video range: outside is dimmed; yellow handles = video start / last line end */}
          <div className="absolute top-6 bottom-0 bg-black/40 pointer-events-none" style={{ left: 0, width: X(edit.start) }} />
          <div className="absolute top-6 bottom-0 bg-black/40 pointer-events-none" style={{ left: X(videoEnd(edit)), right: 0 }} />
          <div className="absolute top-6 bottom-0 bg-white/5 pointer-events-none" style={{ left: X(vEnd), width: X(videoEnd(edit)) - X(vEnd) }}>
            <div className="text-[10px] text-muted p-1">end card</div>
          </div>
          <Handle x={X(edit.start)} label="start" onDown={e => begin(e, { kind: 'vstart', x0: e.clientX, t0: edit.start, key: `v${Math.random()}` })} />
          <Handle x={X(vEnd)} label="end" onDown={e => begin(e, { kind: 'vend', x0: e.clientX, t0: vEnd, key: `v${Math.random()}` })} />

          {/* lyrics track */}
          <div className="absolute inset-x-0 top-8 h-12" onPointerDown={e => begin(e, { kind: 'scrub' })}>
            {edit.lines.map((l, i) => (
              <div key={i}
                className={`absolute top-0 h-full rounded-md text-[11px] leading-tight px-2 py-1 overflow-hidden cursor-grab text-ink font-medium ${i === sel ? 'ring-2 ring-white z-10' : ''}`}
                style={{ left: X(l.start), width: Math.max(4, X(l.end) - X(l.start)), background: LINE_COLORS[i % LINE_COLORS.length] }}
                onPointerDown={e => startLineDrag(e, i, 'move')} onDoubleClick={() => setPlayhead(l.start)}>
                <div className="truncate">{i + 1}. {l.text.replace(/\*/g, '').replace(/\s*\/\s*/g, ' ')}</div>
                <div className="opacity-70 font-mono">{fmt(l.start)}</div>
                <div className="absolute left-0 top-0 h-full w-2 cursor-ew-resize hover:bg-black/25" onPointerDown={e => startLineDrag(e, i, 'start')} />
                <div className="absolute right-0 top-0 h-full w-2 cursor-ew-resize hover:bg-black/25" onPointerDown={e => startLineDrag(e, i, 'end')} />
              </div>
            ))}
          </div>

          {/* pictures / cuts track */}
          <div className="absolute inset-x-0 top-[88px] h-12" onPointerDown={e => begin(e, { kind: 'scrub' })}>
            <ShotTrack edit={edit} pid={pid} X={X} onShotDown={(e, i, j, t) => { setSel(i); begin(e, { kind: 'shot', i, j, x0: e.clientX, t0: t, key: `s${Math.random()}` }) }} />
          </div>

          {/* waveform */}
          <div className="absolute inset-x-0 top-[144px] bottom-1" onPointerDown={e => begin(e, { kind: 'scrub' })}>
            {peaks ? <Wave peaks={peaks} tMin={tMin} tMax={tMax} px={px} /> :
              <div className="text-[11px] text-muted pl-2 pt-2">{edit.audio ? 'loading waveform…' : 'no song loaded — add one in the right panel to see the waveform and hear it'}</div>}
          </div>

          {/* playhead */}
          <div className="absolute top-0 bottom-0 w-px bg-sun pointer-events-none z-20" style={{ left: X(playhead) }}>
            <div className="absolute -top-0 -left-[5px] size-[11px] rotate-45 bg-sun" />
          </div>
        </div>
      </div>
    </div>
  )
}

function Handle({ x, label, onDown }: { x: number; label: string; onDown: (e: React.PointerEvent) => void }) {
  return (
    <div className="absolute top-0 bottom-0 z-10 w-0" style={{ left: x }}>
      <div className="absolute top-0 bottom-0 w-px bg-sun/70" />
      <div className="absolute top-0 -translate-x-1/2 rounded bg-sun text-ink text-[10px] font-semibold px-1 cursor-ew-resize" onPointerDown={onDown}>{label}</div>
    </div>
  )
}

function ShotTrack({ edit, pid, X, onShotDown }: {
  edit: Edit; pid: string; X: (t: number) => number
  onShotDown: (e: React.PointerEvent, i: number, j: number, t: number) => void
}) {
  // flatten every cut with the picture it shows, then draw it until the next cut
  const cuts: { i: number; j: number; t: number; img?: string; zoom?: number; cut?: string }[] = []
  let cur: string | undefined
  edit.lines.forEach((l, i) => shotsOf(l).forEach(s => { if (s.image) cur = s.image; cuts.push({ i, j: s.idx, t: s.t, img: cur, zoom: s.zoom, cut: s.cut }) }))
  cuts.sort((a, b) => a.t - b.t)
  const last = lastLineEnd(edit)
  return <>{cuts.map((c, k) => {
    const to = k + 1 < cuts.length ? cuts[k + 1].t : last
    return (
      <div key={k} className="absolute top-0 h-full overflow-hidden rounded-sm border-l-2 border-white/70 bg-panel2"
        style={{ left: X(c.t), width: Math.max(2, X(to) - X(c.t)) }}>
        {c.img && <div className="absolute inset-0 bg-cover bg-center opacity-80"
          style={{ backgroundImage: `url(${api.thumbUrl('mv', pid, c.img, 160)})`, transform: c.zoom && c.zoom > 1 ? `scale(${c.zoom})` : undefined }} />}
        <div className="absolute left-0.5 top-0.5 rounded bg-black/70 px-1 text-[10px]">
          {c.j > 0 ? '✂ ' : ''}{c.zoom && c.zoom > 1 ? 'close-up ' : ''}{c.cut && c.cut !== 'ghost' && c.cut !== 'hard' ? c.cut : ''}
        </div>
        {c.j > 0 && <div className="absolute left-0 top-0 h-full w-2.5 cursor-ew-resize hover:bg-white/30" title="drag to move this cut"
          onPointerDown={e => onShotDown(e, c.i, c.j, c.t)} />}
      </div>
    )
  })}</>
}

function usePeaks(pid: string, audio: string | null) {
  const [peaks, setPeaks] = useState<{ rate: number; data: Float32Array } | null>(null)
  useEffect(() => {
    setPeaks(null); if (!audio) return
    let alive = true
    ;(async () => {
      const buf = await (await fetch(api.fileUrl('mv', pid, audio))).arrayBuffer()
      const ctx = new OfflineAudioContext(1, 1, 44100)
      const ab = await ctx.decodeAudioData(buf)
      const ch = ab.getChannelData(0), rate = 200, per = Math.floor(ab.sampleRate / rate)
      const data = new Float32Array(Math.ceil(ch.length / per))
      for (let i = 0; i < data.length; i++) { let m = 0; for (let k = i * per; k < Math.min(ch.length, (i + 1) * per); k++) m = Math.max(m, Math.abs(ch[k])); data[i] = m }
      let top = 0; for (const v of data) top = Math.max(top, v)
      if (top > 0) for (let i = 0; i < data.length; i++) data[i] /= top          // normalise: quiet songs still show
      if (alive) setPeaks({ rate, data })
    })().catch(() => {})
    return () => { alive = false }
  }, [pid, audio])
  return peaks
}

function Wave({ peaks, tMin, tMax, px }: { peaks: { rate: number; data: Float32Array }; tMin: number; tMax: number; px: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current!; const w = Math.min(32000, Math.round((tMax - tMin) * px)); const h = c.clientHeight
    c.width = w; c.height = h
    const g = c.getContext('2d')!; g.clearRect(0, 0, w, h); g.fillStyle = '#7cc8ff88'
    for (let x = 0; x < w; x++) {
      const t = tMin + x / px, i = Math.floor(t * peaks.rate)
      if (i < 0 || i >= peaks.data.length) continue
      let m = 0; const i2 = Math.floor((t + 1 / px) * peaks.rate)
      for (let k = i; k <= Math.min(i2, peaks.data.length - 1); k++) m = Math.max(m, peaks.data[k])
      const a = m * h * 0.9; g.fillRect(x, (h - a) / 2, 1, Math.max(1, a))
    }
  }, [peaks, tMin, tMax, px])
  return <canvas ref={ref} className="h-full" style={{ width: Math.min(32000, (tMax - tMin) * px) }} />
}
