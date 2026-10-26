import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Card, Checkbox, Empty, InputNumber, Modal, Popconfirm, Result, Segmented, Select, Slider, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import {
  AimOutlined, ArrowDownOutlined, ArrowUpOutlined, BorderOutlined, CaretRightOutlined, DeleteOutlined, PauseOutlined, PlusOutlined,
  SaveOutlined, ScissorOutlined, ThunderboltOutlined, UndoOutlined, VideoCameraOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { api } from '../api'
import { addLeaveGuard, canLeave, go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import { JobPanel, useJob } from '../components/Jobs'
import { clamp, fmt, round2 } from '../lib'
import type { Box, CamKey, Item, ReelInfo, SbShot, Storyboard } from '../types'

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
const TRANSITIONS = ['cut', 'dissolve', 'dip', 'slide', 'push', 'drop', 'wipe', 'zoom', 'iris', 'pagefold']
const EASES = ['inout', 'linear', 'out', 'in', 'back']
const dur = (s: SbShot) => round2(s.end - s.start)
const isPanel = (s: SbShot) => s.id !== 'end'
/** Panel number from its picture (panel3.png -> 3), so the name follows the panel when the order changes. */
const pnum = (s: SbShot) => s.image.match(/panel(\d+)/)?.[1] ?? '?'

/** Camera presets: start key and end key (x, y = view centre 0-1, zoom 1 = whole panel). */
const PRESETS: { key: string; label: string; a: Partial<CamKey>; b: Partial<CamKey>; hold?: boolean }[] = [
  { key: 'push', label: 'Slow push-in', a: { x: 0.5, y: 0.5, zoom: 1 }, b: { x: 0.5, y: 0.5, zoom: 1.12 } },
  { key: 'panlr', label: 'Pan left → right', a: { x: 0, y: 0.5, zoom: 1 }, b: { x: 1, y: 0.5, zoom: 1.04 } },
  { key: 'panrl', label: 'Pan right → left', a: { x: 1, y: 0.5, zoom: 1 }, b: { x: 0, y: 0.5, zoom: 1.04 } },
  { key: 'pantb', label: 'Pan top → bottom', a: { x: 0.5, y: 0, zoom: 1.3 }, b: { x: 0.5, y: 1, zoom: 1.3 } },
  { key: 'zoomout', label: 'Close-up → zoom out', a: { x: 0.5, y: 0.4, zoom: 1.6 }, b: { x: 0.5, y: 0.5, zoom: 1 } },
  { key: 'still', label: 'Still', a: { x: 0.5, y: 0.5, zoom: 1 }, b: { x: 0.5, y: 0.5, zoom: 1 } },
]

/** Recompute start/end of every shot from its duration (in list order) and keep events attached to their shot. */
function retime(sb: Storyboard, mutate: (shots: SbShot[]) => void) {
  const events = (sb.events ?? []).map(e => {
    const s = sb.shots.find(x => e.t >= x.start && e.t < x.end) ?? sb.shots[sb.shots.length - 1]
    return { e, id: s.id, off: e.t - s.start }
  })
  mutate(sb.shots)
  let t = 0
  sb.shots.forEach((s, i) => {
    const d = Math.max(0.3, s.end - s.start); s.start = round2(t); s.end = round2(t + d); t += d
    if (s.card) s.card.intro = i === 0
    if (i === 0) delete s.transition_in
    else if (!s.transition_in) s.transition_in = { type: 'dissolve', dur: 0.25 }
  })
  for (const { e, id, off } of events) { const s = sb.shots.find(x => x.id === id); if (s) e.t = round2(s.start + Math.min(off, dur(s) - 0.05)) }
  sb.output.duration = round2(t)
  const mus = sb.music as { outro_at?: number } | undefined
  if (mus?.outro_at !== undefined) mus.outro_at = sb.shots[sb.shots.length - 1].start
}

/** Camera keys from start/end framing. hold = old stop-go pan (kept only so older storyboards stay editable; owner found it stiff —
 *  presets now use one smooth eased move instead). */
function buildCam(a: Partial<CamKey>, b: Partial<CamKey>, d: number, hold: boolean, ease = 'inout'): CamKey[] {
  if (!hold) return [{ t: 0, ...a } as CamKey, { t: d, ...b, ease } as CamKey]
  return [{ t: 0, ...a } as CamKey, { t: round2(0.22 * d), ...a } as CamKey, { t: round2(0.55 * d), ...b, ease } as CamKey, { t: d, ...b } as CamKey]
}
const hasHold = (s: SbShot) => (s.camera?.length ?? 0) === 4

function camEnds(s: SbShot): [CamKey, CamKey] {
  const keys = s.camera?.length ? s.camera : [{ t: 0 }]
  const a = { x: 0.5, y: 0.5, zoom: 1, ...keys[0] }
  const b = { ...a, ...keys[keys.length - 1], ...(keys.length === 4 && keys[2].ease ? { ease: keys[2].ease } : {}) }   // held pan: glide key carries the easing
  return [a as CamKey, b as CamKey]
}

export default function ReelEditor({ id }: { id: string }) {
  const { message } = App.useApp()
  const [info, setInfo] = useState<ReelInfo | null>(null)
  const [item, setItem] = useState<Item | null>(null)
  const [sb, setSb] = useState<Storyboard | null>(null)
  const [saved, setSaved] = useState('')
  const [boxes, setBoxes] = useState<Box[]>([])
  const [boxesSaved, setBoxesSaved] = useState('')
  const [sel, setSel] = useState(0)
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [mode, setMode] = useState<'timing' | 'boxes'>('timing')
  const [jobId, setJobId] = useState<string | null>(null)
  const [video, setVideo] = useState(false)
  const { job, log } = useJob(jobId, j => { load(false); if (j.state === 'done') { message.success('Reel built'); setVideo(true) } else if (j.state === 'error') message.error(j.error ?? 'Build failed') })
  const dirty = !!sb && JSON.stringify(sb) !== saved
  const boxesDirty = JSON.stringify(boxes) !== boxesSaved

  const load = useCallback(async (resetSb = true) => {
    try {
      const [r, it] = await Promise.all([api.reel(id), api.piece('strip', id)])
      setInfo(r); setItem(it)
      if (resetSb) { setSb(r.storyboard); setSaved(JSON.stringify(r.storyboard)); setBoxes(r.boxes); setBoxesSaved(JSON.stringify(r.boxes)); setT(r.storyboard ? 0.8 : 0) }
    } catch (e) { message.error((e as Error).message) }
  }, [id, message])
  useEffect(() => { load() }, [load])
  useEffect(() => addLeaveGuard(() => dirty || boxesDirty), [dirty, boxesDirty])

  const change = (fn: (s: Storyboard) => void) => setSb(cur => { if (!cur) return cur; const n = clone(cur); fn(n); return n })
  const total = sb?.output.duration ?? (sb ? Math.max(...sb.shots.map(s => s.end)) : 0)
  const shot = sb?.shots[sel]

  const save = async () => {
    if (!sb) return
    try { await api.reelSave(id, sb); setSaved(JSON.stringify(sb)); message.success('Storyboard saved') } catch (e) { message.error((e as Error).message) }
  }
  const run = async (label: string, fn: () => Promise<void>) => { setBusy(label); try { await fn() } catch (e) { message.error((e as Error).message) } finally { setBusy(null) } }
  const makeStoryboard = () => run('Making the storyboard…', async () => {
    const r = await api.reelMakeStoryboard(id, info?.per ?? 3.6)
    setSb(r.storyboard); setSaved(JSON.stringify(r.storyboard)); setSel(0); setT(0.8); await load(false); message.success('New storyboard from the panel boxes')
  })
  const detect = () => run('Finding the panels…', async () => {
    const r = await api.reelDetect(id); setBoxes(r.boxes); setBoxesSaved(JSON.stringify(r.boxes)); message.success(`${r.boxes.length} panels found — fix the boxes if needed`)
  })
  const saveBoxes = () => run('Saving boxes and re-cutting the panels…', async () => {
    await api.reelSaveBoxes(id, boxes); setBoxesSaved(JSON.stringify(boxes))
    const r = await api.reelRecrop(id); setSb(r.storyboard); setSaved(JSON.stringify(r.storyboard)); await load(false)
    message.success('Boxes saved and panels re-cut')
  })
  const build = async () => {
    if (!sb) return
    try { const j = await api.reelBuild(id, sb); setSaved(JSON.stringify(sb)); setJobId(j.id) } catch (e) { message.error((e as Error).message) }
  }

  // ---------- preview (scripts/render.py, half size) ----------
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const urlRef = useRef<string | null>(null)
  const show = (b: Blob) => { const u = URL.createObjectURL(b); if (urlRef.current) URL.revokeObjectURL(urlRef.current); urlRef.current = u; setUrl(u) }
  useEffect(() => {
    if (!sb || playing) return
    const ac = new AbortController()
    const h = setTimeout(async () => {
      try { show(await api.reelStill(id, sb, t, 0.4, ac.signal)); setErr(null) } catch (e) { if ((e as Error).name !== 'AbortError') setErr((e as Error).message) }
    }, 60)
    return () => { clearTimeout(h); ac.abort() }
  }, [sb, t, playing, id])
  useEffect(() => {
    if (!playing || !sb) return
    let stop = false; const from = t >= total - 0.05 ? 0 : t; const t0 = performance.now()
    ;(async () => {
      let fails = 0
      while (!stop) {
        const tick = performance.now()
        const now = from + (tick - t0) / 1000
        if (now >= total) { setT(total - 0.01); break }
        try { show(await api.reelStill(id, sb, now, 0.3)); fails = 0 }
        catch { if (++fails > 8) break; await new Promise(r => setTimeout(r, 250)); continue }   // ride out a busy server / rate limit
        if (!stop) setT(now)
        const wait = 100 - (performance.now() - tick)                                          // ~10 frames/s: steady, stays under the limit
        if (wait > 0) await new Promise(r => setTimeout(r, wait))
      }
      if (!stop) setPlaying(false)
    })()
    return () => { stop = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (dirty) save(); return }
      if (tag === 'INPUT' || tag === 'TEXTAREA' || document.querySelector('.ant-modal-wrap, .ant-tour')) return
      if (e.code === 'Space') { e.preventDefault(); setPlaying(p => !p) }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); setT(x => clamp(round2(x + (e.shiftKey ? 1 : 0.1) * (e.key === 'ArrowLeft' ? -1 : 1)), 0, total - 0.01)) }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  })

  const { tour, button } = usePageTour('reel', [
    { title: 'Strip-reel editor', description: 'The silent reel shows your strip panel by panel and the whole strip at the end. Here you fix what the automatic build gets wrong.' },
    { target: 're-mode', title: 'Two modes', description: '"Panel boxes": draw/fix where each panel is on the strip. "Timing & camera": order, length, camera move and transition of every shot.' },
    { target: 're-preview', title: 'Preview', description: 'The real renderer at half size. Press Play (Space) or click the timeline to scrub.' },
    { target: 're-timeline', title: 'Timeline', description: 'One block per shot. Click to select; drag the right edge of a block to make it longer or shorter.' },
    { target: 're-inspector', title: 'Shot settings', description: 'Length, camera preset or exact start/end framing, easing and the transition into this shot.' },
    { target: 're-build', title: 'Build the reel', description: 'Saves, renders and makes the Instagram upload copy (upload/…_strip_reel.mp4). Needs the QA PASS.' },
  ], !!info)

  if (!info || !item) return <><PageHeader title="Strip-reel editor" /><div className="p-8"><Spin /></div></>
  if (!info.has_strip) return <><PageHeader title="Strip-reel editor" back={() => go(`/p/strip/${id}`)} />
    <Result status="info" title="This project has no strip.png yet" subTitle="Upload your strip (or pick a draft) in the Pictures tab first." extra={<Button type="primary" onClick={() => go(`/p/strip/${id}/pictures`)}>Go to Pictures</Button>} /></>
  const qaOk = item.status.qa === 'pass'
  const stripUrl = api.fileUrl('strip', id, 'strip.png', info.strip_mtime ?? 0)
  const imgUrl = (rel: string) => api.thumbUrl('strip', id, `strip_reel/${rel}`, 200, info.strip_mtime ?? 0)

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHeader title={<span>Strip-reel editor <span className="opacity-50 text-sm font-sans font-normal">· {item.headline} · {id}</span></span>}
        back={() => { if (canLeave()) go(`/p/strip/${id}/reel`) }}
        extra={<Space size={6}>
          <Segmented value={mode} onChange={v => setMode(v as 'timing' | 'boxes')} data-tour="re-mode"
            options={[{ value: 'timing', label: 'Timing & camera', icon: <VideoCameraOutlined /> }, { value: 'boxes', label: 'Panel boxes', icon: <BorderOutlined /> }]} />
          <Typography.Text type={dirty ? 'warning' : 'secondary'} className="text-xs">{dirty ? '● unsaved' : sb ? 'saved' : ''}</Typography.Text>
          <Tooltip title="Throw away unsaved changes"><Button icon={<UndoOutlined />} disabled={!dirty} onClick={() => { setSb(JSON.parse(saved)); }} /></Tooltip>
          <Tooltip title="Save the storyboard (⌘S)"><Button icon={<SaveOutlined />} disabled={!dirty} onClick={save}>Save</Button></Tooltip>
          <Tooltip title={qaOk ? 'Save, render and make the upload copy (~2 min)' : 'Needs the QA PASS for the current strip.png'}>
            <Button type="primary" icon={<ThunderboltOutlined />} disabled={!sb || !qaOk || job?.state === 'running'} onClick={build} data-tour="re-build">Build reel</Button></Tooltip>
          {button}
        </Space>} />
      {!qaOk && <Alert banner type="warning" message={<span>QA PASS missing for the current strip.png — you can edit and preview, but <b>Build reel</b> unlocks after the QA tab's <b>Mark PASS</b>.</span>} action={<Button size="small" onClick={() => go(`/p/strip/${id}/qa`)}>Open QA</Button>} />}
      {busy && <Alert banner type="info" message={<Space><Spin size="small" />{busy}</Space>} />}

      {mode === 'boxes' ? <BoxesEditor stripUrl={stripUrl} size={info.strip_size} boxes={boxes} setBoxes={setBoxes} source={info.boxes_source}
        dirty={boxesDirty} onDetect={detect} onSave={saveBoxes} onRevert={() => setBoxes(JSON.parse(boxesSaved))} /> :
        !sb ? <div className="flex-1 grid place-items-center">
          <Empty description={<span>No storyboard yet. It is made from the panel boxes{info.boxes.length ? ` (${info.boxes.length} panels)` : ' (found automatically)'}.</span>}>
            <Space><Button type="primary" onClick={makeStoryboard}>Make the storyboard</Button><Button onClick={() => setMode('boxes')}>Check the panel boxes first</Button></Space>
          </Empty></div> :
          <>
            <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,1fr)_380px]">
              <div className="min-h-0 p-4 flex flex-col items-center gap-2" data-tour="re-preview">
                <div className="relative flex-1 min-h-0 aspect-[9/16] rounded-xl overflow-hidden bg-black ring-1 ring-line shadow-2xl">
                  {url && <img src={url} className="w-full h-full object-cover" draggable={false} />}
                  {err && <div className="absolute inset-x-2 bottom-2 rounded bg-red-900/90 p-2 text-xs">{err}</div>}
                </div>
                <Space>
                  <Button type="primary" icon={playing ? <PauseOutlined /> : <CaretRightOutlined />} onClick={() => setPlaying(!playing)}>{playing ? 'Pause' : 'Play'}</Button>
                  <span className="font-mono text-sm opacity-70">{fmt(t)} / {fmt(total)}</span>
                  {job?.state === 'done' || info.upload.reel ? <Button icon={<VideoCameraOutlined />} onClick={() => setVideo(true)}>Watch the built reel</Button> : null}
                </Space>
              </div>
              <div className="border-l border-line bg-panel overflow-y-auto" data-tour="re-inspector">
                {job && <div className="p-3 border-b border-line"><JobPanel job={job} log={log} /></div>}
                <ReelSettings sb={sb} change={change} total={total} />
                {shot && <ShotInspector sb={sb} i={sel} change={change} setSel={setSel} imgUrl={imgUrl} setT={setT} />}
              </div>
            </div>
            <ShotTimeline sb={sb} sel={sel} setSel={i => { setSel(i); setT(sb.shots[i].start + 0.05) }} t={t} setT={setT} change={change} imgUrl={imgUrl} total={total} />
          </>}
      <Modal open={video} onCancel={() => setVideo(false)} footer={info.upload.reel && <Button icon={<DownloadOutlined />} href={api.rootUrl(info.upload.reel.path, true)}>Download</Button>} title="The built reel" destroyOnClose width={460}>
        {info.upload.reel ? <video src={api.rootUrl(info.upload.reel.path) + `?v=${Math.round(info.upload.reel.mtime)}`} controls autoPlay className="w-full rounded bg-black" /> : <Empty description="Not built yet." />}
      </Modal>
      {tour}
    </div>
  )
}

