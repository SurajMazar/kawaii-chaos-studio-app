import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Typography } from 'antd'
import { PauseOutlined, CaretRightOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { fmt, videoEnd } from '../lib'

/** 9:16 preview. Scrubbing renders the exact frame at the playhead; Play shows a small video made by the real renderer
 *  (same code as the final video), rendered in the background and synced to the song — so what you see is what you get. */
export default function Preview() {
  const pid = useStore(s => s.pid)
  const edit = useStore(s => s.edit)
  const playhead = useStore(s => s.playhead)
  const playing = useStore(s => s.playing)
  const setPlaying = useStore(s => s.setPlaying)
  const setPlayhead = useStore(s => s.setPlayhead)
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [safe, setSafe] = useState(() => localStorage.getItem('ls.safe') === '1')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)

  const show = (b: Blob) => {
    const u = URL.createObjectURL(b)
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = u; setUrl(u)
  }

  // song element (only for listening while editing — it is never baked into the video unless you ask)
  const audioPath = edit?.audio ?? null
  useEffect(() => {
    audioRef.current?.pause()
    audioRef.current = pid && audioPath ? new Audio(api.fileUrl('mv', pid, audioPath)) : null
  }, [pid, audioPath])

  // scrub: render the frame at the playhead (debounced, older requests cancelled)
  useEffect(() => {
    if (!pid || !edit || playing) return
    const ac = new AbortController()
    const id = setTimeout(async () => {
      setBusy(true)
      try { show(await api.still(pid, edit, playhead - edit.start, 0.5, ac.signal)); setErr(null) }
      catch (e) { if ((e as Error).name !== 'AbortError') setErr((e as Error).message) }
      finally { setBusy(false) }
    }, 50)
    return () => { clearTimeout(id); ac.abort() }
  }, [pid, edit, playhead, playing])

  // Smooth playback (owner 2026-10-25: frame streaming paused itself): the server renders a small real video of this
  // exact edit in the background (shortly after you stop editing), Play shows it at full frame rate and keeps the song
  // in sync. Scrubbing / paused still shows the exact frame above.
  const editJson = edit ? JSON.stringify(edit) : ''
  const [pb, setPb] = useState<{ json: string; state: string; progress: number; url?: string; error?: string } | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const pbFor = (json: string) => pb && pb.json === json ? pb : null

  // ask for (and poll) the playback video of the current edit
  const ensurePlayback = async (json: string, signal: { stop: boolean }) => {
    if (!pid) return
    for (let i = 0; i < 600 && !signal.stop; i++) {
      try {
        const r = await api.playback(pid, JSON.parse(json))
        if (signal.stop) return
        setPb({ json, state: r.state, progress: r.progress, url: r.url, error: r.error })
        if (r.state === 'ready' || r.state === 'error') return
      } catch (e) { if (!signal.stop) setPb({ json, state: 'error', progress: 0, error: (e as Error).message }); return }
      await new Promise(res => setTimeout(res, 700))
    }
  }

  // pre-render 1.5 s after the last edit so Play is usually instant
  useEffect(() => {
    if (!pid || !editJson || playing) return
    const sig = { stop: false }
    const id = setTimeout(() => { if (!pbFor(editJson) || pbFor(editJson)!.state === 'error') ensurePlayback(editJson, sig) }, 1500)
    return () => { clearTimeout(id); sig.stop = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, editJson, playing])

  // play / pause
  useEffect(() => {
    if (!playing || !pid || !edit) return
    const sig = { stop: false }
    // always poll until ready: the pre-render's own poll is cancelled when Play is pressed, so a render that is still
    // running must be watched from here or the overlay would freeze at its last percentage
    if (pbFor(editJson)?.state !== 'ready') ensurePlayback(editJson, sig)
    return () => { sig.stop = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])

  const ready = playing && pbFor(editJson)?.state === 'ready' ? pbFor(editJson)!.url : undefined
  useEffect(() => {
    const v = videoRef.current
    if (!ready || !v || !edit) return
    const end = videoEnd(edit)
    const from = playhead >= end - 0.05 ? edit.start : playhead
    const audio = audioRef.current
    let raf = 0, lastUi = 0, stopped = false
    const start = async () => {
      v.currentTime = Math.max(0, from - edit.start)
      if (audio) { audio.currentTime = Math.max(0, from); audio.play().catch(() => {}) }
      try { await v.play() } catch { /* autoplay blocked: user can press Play again */ }
      const tick = (now: number) => {
        if (stopped) return
        // the song is the clock when there is one; the video follows it (drift > 80 ms gets corrected)
        if (audio && !audio.paused) {
          const want = audio.currentTime - edit.start
          if (Math.abs(v.currentTime - want) > 0.08) v.currentTime = Math.max(0, want)
        }
        const t = edit.start + v.currentTime
        if (now - lastUi > 66) { setPlayhead(t); lastUi = now }          // ~15 UI updates/s is plenty for the timeline
        if (v.ended || t >= end - 0.02) { setPlayhead(end); setPlaying(false); return }
        raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
    }
    start()
    return () => { stopped = true; cancelAnimationFrame(raf); v.pause(); audio?.pause(); setPlayhead(edit.start + v.currentTime) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready])

  const cpb = pbFor(editJson)
  const preparing = playing && !ready && cpb?.state !== 'error'

  if (!edit) return null
  const vt = playhead - edit.start
  const cur = edit.lines.find(l => l.start <= playhead && playhead < l.end)

  return (
    <div className="flex flex-col items-center gap-2 h-full min-h-0">
      <div className="relative h-full min-h-0 aspect-[9/16] rounded-xl overflow-hidden bg-black shadow-2xl ring-1 ring-line">
        {url && <img src={url} className="w-full h-full object-cover select-none" draggable={false} />}
        {ready && <video ref={videoRef} src={ready} muted playsInline preload="auto" className="absolute inset-0 w-full h-full object-cover bg-black" />}
        {preparing && <div className="absolute inset-0 grid place-items-center bg-black/55 text-center p-4">
          <div><div className="text-sm font-medium">Preparing smooth preview…</div>
            <div className="text-xs opacity-70 mt-1">{cpb?.state === 'queued' ? 'waiting for another preview to finish' : `${Math.round((cpb?.progress ?? 0) * 100)}%`} · plays at full speed with the song</div></div>
        </div>}
        {playing && cpb?.state === 'error' && <div className="absolute inset-x-2 bottom-2 rounded bg-red-900/90 p-2 text-xs">Could not make the preview: {cpb.error}</div>}
        {safe && <>
          <div className="absolute inset-x-0 top-0 h-[11%] bg-red-500/15 border-b border-dashed border-red-400/60" />
          <div className="absolute inset-x-0 bottom-0 h-[22%] bg-red-500/15 border-t border-dashed border-red-400/60" />
          <div className="absolute right-0 bottom-[22%] w-[14%] h-[38%] bg-red-500/15 border-l border-dashed border-red-400/60" />
          <div className="absolute left-2 bottom-2 text-[10px] text-red-200/80">Instagram UI covers the red areas</div>
        </>}
        {busy && !playing && <div className="absolute top-2 right-2 size-2 rounded-full bg-sun animate-pulse" />}
        {err && <div className="absolute inset-x-2 bottom-2 rounded bg-red-900/90 p-2 text-xs">{err}</div>}
      </div>
      <div className="flex flex-wrap justify-center items-center gap-x-2 gap-y-1 text-sm">
        <Button type="primary" className="w-24" icon={playing ? <PauseOutlined /> : <CaretRightOutlined />} onClick={() => setPlaying(!playing)}>{playing ? 'Pause' : 'Play'}</Button>
        <span className="font-mono tabular-nums text-muted">{fmt(Math.max(0, vt))} / {fmt(videoEnd(edit) - edit.start)}</span>
        <span className="text-muted">·</span>
        <span className="font-mono tabular-nums text-muted" title="song time">song {fmt(playhead)}</span>
        {!playing && cpb?.state === 'ready' && <span className="text-xs text-muted" title="Play is instant: the preview video is ready">● ready</span>}
        {!playing && (cpb?.state === 'rendering' || cpb?.state === 'queued') && <span className="text-xs text-muted">preparing preview {Math.round((cpb?.progress ?? 0) * 100)}%</span>}
        <Checkbox className="!ml-2" checked={safe} onChange={e => { setSafe(e.target.checked); localStorage.setItem('ls.safe', e.target.checked ? '1' : '0') }}><span className="text-xs opacity-70">IG safe zones</span></Checkbox>
      </div>
      {!audioPath && <Typography.Text type="secondary" className="text-xs">Tip: add your song under <b>Song</b> (right panel) to hear it while you edit — it is not put into the video.</Typography.Text>}
      {cur && <div className="text-xs text-muted max-w-full truncate">♪ {cur.text.replace(/\*/g, '').replace(/\s*\/\s*/g, ' · ')}</div>}
    </div>
  )
}
