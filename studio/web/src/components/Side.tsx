import { useEffect, useState } from 'react'
import { Button, Checkbox, ColorPicker, Input, InputNumber, Popconfirm, Progress, Select, Slider, Tooltip, Typography, Upload } from 'antd'
import { AimOutlined, DownloadOutlined, PlayCircleOutlined, UploadOutlined, FontSizeOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useStore } from '../store'
import { fmt, lastLineEnd, parseTime, round2 } from '../lib'

function Section({ title, children, right, tip }: { title: string; children: React.ReactNode; right?: React.ReactNode; tip?: string }) {
  return (
    <div className="border-b border-line p-3">
      <div className="flex items-center mb-2">{tip ? <Tooltip title={tip}><span className="label cursor-help">{title}</span></Tooltip> : <span className="label">{title}</span>}<div className="ml-auto">{right}</div></div>
      {children}
    </div>
  )
}

const DEF_FONTS: Record<string, string> = { verse: 'fonts/Gaegu-Bold.ttf', heavy: 'fonts/Baloo2.ttf', marker: 'fonts/PermanentMarker.ttf', script: 'fonts/CaveatBrush.ttf' }
const FONT_ROLES: { k: 'verse' | 'heavy' | 'marker' | 'script'; label: string; tip: string }[] = [
  { k: 'heavy', label: 'block / chorus', tip: 'BIG block words and chorus caps' },
  { k: 'verse', label: 'verse', tip: 'cute hand-lettering lines' },
  { k: 'marker', label: '*big* words', tip: 'emphasis words in Stack/Verse lines' },
  { k: 'script', label: 'end card', tip: 'the signature on the black end card' },
]
const DEF_PALETTE = ['#FFD84D', '#FFFFFF', '#F0445E']