function ReelSettings({ sb, change, total }: { sb: Storyboard; change: (fn: (s: Storyboard) => void) => void; total: number }) {
  const [want, setWant] = useState<number | null>(null)
  const scaleTo = (len: number) => change(s => retime(s, shots => {
    const panels = shots.filter(isPanel), fixed = shots.filter(x => !isPanel(x)).reduce((a, x) => a + dur(x), 0)
    const cur = panels.reduce((a, x) => a + dur(x), 0), k = Math.max(0.1, (len - fixed) / Math.max(0.1, cur))
    for (const x of panels) { const d = dur(x); const nd = round2(Math.max(0.8, d * k)); x.camera?.forEach(c => { c.t = round2(c.t * nd / d) }); x.end = x.start + nd }
  }))
  const punch = (sb.events ?? []).some(e => e.type === 'shake')
  const lastPanel = [...sb.shots].reverse().find(isPanel)
  return (
    <div className="p-3 border-b border-line">
      <div className="label mb-2">Whole reel</div>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
        <span className="opacity-70">Length</span>
        <Space.Compact>
          <InputNumber size="small" min={3} max={90} step={0.5} value={want ?? round2(total)} onChange={v => setWant(v === null ? null : Number(v))} addonAfter="s" />
          <Tooltip title="Stretch or squeeze every panel to this total length (the end card keeps its length)"><Button size="small" disabled={!want || want === round2(total)} onClick={() => { if (want) scaleTo(want); setWant(null) }}>Fit</Button></Tooltip>
        </Space.Compact>
        <span className="opacity-70">Fade in / out</span>
        <Space>
          <InputNumber size="small" min={0} max={2} step={0.05} value={sb.output.fade_in ?? 0.1} onChange={v => change(s => { s.output.fade_in = Number(v ?? 0) })} />
          <InputNumber size="small" min={0} max={3} step={0.05} value={sb.output.fade_out ?? 0.6} onChange={v => change(s => { s.output.fade_out = Number(v ?? 0) })} />
        </Space>
        <span className="opacity-70">Punchline</span>
        <Checkbox checked={punch} onChange={e => change(s => {
          s.events = (s.events ?? []).filter(x => x.type !== 'shake')
          if (e.target.checked && lastPanel) { const lp = s.shots.find(x => x.id === lastPanel.id)!; s.events.push({ t: round2(lp.start + 0.15), type: 'shake', amp: 8, decay: 0.12 }) }
        })}><span className="text-xs opacity-80">shake when the last panel lands</span></Checkbox>
      </div>
    </div>
  )
}

