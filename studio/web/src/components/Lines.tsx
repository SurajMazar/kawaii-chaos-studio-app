import { useRef } from 'react'
import { Button, Checkbox, ColorPicker, Empty, Input, Segmented, Select, Slider, Tooltip, Typography } from 'antd'
import { PlusOutlined, ScissorOutlined, CopyOutlined, DeleteOutlined, UpOutlined, DownOutlined, AimOutlined, MinusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { clamp, fmt, parseTime, previewRows, round2, shotsOf } from '../lib'
import type { Cut, Line, Shot, Style } from '../types'

const STYLES: { v: Style; label: string; hint: string }[] = [
  { v: 'block', label: 'Block', hint: 'reference-reel look: BIG word + small rows, left' },
  { v: 'verse', label: 'Verse', hint: 'cute hand-lettering, types on' },
  { v: 'stack', label: 'Stack', hint: 'zig-zag rows, words rise' },
  { v: 'chorus', label: 'Chorus', hint: 'heavy colour caps, slam' },
]
const CUTS: { v: Cut; hint: string }[] = [
  { v: 'ghost', hint: 'soft crossfade' }, { v: 'hard', hint: 'straight cut' }, { v: 'flash', hint: 'white flash' },
  { v: 'shake', hint: 'camera shake' }, { v: 'whoosh', hint: 'fast slide' },
]

export function LineList() {
  const edit = useStore(s => s.edit)!
  const sel = useStore(s => s.sel)
  const playhead = useStore(s => s.playhead)
  const { setSel, setPlayhead, change } = useStore.getState()

  const add = () => change(e => {
    const lastL = e.lines[e.lines.length - 1]
    const s = round2(Math.max(playhead, lastL ? lastL.end : e.start))
    e.lines.push({ start: s, end: round2(s + 3), text: '*NEW* / line', style: lastL?.style ?? 'block', y: lastL?.y ?? 0.15, shots: [{ image: shotsOf(lastL ?? { start: 0, end: 0, text: '' }).find(x => x.image)?.image }] })
    e.lines.sort((a, b) => a.start - b.start)
  })
  return (
    <div className="flex flex-col min-h-0 h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line">
        <span className="label">Lyrics</span><span className="text-xs text-muted">{edit.lines.length} lines</span>
        <Tooltip title="Add a line at the playhead"><Button size="small" className="ml-auto" icon={<PlusOutlined />} onClick={add}>line</Button></Tooltip>
      </div>
      <div className="overflow-y-auto min-h-0 flex-1">
        {edit.lines.map((l, i) => {
          const live = l.start <= playhead && playhead < l.end
          return (
            <div key={i} onClick={() => { setSel(i); setPlayhead(l.start + 0.01) }}
              className={`px-3 py-2 border-b border-line/60 cursor-pointer transition-colors ${i === sel ? 'bg-panel2 border-l-2 !border-l-pink' : 'hover:bg-panel2/50'}`}>
              <div className="flex items-center gap-2 text-xs font-mono text-muted">
                <span className={`inline-block size-2 rounded-full ${live ? 'bg-sun' : 'bg-line'}`} />
                {i + 1} · {fmt(l.start)} → {fmt(l.end)} <span className="ml-auto">{(l.end - l.start).toFixed(2)}s</span>
              </div>
              <div className="mt-0.5 text-sm leading-snug">
                {previewRows(l).map((r, k, all) => <span key={k}>{r.map((w, q) => <span key={q} className={w.big ? 'font-display font-extrabold text-pink' : ''}>{w.w} </span>)}{k < all.length - 1 && <span className="text-muted"> / </span>}</span>)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const Lbl = ({ children, tip }: { children: React.ReactNode; tip?: string }) => tip ? <Tooltip title={tip}><span className="label cursor-help">{children}</span></Tooltip> : <span className="label">{children}</span>

export function LineEditor() {
  const pid = useStore(s => s.pid)!
  const edit = useStore(s => s.edit)!
  const sel = useStore(s => s.sel)
  const playhead = useStore(s => s.playhead)
  const media = useStore(s => s.media)
  const { updateLine, change, setSel, setPlayhead } = useStore.getState()
  const ta = useRef<HTMLTextAreaElement | null>(null)
  const l = edit.lines[sel]
  if (!l) return <Empty className="mt-10" description="Select a line on the left." />
  const up = (p: Partial<Line>, key?: string) => updateLine(sel, p, key)
  const style = l.style ?? 'stack'

  const wrapBig = () => {
    const t = ta.current; if (!t) return
    let a = t.selectionStart, b = t.selectionEnd; const s = l.text
    if (a === b) { while (a > 0 && !/[\s/]/.test(s[a - 1])) a--; while (b < s.length && !/[\s/]/.test(s[b])) b++ }
    const word = s.slice(a, b); if (!word.trim()) return
    const isBig = word.startsWith('*') && word.endsWith('*')
    up({ text: s.slice(0, a) + (isBig ? word.slice(1, -1) : `*${word.trim()}*`) + s.slice(b) })
  }
  const insertRow = () => {
    const t = ta.current; const a = t ? t.selectionStart : l.text.length
    up({ text: l.text.slice(0, a).trimEnd() + ' / ' + l.text.slice(a).trimStart() })
  }
  const shots: Shot[] = l.shots ?? (l.image ? [{ image: l.image }] : [])
  const setShots = (fn: (s: Shot[]) => void, key?: string) => change(e => {
    const L = e.lines[sel]; const s = L.shots ?? (L.image ? [{ image: L.image }] : []); fn(s); L.shots = s; delete L.image
  }, key)
  const imgs = media?.images ?? []
  const prevImage = (() => { let cur: string | undefined; for (let i = 0; i < sel; i++) for (const s of shotsOf(edit.lines[i])) if (s.image) cur = s.image; return cur })()

  const timeInput = (k: 'start' | 'end') => (
    <div className="flex items-center gap-1">
      <Input key={`${sel}${k}${l[k]}`} size="small" className="!w-[86px] font-mono" defaultValue={fmt(l[k])}
        onBlur={e => { const v = parseTime(e.target.value); if (v !== null) up({ [k]: round2(v) }) }}
        onPressEnter={e => (e.target as HTMLInputElement).blur()} />
      <Tooltip title="−0.05 s"><Button size="small" icon={<MinusOutlined />} onClick={() => up({ [k]: round2(l[k] - 0.05) }, `n${k}`)} /></Tooltip>
      <Tooltip title="+0.05 s"><Button size="small" icon={<PlusOutlined />} onClick={() => up({ [k]: round2(l[k] + 0.05) }, `n${k}`)} /></Tooltip>
      <Tooltip title={`Set to the playhead (${k === 'start' ? '[' : ']'})`}><Button size="small" icon={<AimOutlined />} onClick={() => up({ [k]: round2(playhead) })} /></Tooltip>
    </div>
  )
  const canSplit = playhead > l.start + 0.2 && playhead < l.end - 0.2

  return (
    <div className="p-3 flex flex-col gap-3 overflow-y-auto overflow-x-hidden min-h-0 min-w-0">
      <div className="flex items-center gap-1">
        <span className="font-display font-extrabold text-lg mr-auto">Line {sel + 1}</span>
        <Tooltip title="Previous line (↑)"><Button size="small" icon={<UpOutlined />} disabled={sel === 0} onClick={() => setSel(sel - 1)} /></Tooltip>
        <Tooltip title="Next line (↓)"><Button size="small" icon={<DownOutlined />} disabled={sel === edit.lines.length - 1} onClick={() => setSel(sel + 1)} /></Tooltip>
        <Tooltip title={canSplit ? 'Split this line at the playhead' : 'Move the playhead inside this line to split it'}><Button size="small" icon={<ScissorOutlined />} disabled={!canSplit}
          onClick={() => change(e => { const L = e.lines[sel]; const t = round2(playhead); e.lines.splice(sel + 1, 0, { ...JSON.parse(JSON.stringify(L)), start: t, shots: undefined, image: undefined, text: '*NEXT* / line' }); L.end = t })} /></Tooltip>
        <Tooltip title="Duplicate this line"><Button size="small" icon={<CopyOutlined />} onClick={() => change(e => { e.lines.splice(sel + 1, 0, JSON.parse(JSON.stringify(e.lines[sel]))) })} /></Tooltip>
        <Tooltip title="Delete this line (undo with ⌘Z)"><Button size="small" danger icon={<DeleteOutlined />} disabled={edit.lines.length < 2}
          onClick={() => { change(e => { e.lines.splice(sel, 1) }); setSel(Math.max(0, sel - 1)) }} /></Tooltip>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
        <Lbl>start</Lbl>{timeInput('start')}
        <Lbl>end</Lbl>{timeInput('end')}
      </div>

      <div>
        <div className="flex items-center gap-1 mb-1">
          <Lbl>text</Lbl>
          <Tooltip title="Make the word under the cursor BIG (or small again)"><Button size="small" className="ml-auto" onClick={wrapBig}>★ big word</Button></Tooltip>
          <Tooltip title="Start a new row at the cursor"><Button size="small" onClick={insertRow}>↵ new row</Button></Tooltip>
        </div>
        <Input.TextArea ref={r => { ta.current = r?.resizableTextArea?.textArea ?? null }} autoSize={{ minRows: 2, maxRows: 5 }} className="!text-[15px]" value={l.text}
          onChange={e => up({ text: e.target.value }, `text${sel}`)} />
        <Typography.Text type="secondary" className="!text-[11px]"><b>/</b> = new row · <b>*word*</b> = big word · no <b>/</b> → rows split automatically</Typography.Text>
        <div className="mt-2 rounded-lg bg-ink p-2 leading-tight">
          {previewRows(l).map((r, k) => <div key={k}>{r.map((w, q) => <span key={q} className={w.big ? 'font-display font-extrabold text-2xl mr-1.5' : 'font-display font-semibold text-sm mr-1'}>{style === 'block' || style === 'chorus' ? w.w.toUpperCase() : w.w}</span>)}</div>)}
        </div>
      </div>

      <div>
        <Lbl>look</Lbl>
        <Segmented block size="small" className="mt-1" value={style} onChange={v => up({ style: v as Style, anim: undefined })}
          options={STYLES.map(s => ({ value: s.v, label: <Tooltip title={s.hint}><span>{s.label}</span></Tooltip> }))} />
      </div>

      <div className="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-2 items-center text-sm">
        <Lbl tip="Where the text block sits (0 = top, 1 = bottom)">height</Lbl>
        <Slider className="!m-0" min={0.04} max={0.96} step={0.01} value={l.y ?? (edit.y as number) ?? 0.2} onChange={v => up({ y: v }, `y${sel}`)} tooltip={{ open: false }} />
        <span className="font-mono text-xs w-8">{(l.y ?? (edit.y as number) ?? 0.2).toFixed(2)}</span>
        <Lbl>align</Lbl>
        <Select size="small" value={l.align ?? ''} onChange={v => up({ align: (v || undefined) as Line['align'] })}
          options={[{ value: '', label: 'auto' }, { value: 'left', label: 'left' }, { value: 'center', label: 'center' }, { value: 'right', label: 'right' }]} /><span />
        <Lbl>flash</Lbl>
        <Checkbox checked={!!l.flash} onChange={e => up({ flash: e.target.checked || undefined })}><span className="text-xs opacity-70">white flash when the line starts</span></Checkbox><span />
        <Lbl>emoji</Lbl>
        <Input size="small" placeholder="e.g. 🔪🌹" value={l.emoji ?? ''} onChange={e => up({ emoji: e.target.value || undefined }, `em${sel}`)} /><span />
        {style !== 'block' && <>
          <Lbl tip="A crayon-painted band behind the text">stripe</Lbl>
          <div className="flex items-center gap-2">
            <ColorPicker size="small" value={l.stripe ?? '#ffd84d'} onChange={c => up({ stripe: c.toHexString() }, `st${sel}`)} disabledAlpha />
            {l.stripe ? <Button size="small" onClick={() => up({ stripe: undefined })}>none</Button> : <span className="text-xs opacity-50">off — pick a colour to add one</span>}
          </div><span />
        </>}
      </div>

      <div>
        <div className="flex items-center gap-1 mb-1">
          <Lbl>pictures & cuts</Lbl>
          <Tooltip title="Add a zoomed close-up of the same picture"><Button size="small" className="ml-auto" onClick={() => setShots(s => {
            const t = canSplit ? round2(playhead) : round2((l.start + l.end) / 2)
            s.push({ at: t, zoom: 1.6, focus: [0.5, 0.45], cut: 'hard' })
          })}>+ close-up</Button></Tooltip>
          <Tooltip title="Cut to another picture inside this line"><Button size="small" onClick={() => setShots(s => {
            const t = canSplit ? round2(playhead) : round2((l.start + l.end) / 2)
            s.push({ at: t, image: imgs[0]?.path, cut: 'flash' })
          })}>+ picture</Button></Tooltip>
        </div>
        {shots.length === 0 && <Typography.Text type="secondary" className="text-xs">No picture set — the previous line's picture continues. Click a picture in the right panel to use it here.</Typography.Text>}
        <div className="flex flex-col gap-2">
          {shots.map((s, j) => {
            const img = s.image ?? (() => { for (let k = j - 1; k >= 0; k--) if (shots[k].image) return shots[k].image; return prevImage })()
            const at = shotsOf(l)[j]?.t ?? l.start
            return (
              <div key={j} className="rounded-lg border border-line bg-panel2/60 p-2 flex gap-2 min-w-0">
                {img ? <FocusThumb pid={pid} img={img} zoom={s.zoom ?? 1} focus={s.focus ?? [0.5, 0.5]}
                  onFocus={f => setShots(x => { x[j].focus = f; if (!x[j].zoom || x[j].zoom === 1) x[j].zoom = 1.6 }, `f${sel}${j}`)} /> :
                  <div className="w-16 h-24 rounded bg-ink grid place-items-center text-[10px] text-muted">none</div>}
                <div className="flex-1 min-w-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1.5 items-center text-xs">
                  <span className="text-muted">{j === 0 ? 'at start' : 'cut at'}</span>
                  {j === 0 ? <span className="font-mono">{fmt(l.start)}</span> :
                    <div className="flex gap-1 items-center">
                      <Button size="small" className="font-mono" onClick={() => setPlayhead(at + 0.01)}>{fmt(at)}</Button>
                      <Tooltip title="Move this cut to the playhead"><Button size="small" icon={<AimOutlined />} onClick={() => setShots(x => { x[j].at = round2(clamp(playhead, l.start + 0.05, l.end - 0.05)) })} /></Tooltip>
                    </div>}
                  <span className="text-muted">picture</span>
                  <Select size="small" className="w-full min-w-0" value={s.image ?? ''} onChange={v => setShots(x => { x[j].image = v || undefined })} popupMatchSelectWidth={false}
                    options={[{ value: '', label: j === 0 ? '(same as before)' : '(same picture)' }, ...imgs.map(m => ({ value: m.path, label: m.path.replace('edit_frames/', '') }))]} />
                  <span className="text-muted">cut</span>
                  <Select size="small" className="w-full min-w-0" value={s.cut ?? (j === 0 ? 'ghost' : 'hard')} onChange={v => setShots(x => { x[j].cut = v as Cut })}
                    options={CUTS.map(c => ({ value: c.v, label: c.v, title: c.hint }))} popupMatchSelectWidth={false}
                    optionRender={o => <span>{o.value as string} <span className="opacity-60">— {CUTS.find(c => c.v === o.value)?.hint}</span></span>} />
                  <span className="text-muted">zoom</span>
                  <div className="flex items-center gap-1">
                    <Slider className="flex-1 min-w-0 !my-0" min={1} max={2.6} step={0.05} value={s.zoom ?? 1} tooltip={{ open: false }}
                      onChange={v => setShots(x => { x[j].zoom = v === 1 ? undefined : v; if (v > 1 && !x[j].focus) x[j].focus = [0.5, 0.45] }, `z${sel}${j}`)} />
                    <span className="font-mono w-8 shrink-0 text-right">{(s.zoom ?? 1).toFixed(2)}</span>
                  </div>
                  <span />
                  <div className="flex flex-wrap gap-1 items-center">
                    <Button size="small" disabled={j === 0} onClick={() => setShots(x => { x.splice(j, 1) })}>remove</Button>
                    <span className="text-muted">{(s.zoom ?? 1) > 1 ? 'click the picture to aim' : ''}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** Thumbnail; click sets the close-up focus point. The pink box shows what the close-up shows. */
function FocusThumb({ pid, img, zoom, focus, onFocus }: { pid: string; img: string; zoom: number; focus: [number, number]; onFocus: (f: [number, number]) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const w = 1 / zoom, h = 1 / zoom
  const left = clamp(focus[0] - w / 2, 0, 1 - w), top = clamp(focus[1] - h / 2, 0, 1 - h)
  return (
    <Tooltip title="Click to aim the close-up">
      <div ref={ref} className="relative w-14 shrink-0 cursor-crosshair self-start"
        onClick={e => { const r = ref.current!.getBoundingClientRect(); onFocus([round2((e.clientX - r.left) / r.width), round2((e.clientY - r.top) / r.height)]) }}>
        <img src={api.thumbUrl('mv', pid, img, 160)} className="w-full rounded" draggable={false} />
        {zoom > 1 && <div className="absolute border-2 border-pink rounded-sm pointer-events-none" style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }} />}
      </div>
    </Tooltip>
  )
}