export default function Side() {
  const pid = useStore(s => s.pid)!
  const edit = useStore(s => s.edit)!
  const media = useStore(s => s.media)
  const job = useStore(s => s.job)
  const playhead = useStore(s => s.playhead)
  const sel = useStore(s => s.sel)
  const { change, startRender, cancelRender, reloadMedia, notify } = useStore.getState()
  const [bake, setBake] = useState(false)
  const [drag, setDrag] = useState(false)
  const [video, setVideo] = useState<string | null>(null)
  const [fonts, setFonts] = useState<{ name: string; path: string }[]>([])
  const running = job && (job.state === 'queued' || job.state === 'running')
  useEffect(() => { api.fonts().then(setFonts).catch(() => {}) }, [])

  const upload = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      try {
        const isAudio = /\.(mp3|m4a|wav|aac|ogg|flac)$/i.test(f.name)
        const r = await api.upload('mv', pid, f, isAudio ? 'audio' : 'edit_frames')
        if (isAudio) change(e => { e.audio = r.path })
        notify(`Added ${r.path}`)
      } catch (e) { notify(String((e as Error).message)) }
    }
    await reloadMedia()
  }
  const timeField = (label: string, value: number, set: (v: number) => void, tip: string) => (
    <>
      <Tooltip title={tip}><span className="label cursor-help">{label}</span></Tooltip>
      <div className="flex gap-1">
        <Input key={value} size="small" className="!w-[86px] font-mono" defaultValue={fmt(value)}
          onBlur={e => { const v = parseTime(e.target.value); if (v !== null) set(round2(v)) }}
          onPressEnter={e => (e.target as HTMLInputElement).blur()} />
        <Tooltip title="Set to the playhead"><Button size="small" icon={<AimOutlined />} onClick={() => set(round2(playhead))} /></Tooltip>
      </div>
    </>
  )
  const latest = [...(media?.videos ?? [])].sort((a, b) => b.mtime - a.mtime)
  const palette = edit.palette ?? DEF_PALETTE
  const fontOpts = fonts.map(f => ({ value: f.path, label: f.name.replace(/\.(ttf|otf|ttc)$/i, '') }))
  const fontOf = (k: string) => {
    const v = edit.fonts?.[k as 'verse'] ?? DEF_FONTS[k]
    return v.includes('/fonts/') ? 'fonts/' + v.split('/fonts/')[1] : v
  }

  return (
    <div className="flex flex-col overflow-y-auto min-h-0 h-full"
      onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
      onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}>

      <Section title="Render">
        <div className="flex gap-2">
          <Tooltip title="540×960, 15 fps — a quick check in about 10 s"><Button className="flex-1" style={{ background: '#ffd84d', color: '#1d1606', borderColor: '#ffd84d' }} disabled={!!running} onClick={() => startRender('preview', bake)}>Quick preview</Button></Tooltip>
          <Tooltip title="1080×1920, 30 fps — saves first"><Button type="primary" className="flex-1" disabled={!!running} onClick={() => startRender('final', bake)}>Final video</Button></Tooltip>
        </div>
        <Checkbox className="!mt-2 !text-xs" checked={bake} onChange={e => setBake(e.target.checked)} disabled={!edit.audio}>
          <span className="text-xs opacity-70">put the song into the mp4 <i>(leave off: add the song in the Instagram app — copyrighted audio in the file can get the reel muted)</i></span>
        </Checkbox>
        {job && <div className="mt-2">
          <div className="flex text-xs mb-1"><span>{job.quality === 'final' ? 'Final video' : 'Quick preview'} · {job.state === 'running' ? 'rendering' : job.state}</span></div>
          <Progress size="small" percent={Math.round(100 * job.done / Math.max(1, job.total))} status={job.state === 'error' ? 'exception' : job.state === 'done' ? 'success' : 'active'} />
          {running && <Popconfirm title="Stop rendering?" onConfirm={cancelRender}><Button size="small" danger>Stop</Button></Popconfirm>}
          {job.error && <Typography.Text type="danger" className="text-xs">{job.error}</Typography.Text>}
        </div>}
        {latest.length > 0 && <div className="mt-2 flex flex-col gap-1">
          {latest.slice(0, 4).map(v => (
            <div key={v.path} className="flex items-center gap-2 text-xs">
              <Button size="small" icon={<PlayCircleOutlined />} onClick={() => setVideo(video === v.path ? null : v.path)}>{video === v.path ? 'hide' : ''}</Button>
              <span className="truncate">{v.path}</span>
              <span className="text-muted ml-auto">{(v.size / 1e6).toFixed(1)} MB</span>
              <Tooltip title="Download"><Button size="small" icon={<DownloadOutlined />} href={api.downloadUrl('mv', pid, v.path)} /></Tooltip>
            </div>
          ))}
          {video && <video key={video} src={api.fileUrl('mv', pid, video, Date.now())} controls autoPlay className="mt-1 w-full rounded-lg max-h-[360px] bg-black" />}
          <Typography.Text type="secondary" className="!text-[11px]">Saved in music_videos/{pid}/</Typography.Text>
        </div>}
      </Section>

      <Section title="Video">
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
          {timeField('starts at', edit.start, v => change(e => { e.start = v }), 'Song second where the video starts')}
          {timeField('lyrics end', lastLineEnd(edit), v => change(e => { e.end = v }), 'Song second where the last lyric ends (the end card follows)')}
          <span className="label">picture</span>
          <Select size="small" value={edit.fit ?? 'extend'} onChange={v => change(x => { x.fit = v })}
            options={[{ value: 'cover', label: 'fill the screen' }, { value: 'extend', label: 'full width + paper on top' }]} />
          <Tooltip title="Text on the black card at the end (empty = no end card)"><span className="label cursor-help">end card</span></Tooltip>
          <Input size="small" value={edit.signature ?? ''} placeholder="(no end card)" onChange={e => change(x => { x.signature = e.target.value || undefined }, 'sig')} />
          <span className="label">card secs</span>
          <InputNumber size="small" step={0.1} min={0} value={edit.signature_seconds ?? 1.6} onChange={v => change(x => { x.signature_seconds = Number(v ?? 1.6) }, 'sigs')} />
          <span className="label">big words</span>
          <Slider className="!m-0" min={90} max={240} value={edit.block_big ?? 165} onChange={v => change(x => { x.block_big = v }, 'bb')} />
          <span className="label">small rows</span>
          <Slider className="!m-0" min={40} max={130} value={edit.block_small ?? 82} onChange={v => change(x => { x.block_small = v }, 'bs')} />
        </div>
        <Button size="small" className="!mt-2" onClick={() => change(e => { const y = e.lines[sel]?.y; e.lines.forEach(l => { l.y = y }) })}>Use line {sel + 1}'s height for every line</Button>
      </Section>

      <Section title="Fonts & colours" tip="Your own look: pick fonts (upload more in Settings) and colours for this edit"
        right={<Tooltip title="Back to the house look"><Button size="small" onClick={() => change(e => { delete e.fonts; delete e.palette; delete e.accent; delete e.ink; delete e.block_fill })}>reset</Button></Tooltip>}>
        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-sm">
          {FONT_ROLES.map(r => <div key={r.k} className="contents">
            <Tooltip title={r.tip}><span className="label cursor-help whitespace-nowrap">{r.label}</span></Tooltip>
            <Select size="small" showSearch value={fontOf(r.k)} options={fontOpts} suffixIcon={<FontSizeOutlined />} popupMatchSelectWidth={false}
              optionRender={o => <div className="flex items-center gap-2"><img src={api.fontSample(String(o.value), 'Aa Kawaii')} className="h-5" /><span className="text-xs opacity-60">{o.label}</span></div>}
              onChange={v => change(e => { e.fonts = { ...(e.fonts ?? {}), [r.k]: v } })} />
          </div>)}
          <Tooltip title="Fill colour of Block words"><span className="label cursor-help">block text</span></Tooltip>
          <ColorPicker size="small" showText disabledAlpha value={edit.block_fill ?? '#FFFFFF'} onChangeComplete={c => change(e => { e.block_fill = c.toHexString().toUpperCase() })} />
          <Tooltip title="Chorus words cycle through these colours"><span className="label cursor-help">chorus</span></Tooltip>
          <div className="flex gap-1">{palette.map((p, k) => <ColorPicker key={k} size="small" disabledAlpha value={p}
            onChangeComplete={c => change(e => { const pl = [...(e.palette ?? DEF_PALETTE)]; pl[k] = c.toHexString().toUpperCase(); e.palette = pl })} />)}</div>
          <Tooltip title="Colour of *big* marker words"><span className="label cursor-help">accent</span></Tooltip>
          <ColorPicker size="small" showText disabledAlpha value={edit.accent ?? '#F0445E'} onChangeComplete={c => change(e => { e.accent = c.toHexString().toUpperCase() })} />
          <Tooltip title="Outline / shadow and verse text colour"><span className="label cursor-help">ink</span></Tooltip>
          <ColorPicker size="small" showText disabledAlpha value={edit.ink ?? '#2E2228'} onChangeComplete={c => change(e => { e.ink = c.toHexString().toUpperCase() })} />
        </div>
      </Section>

      <Section title="Song (for listening & timing)">
        <Select size="small" className="w-full" value={edit.audio ?? ''} onChange={v => change(x => { x.audio = v || null })}
          options={[{ value: '', label: '(none)' }, ...(media?.audio ?? []).map(a => ({ value: a.path, label: a.path }))]} />
        <Upload accept="audio/*" showUploadList={false} beforeUpload={f => { upload([f]); return false }}>
          <Button size="small" className="!mt-2" icon={<UploadOutlined />}>Add a song file…</Button>
        </Upload>
        <Typography.Paragraph type="secondary" className="!text-[11px] !mt-1 !mb-0">It stays on this computer. Play it with the preview and tap <span className="kbd">T</span> on each lyric to time it.</Typography.Paragraph>
      </Section>

      <Section title="Pictures" right={<Upload accept="image/*" multiple showUploadList={false} beforeUpload={(f, list) => { if (f === list[list.length - 1]) upload(list); return false }}>
        <Button size="small" icon={<UploadOutlined />}>Add</Button></Upload>}>
        {(media?.images.length ?? 0) === 0 && <Typography.Text type="secondary" className="text-xs">No pictures yet — drop your own pictures here.</Typography.Text>}
        <div className={`grid grid-cols-3 gap-1.5 rounded-lg ${drag ? 'ring-2 ring-pink' : ''}`}>
          {media?.images.map(m => (
            <Tooltip key={m.path} title={`${m.path} — click: use for line ${sel + 1}`}>
              <div className="relative group"
                onClick={() => change(e => { const L = e.lines[sel]; const s = L.shots ?? []; if (!s.length) s.push({}); s[0].image = m.path; L.shots = s; delete L.image })}>
                <img src={api.thumbUrl('mv', pid, m.path, 240, m.mtime)} className="w-full rounded cursor-pointer hover:ring-2 hover:ring-pink" draggable={false} />
                <div className="absolute bottom-0 inset-x-0 text-[10px] bg-black/60 px-1 truncate">{m.path.replace('edit_frames/', '')}</div>
              </div>
            </Tooltip>
          ))}
        </div>
        <Typography.Text type="secondary" className="!text-[11px]">Click a picture to use it for the selected line. Drop pictures or a song anywhere in this panel to add them.</Typography.Text>
      </Section>
    </div>
  )
}