function ShotInspector({ sb, i, change, setSel, imgUrl, setT }: { sb: Storyboard; i: number; change: (fn: (s: Storyboard) => void) => void; setSel: (i: number) => void; imgUrl: (r: string) => string; setT: (t: number) => void }) {
  const s = sb.shots[i]; const [a, b] = camEnds(s); const d = dur(s); const panel = isPanel(s)
  const panelIdx = sb.shots.filter(isPanel).findIndex(x => x.id === s.id)
  const nPanels = sb.shots.filter(isPanel).length
  const setCam = (which: 0 | 1, patch: Partial<CamKey>) => change(x => {
    const sh = x.shots[i]; const [ca, cb] = camEnds(sh)
    const na = which === 0 ? { ...ca, ...patch } : ca, nb = which === 1 ? { ...cb, ...patch } : cb
    sh.camera = buildCam({ x: na.x, y: na.y, zoom: na.zoom }, { x: nb.x, y: nb.y, zoom: nb.zoom }, dur(sh), hasHold(sh), cb.ease ?? 'inout')
  })
  const move = (dir: -1 | 1) => change(x => retime(x, shots => { const j = i + dir; [shots[i], shots[j]] = [shots[j], shots[i]] }))
  const camRow = (label: string, which: 0 | 1, c: CamKey) => (
    <div className="rounded-lg bg-panel2/60 p-2">
      <div className="flex items-center mb-1"><span className="label">{label}</span>
        <Tooltip title="Jump the preview here"><Button size="small" type="text" className="ml-auto" icon={<AimOutlined />} onClick={() => setT(which === 0 ? s.start + 0.02 : s.end - 0.05)} /></Tooltip></div>
      <div className="grid grid-cols-[74px_1fr_36px] gap-x-2 items-center text-xs">
        <span className="opacity-60">left↔right</span><Slider className="!my-1" min={0} max={1} step={0.01} value={c.x ?? 0.5} onChange={v => setCam(which, { x: v })} tooltip={{ open: false }} /><span className="font-mono">{(c.x ?? 0.5).toFixed(2)}</span>
        <span className="opacity-60">top↕bottom</span><Slider className="!my-1" min={0} max={1} step={0.01} value={c.y ?? 0.5} onChange={v => setCam(which, { y: v })} tooltip={{ open: false }} /><span className="font-mono">{(c.y ?? 0.5).toFixed(2)}</span>
        <span className="opacity-60">zoom</span><Slider className="!my-1" min={1} max={2.5} step={0.01} value={c.zoom ?? 1} onChange={v => setCam(which, { zoom: v })} tooltip={{ open: false }} /><span className="font-mono">{(c.zoom ?? 1).toFixed(2)}</span>
      </div>
    </div>
  )
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <img src={imgUrl(s.image)} className="w-14 h-14 object-cover rounded" />
        <div className="min-w-0">
          <div className="font-display font-extrabold text-lg leading-tight">{panel ? `Panel ${pnum(s)}` : 'End card (whole strip)'}<span className="text-xs opacity-50 font-sans font-normal ml-2">{panel ? `shot ${panelIdx + 1} of ${nPanels}` : ''}</span></div>
          <div className="text-xs opacity-60">{fmt(s.start)} → {fmt(s.end)} · {s.image}</div>
        </div>
        <Space.Compact className="ml-auto">
          <Tooltip title="Show earlier"><Button size="small" icon={<ArrowUpOutlined />} disabled={!panel || panelIdx === 0} onClick={() => { move(-1); setSel(i - 1) }} /></Tooltip>
          <Tooltip title="Show later"><Button size="small" icon={<ArrowDownOutlined />} disabled={!panel || panelIdx === nPanels - 1} onClick={() => { move(1); setSel(i + 1) }} /></Tooltip>
        </Space.Compact>
      </div>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
        <span className="opacity-70">Length</span>
        <InputNumber size="small" min={0.5} max={20} step={0.1} value={d} addonAfter="s" onChange={v => change(x => retime(x, shots => {
          const sh = shots[i], od = dur(sh), nd = Math.max(0.5, Number(v ?? od)); sh.camera?.forEach(c => { c.t = round2(c.t * nd / od) }); sh.end = sh.start + nd
        }))} />
        <span className="opacity-70">Transition in</span>
        <Space.Compact>
          <Select size="small" disabled={i === 0} value={i === 0 ? 'start' : s.transition_in?.type ?? 'cut'} style={{ width: 120 }}
            options={i === 0 ? [{ value: 'start', label: '(reel start)' }] : TRANSITIONS.map(x => ({ value: x, label: x }))}
            onChange={v => change(x => { x.shots[i].transition_in = { ...(x.shots[i].transition_in ?? {}), type: v, dur: x.shots[i].transition_in?.dur ?? 0.25 } })} />
          <InputNumber size="small" disabled={i === 0 || s.transition_in?.type === 'cut'} min={0.05} max={1.5} step={0.05} value={s.transition_in?.dur ?? 0.25} style={{ width: 80 }}
            onChange={v => change(x => { const tr = x.shots[i].transition_in; if (tr) tr.dur = Number(v ?? 0.25) })} />
        </Space.Compact>
        <span className="opacity-70">Card size</span>
        <Slider className="!my-1" min={0.6} max={1} step={0.01} value={s.card?.width ?? 0.98} onChange={v => change(x => { const c = x.shots[i].card; if (c) c.width = v })} />
      </div>
      <div>
        <div className="label mb-1">Camera move</div>
        <div className="flex flex-wrap gap-1 mb-2">
          {PRESETS.map(p => <Button key={p.key} size="small" onClick={() => change(x => {
            const sh = x.shots[i]; sh.camera = buildCam(p.a, p.b, dur(sh), !!p.hold)
          })}>{p.label}</Button>)}
        </div>
        <div className="flex flex-col gap-2">
          {camRow('Start framing', 0, a)}
          {camRow('End framing', 1, b)}
          <div className="flex items-center gap-2 text-xs"><span className="opacity-60">Easing</span>
            <Select size="small" value={b.ease ?? 'inout'} style={{ width: 110 }} options={EASES.map(e => ({ value: e, label: e }))}
              onChange={v => change(x => { const c = x.shots[i].camera; if (c?.length) c[c.length === 4 ? 2 : c.length - 1].ease = v })} /></div>
        </div>
        <Typography.Paragraph type="secondary" className="!text-[11px] !mt-2 !mb-0">zoom 1 = the whole panel fits the card; wide panels pan left → right so they read like a comic.</Typography.Paragraph>
      </div>
    </div>
  )
}

function ShotTimeline({ sb, sel, setSel, t, setT, change, imgUrl, total }: {
  sb: Storyboard; sel: number; setSel: (i: number) => void; t: number; setT: (t: number) => void
  change: (fn: (s: Storyboard) => void) => void; imgUrl: (r: string) => string; total: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ i: number; x0: number; d0: number } | null>(null)
  const scrubbing = useRef(false)
  const W = () => ref.current?.clientWidth ?? 1000
  const pps = () => W() / Math.max(1, total)
  const tAt = (clientX: number) => { const r = ref.current!.getBoundingClientRect(); return clamp((clientX - r.left) / r.width * total, 0, total - 0.01) }
  return (
    <div className="shrink-0 border-t border-line bg-panel px-4 pt-2 pb-3 select-none" data-tour="re-timeline">
      <div className="flex items-center gap-3 text-xs opacity-70 mb-1">
        <span className="label">Timeline</span><span>click a shot to edit it · drag its right edge to change its length · click the ruler to scrub</span>
        <span className="ml-auto font-mono">{fmt(total)}</span>
      </div>
      <div ref={ref} className="relative h-[92px]"
        onPointerMove={e => {
          if (scrubbing.current) { setT(tAt(e.clientX)); return }
          const d = drag.current; if (!d) return
          const nd = round2(Math.max(0.5, d.d0 + (e.clientX - d.x0) / pps()))
          change(x => retime(x, shots => { const sh = shots[d.i], od = dur(sh); sh.camera?.forEach(c => { c.t = round2(c.t * nd / od) }); sh.end = sh.start + nd }))
        }}
        onPointerUp={() => { drag.current = null; scrubbing.current = false }}>
        <div className="absolute inset-x-0 top-0 h-5 border-b border-line cursor-text"
          onPointerDown={e => { (e.target as Element).setPointerCapture(e.pointerId); scrubbing.current = true; setT(tAt(e.clientX)) }}>
          {Array.from({ length: Math.floor(total) + 1 }, (_, k) => <div key={k} className="absolute top-0 h-full border-l border-line/70 text-[10px] pl-0.5 opacity-60" style={{ left: `${100 * k / total}%` }}>{k % 2 === 0 ? `${k}s` : ''}</div>)}
        </div>
        {sb.shots.map((s, i) => (
          <div key={s.id + i} onClick={() => setSel(i)}
            className={`absolute top-6 bottom-0 rounded-md overflow-hidden cursor-pointer border-2 ${i === sel ? 'border-pink z-10' : 'border-transparent'} ${isPanel(s) ? 'bg-[#28232e]' : 'bg-[#3a2f20]'}`}
            style={{ left: `${100 * s.start / total}%`, width: `calc(${100 * dur(s) / total}% - 2px)` }}>
            <div className="absolute inset-0 bg-cover bg-center opacity-60" style={{ backgroundImage: `url(${imgUrl(s.image)})` }} />
            <div className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[11px]">{isPanel(s) ? `P${pnum(s)}` : 'end'} · {dur(s).toFixed(1)}s</div>
            {i > 0 && s.transition_in?.type && s.transition_in.type !== 'cut' && <div className="absolute left-1 bottom-1 text-[10px] bg-black/60 rounded px-1">{s.transition_in.type}</div>}
            <Tooltip title="Drag to change the length"><div className="absolute right-0 top-0 h-full w-2.5 cursor-ew-resize hover:bg-pink/50"
              onPointerDown={e => { e.stopPropagation(); (e.target as Element).setPointerCapture(e.pointerId); setSel(i); drag.current = { i, x0: e.clientX, d0: dur(s) } }} /></Tooltip>
          </div>
        ))}
        {(sb.events ?? []).filter(e => e.type === 'shake').map((e, k) => <div key={k} title="punchline shake" className="absolute top-5 text-[10px] text-sun pointer-events-none" style={{ left: `${100 * e.t / total}%` }}>⚡</div>)}
        <div className="absolute top-0 bottom-0 w-px bg-sun pointer-events-none z-20" style={{ left: `${100 * t / total}%` }}><div className="absolute -left-[5px] top-0 size-[11px] rotate-45 bg-sun" /></div>
      </div>
    </div>
  )
}

/** Panel boxes over strip.png: drag a box to move it, drag its corner dots to resize, + to add, ✕ to remove. Saved to layout/layout_actual.json. */
function BoxesEditor({ stripUrl, size, boxes, setBoxes, source, dirty, onDetect, onSave, onRevert }: {
  stripUrl: string; size: [number, number] | null; boxes: Box[]; setBoxes: (b: Box[]) => void; source: string | null
  dirty: boolean; onDetect: () => void; onSave: () => void; onRevert: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [selB, setSelB] = useState<number | null>(null)
  const drag = useRef<{ i: number; mode: 'move' | 'nw' | 'ne' | 'sw' | 'se'; x0: number; y0: number; b0: Box } | null>(null)
  const rel = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height] }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const [x, y] = rel(e); const dx = x - d.x0, dy = y - d.y0; let [x0, y0, x1, y1] = d.b0
    if (d.mode === 'move') { const w = x1 - x0, h = y1 - y0; x0 = clamp(x0 + dx, 0, 1 - w); y0 = clamp(y0 + dy, 0, 1 - h); x1 = x0 + w; y1 = y0 + h }
    else {
      if (d.mode.includes('w')) x0 = clamp(x0 + dx, 0, x1 - 0.04); if (d.mode.includes('e')) x1 = clamp(x1 + dx, x0 + 0.04, 1)
      if (d.mode.includes('n')) y0 = clamp(y0 + dy, 0, y1 - 0.04); if (d.mode.includes('s')) y1 = clamp(y1 + dy, y0 + 0.04, 1)
    }
    const nb = [...boxes]; nb[d.i] = [x0, y0, x1, y1].map(v => Math.round(v * 10000) / 10000) as Box; setBoxes(nb)
  }
  const start = (e: React.PointerEvent, i: number, mode: 'move' | 'nw' | 'ne' | 'sw' | 'se') => {
    e.stopPropagation(); (e.target as Element).setPointerCapture(e.pointerId); setSelB(i); const [x, y] = rel(e); drag.current = { i, mode, x0: x, y0: y, b0: boxes[i] }
  }
  const aspect = size ? size[0] / size[1] : 0.8
  return (
    <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-h-0 p-4 flex justify-center overflow-auto">
        <div ref={ref} className="relative h-full max-h-full select-none" style={{ aspectRatio: String(aspect) }} onPointerMove={onMove} onPointerUp={() => { drag.current = null }}>
          <img src={stripUrl} className="w-full h-full object-contain rounded" draggable={false} />
          {boxes.map((b, i) => (
            <div key={i} className={`absolute border-[3px] cursor-move ${selB === i ? 'border-pink bg-pink/10' : 'border-sun bg-sun/5'}`}
              style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%` }}
              onPointerDown={e => start(e, i, 'move')}>
              <div className={`absolute left-1 top-1 rounded-full size-7 grid place-items-center font-bold text-ink ${selB === i ? 'bg-pink' : 'bg-sun'}`}>{i + 1}</div>
              {(['nw', 'ne', 'sw', 'se'] as const).map(c => <div key={c} onPointerDown={e => start(e, i, c)}
                className="absolute size-3.5 rounded-full bg-white border-2 border-ink"
                style={{ left: c.includes('w') ? -8 : undefined, right: c.includes('e') ? -8 : undefined, top: c.includes('n') ? -8 : undefined, bottom: c.includes('s') ? -8 : undefined, cursor: c === 'nw' || c === 'se' ? 'nwse-resize' : 'nesw-resize' }} />)}
            </div>
          ))}
        </div>
      </div>
      <div className="border-l border-line bg-panel p-3 overflow-y-auto flex flex-col gap-3">
        <Card size="small" title="Panel boxes">
          <Typography.Paragraph type="secondary" className="text-xs">Each box is one panel of the reel, numbered in reading order. Drag a box to move it, drag its white dots to resize. {source === 'wireframe' ? 'These come from the layout wireframe — press Find panels to fit them to the real drawing.' : source === 'actual' ? 'Saved in layout/layout_actual.json.' : ''}</Typography.Paragraph>
          <Space wrap>
            <Popconfirm title="Find the panels again automatically?" description="Your box changes are replaced." onConfirm={onDetect}><Button icon={<ScissorOutlined />}>Find panels</Button></Popconfirm>
            <Button icon={<PlusOutlined />} onClick={() => { setBoxes([...boxes, [0.3, 0.4, 0.7, 0.6]]); setSelB(boxes.length) }}>Add box</Button>
          </Space>
        </Card>
        <Card size="small" title={`${boxes.length} panels`}>
          {boxes.map((b, i) => <div key={i} className={`flex items-center gap-2 py-1 text-xs rounded px-1 ${selB === i ? 'bg-[#2a2431]' : ''}`} onClick={() => setSelB(i)}>
            <Tag color={selB === i ? 'magenta' : 'gold'}>{i + 1}</Tag>
            <span className="font-mono opacity-70">{b.map(v => v.toFixed(2)).join(' ')}</span>
            <Space.Compact className="ml-auto">
              <Button size="small" icon={<ArrowUpOutlined />} disabled={i === 0} onClick={() => { const n = [...boxes]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setBoxes(n); setSelB(i - 1) }} />
              <Button size="small" icon={<ArrowDownOutlined />} disabled={i === boxes.length - 1} onClick={() => { const n = [...boxes]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; setBoxes(n); setSelB(i + 1) }} />
              <Button size="small" danger icon={<DeleteOutlined />} disabled={boxes.length < 2} onClick={() => { setBoxes(boxes.filter((_, k) => k !== i)); setSelB(null) }} />
            </Space.Compact>
          </div>)}
        </Card>
        <Space direction="vertical" className="w-full">
          <Button type="primary" block disabled={!dirty} onClick={onSave} icon={<SaveOutlined />}>Save boxes & re-cut the panels</Button>
          <Button block disabled={!dirty} onClick={onRevert} icon={<UndoOutlined />}>Undo box changes</Button>
          <Typography.Text type="secondary" className="text-xs">Same number of panels → your timing and camera edits are kept. A different number → a fresh storyboard is made.</Typography.Text>
        </Space>
      </div>
    </div>
  )
}
