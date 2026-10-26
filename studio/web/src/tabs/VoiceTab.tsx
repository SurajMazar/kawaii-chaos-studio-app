import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App, AutoComplete, Button, Card, Col, Collapse, Empty, Input, InputNumber, Popconfirm, Result, Row, Select, Slider, Space, Switch, Tag, Tooltip, Typography, Upload } from 'antd'
import {
  AimOutlined, CaretRightOutlined, CustomerServiceOutlined, DeleteOutlined, DownloadOutlined, ExportOutlined, FileTextOutlined, PauseOutlined,
  PlusOutlined, SoundOutlined, ThunderboltOutlined, UploadOutlined,
} from '@ant-design/icons'
import { api } from '../api'
import { useCan } from '../auth'
import { JobPanel, useJob } from '../components/Jobs'
import { usePageTour } from '../components/Tours'
import VoiceCastDrawer from '../components/VoiceCast'
import type { TabProps } from '../pages/PiecePage'
import type { VoiceCast, VoiceLine, VoiceoverConfig, VoiceoverInfo } from '../types'

const COLORS = ['#ff7eb6', '#7cc4ff', '#ffd84d', '#9be38f', '#c9a2ff', '#ffab70', '#6fe0d2']
const dbVol = (db: number) => Math.min(1, Math.pow(10, db / 20))
const newId = (lines: VoiceLine[]) => { let n = lines.length + 1; while (lines.some(l => l.id === `l${n}`)) n++; return `l${n}` }

/** Voiced strip reel: lines (ElevenLabs or uploaded clips) placed on the silent reel, music ducked under them, one mix. */
export default function VoiceTab({ id, item, goTab }: TabProps) {
  const { message, modal } = App.useApp()
  const canEdit = useCan('editor')
  const [info, setInfo] = useState<VoiceoverInfo | null>(null)
  const [cfg, setCfg] = useState<VoiceoverConfig | null>(null)
  const [cast, setCast] = useState<VoiceCast | null>(null)
  const [castOpen, setCastOpen] = useState(false)
  const [credits, setCredits] = useState<{ used?: number; limit?: number } | null>(null)
  const [saving, setSaving] = useState<'idle' | 'dirty' | 'saving' | 'saved'>('idle')
  const [busyLine, setBusyLine] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [now, setNow] = useState(0)
  const [previewing, setPreviewing] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const stopRef = useRef<() => void>(() => {})
  const { job, log } = useJob(jobId, j => { load(); if (j.state === 'done') message.success('Voiced reel ready'); if (j.state === 'error') message.error(j.error ?? 'Mix failed') })
  const running = !!job && (job.state === 'running' || job.state === 'queued')

  const load = async () => {
    try { const r = await api.voiceover(id); setInfo(r); setCfg(c => c && saving === 'dirty' ? c : r.config) } catch (e) { message.error((e as Error).message) }
  }
  useEffect(() => {
    load(); api.cast().then(setCast).catch(() => {})
    api.jobs(true).then(js => { const r = js.find(j => j.ref === `strip/${id}` && j.kind === 'voiceover'); if (r) setJobId(r.id) }).catch(() => {})
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => stopRef.current(), [])           // stop the preview when leaving the tab
  useEffect(() => { if (info?.eleven) api.voiceStatus(true).then(s => setCredits(s.subscription)).catch(() => {}) }, [info?.eleven])

  // autosave shortly after the last change
  useEffect(() => {
    if (!cfg || saving !== 'dirty' || !canEdit) return
    const t = setTimeout(async () => {
      setSaving('saving')
      try { await api.saveVoiceover(id, cfg); setSaving('saved') } catch (e) { setSaving('dirty'); message.error((e as Error).message) }
    }, 700)
    return () => clearTimeout(t)
  }, [cfg, saving]) // eslint-disable-line react-hooks/exhaustive-deps
  const change = (f: (c: VoiceoverConfig) => VoiceoverConfig) => { setCfg(c => c && f(c)); setSaving('dirty') }
  const setLine = (lid: string, patch: Partial<VoiceLine>) => change(c => ({ ...c, lines: c.lines.map(l => l.id === lid ? { ...l, ...patch } : l) }))

  const clipDur = useMemo(() => Object.fromEntries((info?.clips ?? []).map(c => [c.name, c.duration ?? 0])), [info])
  const castBy = (name: string) => cast?.characters.find(c => c.name.toLowerCase() === (name || '').toLowerCase())
  const colorOf = useMemo(() => { const names = [...new Set((cfg?.lines ?? []).map(l => l.character || '?'))]; return (n: string) => COLORS[Math.max(0, names.indexOf(n || '?')) % COLORS.length] }, [cfg])
  const D = info?.video?.duration ?? 18
  const fileUrl = (name: string) => api.fileUrl('strip', id, `voiceover/${name}`, info?.clips.find(c => c.name === name)?.mtime)
  const rootOrProject = (p: string, bust?: number) => (p.startsWith('upload/') ? api.rootUrl(p) : api.fileUrl('strip', id, p.replace(`projects/${id}/`, ''))) + (bust ? `${p.startsWith('upload/') ? '?' : '&'}v=${Math.round(bust)}` : '')

  const { tour, button } = usePageTour('voice', [
    { title: 'Voiced reel', description: 'An extra version of the strip reel with character voices (ElevenLabs) and soft music. The silent reel stays as it is.' },
    { target: 'vo-cast', title: 'Voice cast', description: 'Which ElevenLabs voice each character uses — a character keeps the same voice in every reel. Shared by every project.' },
    { target: 'vo-lines', title: 'Lines', description: 'One row per spoken line: who says it, the words, and when (seconds into the reel). Make the voice with ElevenLabs, or upload a clip you made on their website. Every take is kept.' },
    { target: 'vo-preview', title: 'Preview and mix', description: 'Preview plays the reel with the clips at their times right here. Mix makes the final video with the music ducked under the voices.' },
  ], !!info)

  if (!item.status.reel) return <Result status="info" title="Build the silent strip reel first" subTitle="The voices are placed on the finished strip reel." extra={<Button type="primary" onClick={() => goTab('reel')}>Go to Reel</Button>} />
  if (!info || !cfg) return <Card loading />

  // ---------------- actions ----------------
  const addLine = (patch: Partial<VoiceLine> = {}) => change(c => ({ ...c, lines: [...c.lines, { id: newId(c.lines), character: '', text: '', at: Math.round(now * 100) / 100, clip: '', gain_db: 0, takes: [], ...patch }] }))
  const fillFromScript = () => {
    const s = info.suggestions
    if (!s.length) { message.info('No dialogue found in the script (lines like  Stark: "Take my scarf."  or  Caption: "…").'); return }
    change(c => { let ls = [...c.lines]; for (const x of s) ls = [...ls, { id: newId(ls), character: x.character, text: x.text, at: x.at, clip: '', gain_db: 0, takes: [] }]; return { ...c, lines: ls } })
    message.success(`Added ${s.length} line${s.length > 1 ? 's' : ''} from the script — check the times`)
  }
  const generate = (l: VoiceLine) => {
    const who = castBy(l.character); const vid = l.voice_id || who?.voice_id
    if (!vid) { message.warning(`Give ${l.character || 'this character'} a voice in the Voice cast first.`); setCastOpen(true); return }
    if (!l.text.trim()) { message.warning('Write the line first.'); return }
    modal.confirm({
      title: `Make ${l.character || 'this line'}'s voice?`, okText: 'Make it',
      content: <div><Typography.Paragraph>“{l.text}” with <b>{who?.voice_name || vid}</b> ({cfg.model}).</Typography.Paragraph>
        <Typography.Text type="secondary">Uses about {l.text.length} ElevenLabs credits{credits?.limit ? ` (${(credits.limit - (credits.used ?? 0)).toLocaleString()} left)` : ''}. The new take is added; older takes stay.</Typography.Text></div>,
      onOk: async () => {
        setBusyLine(l.id)
        try {
          const r = await api.generateLine(id, { text: l.text, voice_id: vid, character: l.character, model: cfg.model })
          setLine(l.id, { clip: r.name, takes: [...new Set([...(l.takes ?? []), r.name])] }); await load()
          api.voiceStatus(true).then(s => setCredits(s.subscription)).catch(() => {})
          message.success(`New take: ${r.name}`); new Audio(fileUrl(r.name)).play().catch(() => {})
        } catch (e) { message.error((e as Error).message) } finally { setBusyLine(null) }
      },
    })
  }
  const uploadFor = async (f: File, lid?: string) => {
    try {
      const r = await api.uploadVoiceClip(id, f); await load()
      if (lid) { const l = cfg.lines.find(x => x.id === lid); setLine(lid, { clip: r.name, takes: [...new Set([...(l?.takes ?? []), r.name])] }) }
      message.success(`Added ${r.name}`)
    } catch (e) { message.error((e as Error).message) }
    return false
  }
  const mix = async () => { try { setJobId((await api.mixVoiceover(id, cfg)).id); setSaving('saved') } catch (e) { message.error((e as Error).message) } }

  // in-page preview: the silent reel + the clips started at their times (no ducking — Mix does that)
  const preview = () => {
    const v = videoRef.current; if (!v) return
    if (previewing) { stopRef.current(); return }
    const voices = cfg.lines.filter(l => l.clip).map(l => ({ l, a: new Audio(fileUrl(l.clip)), on: false }))
    const music = cfg.music.file ? new Audio(fileUrl(cfg.music.file)) : null
    const base = dbVol(cfg.music.gain_db + 6)
    let raf = 0
    const stop = () => { cancelAnimationFrame(raf); v.pause(); voices.forEach(x => x.a.pause()); music?.pause(); setPreviewing(false) }
    stopRef.current = stop
    v.muted = true; v.currentTime = 0
    if (music) { music.currentTime = cfg.music.start; music.volume = base; music.play().catch(() => {}) }
    v.play().then(() => {
      setPreviewing(true)
      const tick = () => {
        const t = v.currentTime; setNow(t)
        let talking = false
        for (const x of voices) {
          if (!x.on && t >= x.l.at) { x.on = true; x.a.currentTime = Math.max(0, t - x.l.at); x.a.volume = dbVol(x.l.gain_db); x.a.play().catch(() => {}) }
          if (x.on && !x.a.paused && !x.a.ended) talking = true
        }
        if (music) music.volume = talking && cfg.music.duck ? base * 0.35 : base
        if (v.ended) { stop(); return }
        raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
    }).catch(() => message.error('The browser blocked playback — click Preview again.'))
  }
  const charOptions = [...new Set([...(cast?.characters.map(c => c.name) ?? []), ...cfg.lines.map(l => l.character).filter(Boolean), 'Narrator'])].map(v => ({ value: v }))
  const clipOptions = (l: VoiceLine) => [...new Set([...(l.takes ?? []), ...(l.clip ? [l.clip] : [])])].map(n => ({ value: n, label: `${n}${clipDur[n] ? ` · ${clipDur[n].toFixed(1)} s` : ''}` }))
  const allClips = info.clips.map(c => ({ value: c.name, label: `${c.name}${c.duration ? ` · ${c.duration.toFixed(1)} s` : ''}` }))
  const out = info.output
  const lines = [...cfg.lines].sort((a, b) => a.at - b.at)
  const overlaps = new Set(lines.flatMap((l, i) => i && l.clip && lines[i - 1].clip && lines[i - 1].at + (clipDur[lines[i - 1].clip] ?? 0) > l.at + 0.05 ? [l.id, lines[i - 1].id] : []))

  return (
    <Row gutter={16}>
      <Col xs={24} xl={14} className="flex flex-col gap-3">
        <Card size="small" title={<span><SoundOutlined /> Voiced reel</span>} extra={<Space>
          {saving === 'saving' ? <Tag>saving…</Tag> : saving === 'saved' ? <Tag color="green">saved</Tag> : saving === 'dirty' ? <Tag color="orange">unsaved</Tag> : null}
          <Button icon={<CustomerServiceOutlined />} onClick={() => setCastOpen(true)} data-tour="vo-cast">Voice cast</Button>{button}
        </Space>}>
          <Typography.Paragraph type="secondary" className="!mb-2">An extra version of the strip reel with voices: <code>{info.output_path}</code>. The silent reel is not changed.</Typography.Paragraph>
          {!info.eleven && <Alert type="info" showIcon className="!mb-2" message="ElevenLabs is not connected — upload clips you made on elevenlabs.io, or ask an admin to add the API key (Settings → Integrations)." />}
          {info.eleven && credits?.limit != null && <Typography.Text type="secondary" className="text-xs">ElevenLabs credits: {(credits.used ?? 0).toLocaleString()} / {credits.limit.toLocaleString()} used</Typography.Text>}
        </Card>

        <Card size="small" title="Lines" data-tour="vo-lines" extra={canEdit && <Space>
          <Tooltip title="Captions and dialogue from the Script tab, placed on their panels"><Button size="small" icon={<FileTextOutlined />} onClick={fillFromScript}>From the script</Button></Tooltip>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => addLine()}>Add a line</Button>
        </Space>}>
          {!lines.length ? <Empty description="No lines yet. Add one, or take them from the script." /> : <div className="flex flex-col gap-2">
            {lines.map(l => {
              const who = castBy(l.character)
              return (
                <div key={l.id} className="rounded-lg border border-line p-2 grid grid-cols-[6px_minmax(0,1fr)] gap-2">
                  <div className="rounded" style={{ background: colorOf(l.character) }} />
                  <div className="flex flex-col gap-2 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <AutoComplete className="!w-40" value={l.character} options={charOptions} disabled={!canEdit} placeholder="Character"
                        filterOption={(i, o) => !!o?.value.toLowerCase().includes(i.toLowerCase())} onChange={v => setLine(l.id, { character: v })} />
                      {l.character && (who?.voice_id ? <Tooltip title={`${who.voice_name} (ready for Make voice)`}><Tag color="green" className="!m-0">{who.voice_name.split(/\s[–-]\s/)[0] || 'voice'} ✓</Tag></Tooltip>
                        : who?.voice_name ? <Tooltip title={`${who.voice_name} — choose it in the Voice cast to link the ElevenLabs voice id`}><Tag color="gold" className="!m-0 cursor-pointer" onClick={() => setCastOpen(true)}>{who.voice_name.split(/\s[–-]\s/)[0]} · link</Tag></Tooltip>
                          : <Tooltip title="No voice for this character yet (Voice cast)"><Tag color="orange" className="!m-0 cursor-pointer" onClick={() => setCastOpen(true)}>no voice</Tag></Tooltip>)}
                      <Space.Compact>
                        <InputNumber className="!w-28" addonBefore="at" value={l.at} min={0} max={D} step={0.05} precision={2} disabled={!canEdit} onChange={v => setLine(l.id, { at: v ?? 0 })} />
                        <Tooltip title="Use the player's current time"><Button icon={<AimOutlined />} disabled={!canEdit} onClick={() => setLine(l.id, { at: Math.round(now * 100) / 100 })} /></Tooltip>
                      </Space.Compact>
                      <Tooltip title="Volume of this line (dB)"><InputNumber className="!w-24" value={l.gain_db} min={-30} max={12} step={1} addonAfter="dB" disabled={!canEdit} onChange={v => setLine(l.id, { gain_db: v ?? 0 })} /></Tooltip>
                      {overlaps.has(l.id) && <Tag color="red" className="!m-0">overlaps</Tag>}
                      <div className="flex-1" />
                      {canEdit && <Popconfirm title="Remove this line?" description="Its clips stay in voiceover/." onConfirm={() => change(c => ({ ...c, lines: c.lines.filter(x => x.id !== l.id) }))}>
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} /></Popconfirm>}
                    </div>
                    <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={l.text} disabled={!canEdit} placeholder={'What they say. Eleven v3 understands tags like "[deadpan] …I\'m also cold."'}
                      onChange={e => setLine(l.id, { text: e.target.value })} />
                    <div className="flex flex-wrap items-center gap-2">
                      <Select className="min-w-[220px] flex-1" value={l.clip || undefined} placeholder="no voice clip yet" options={clipOptions(l).length ? clipOptions(l) : allClips} disabled={!canEdit}
                        onChange={v => setLine(l.id, { clip: v, takes: [...new Set([...(l.takes ?? []), v])] })} allowClear onClear={() => setLine(l.id, { clip: '' })}
                        popupRender={menu => <>{menu}{allClips.length > clipOptions(l).length && <div className="px-2 py-1 text-xs opacity-60">Other clips in voiceover/: {allClips.filter(c => !clipOptions(l).some(o => o.value === c.value)).map(c => c.value).join(', ')}</div>}</>} />
                      {l.clip && <Tooltip title="Listen"><Button icon={<CaretRightOutlined />} onClick={() => { const a = new Audio(fileUrl(l.clip)); a.volume = dbVol(l.gain_db); a.play().catch(() => {}) }} /></Tooltip>}
                      {canEdit && <Tooltip title={info.eleven ? 'Make this line with ElevenLabs (a new take)' : 'Connect ElevenLabs in Settings → Integrations'}>
                        <Button type="primary" ghost icon={<ThunderboltOutlined />} loading={busyLine === l.id} disabled={!info.eleven} onClick={() => generate(l)}>Make voice</Button></Tooltip>}
                      {canEdit && <Upload accept=".mp3,.wav,.m4a,.ogg,.flac,.aac" showUploadList={false} beforeUpload={f => uploadFor(f, l.id)}>
                        <Tooltip title="Upload a clip (e.g. downloaded from elevenlabs.io)"><Button icon={<UploadOutlined />} /></Tooltip></Upload>}
                    </div>
                  </div>
                </div>)
            })}
          </div>}
        </Card>

        <Collapse size="small" items={[{ key: 'm', label: <span>Music & loudness {cfg.music.file ? <Tag className="!ml-2">{cfg.music.file}</Tag> : <Tag className="!ml-2">no music</Tag>}</span>, children: <div className="flex flex-col gap-3">
          <Space wrap>
            <Select className="!w-72" allowClear placeholder="Music file in voiceover/" value={cfg.music.file || undefined} options={allClips} disabled={!canEdit}
              onChange={v => change(c => ({ ...c, music: { ...c.music, file: v ?? '' } }))} />
            {canEdit && <Upload accept=".mp3,.wav,.m4a,.ogg,.flac,.aac" showUploadList={false} beforeUpload={f => uploadFor(f)}><Button icon={<UploadOutlined />}>Upload music</Button></Upload>}
          </Space>
          <div className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-x-3 gap-y-1">
            <span>Music volume</span><Slider min={-30} max={0} value={cfg.music.gain_db} disabled={!canEdit} tooltip={{ formatter: v => `${v} dB` }} onChange={v => change(c => ({ ...c, music: { ...c.music, gain_db: v } }))} />
            <span>Starts at</span><InputNumber className="!w-32" min={0} step={0.5} value={cfg.music.start} addonAfter="s into song" disabled={!canEdit} onChange={v => change(c => ({ ...c, music: { ...c.music, start: v ?? 0 } }))} />
            <span>Fade in / out</span><Space><InputNumber min={0} max={10} step={0.1} value={cfg.music.fade_in} addonAfter="s" disabled={!canEdit} onChange={v => change(c => ({ ...c, music: { ...c.music, fade_in: v ?? 0 } }))} />
              <InputNumber min={0} max={10} step={0.1} value={cfg.music.fade_out} addonAfter="s" disabled={!canEdit} onChange={v => change(c => ({ ...c, music: { ...c.music, fade_out: v ?? 0 } }))} /></Space>
            <span>Duck under voices</span><Switch checked={cfg.music.duck} disabled={!canEdit} onChange={v => change(c => ({ ...c, music: { ...c.music, duck: v } }))} />
            <span>Loudness</span><InputNumber className="!w-32" min={-30} max={-8} value={cfg.loudness} addonAfter="LUFS" disabled={!canEdit} onChange={v => change(c => ({ ...c, loudness: v ?? -16 }))} />
          </div>
          <Typography.Text type="secondary" className="text-xs">Only use music you made or are allowed to use (e.g. ElevenLabs Music). Licensed songs go in through the Instagram app.</Typography.Text>
        </div> }]} />
        {info.readme && <Collapse size="small" items={[{ key: 'r', label: 'Notes (voiceover/README.md)', children: <pre className="whitespace-pre-wrap text-xs m-0">{info.readme}</pre> }]} />}
      </Col>

      <Col xs={24} xl={10} className="flex flex-col gap-3">
        <Card size="small" title="Preview" data-tour="vo-preview">
          {info.video ? <>
            <video ref={videoRef} src={rootOrProject(info.video.path, info.video.mtime)} playsInline className="rounded-lg bg-black w-full max-h-[52vh] object-contain"
              onTimeUpdate={e => { if (!previewing) setNow(e.currentTarget.currentTime) }} controls={!previewing} />
            <div className="relative h-14 mt-2 rounded bg-black/30 cursor-pointer select-none" onClick={e => {
              const r = e.currentTarget.getBoundingClientRect(); const t = ((e.clientX - r.left) / r.width) * D
              if (videoRef.current && !previewing) videoRef.current.currentTime = t; setNow(t)
            }}>
              {lines.map((l, i) => <Tooltip key={l.id} title={`${l.character || '?'} · ${l.at.toFixed(2)} s · ${l.text}`}>
                <div className="absolute h-5 rounded text-[10px] leading-5 px-1 overflow-hidden whitespace-nowrap text-black"
                  style={{ left: `${(l.at / D) * 100}%`, width: `${Math.max(1.5, ((clipDur[l.clip] || 1.2) / D) * 100)}%`, top: 4 + (i % 2) * 24, background: colorOf(l.character), opacity: l.clip ? 1 : 0.45 }}>{l.character}</div>
              </Tooltip>)}
              <div className="absolute top-0 bottom-0 w-px bg-white" style={{ left: `${(now / D) * 100}%` }} />
            </div>
            <div className="flex justify-between text-xs opacity-60 mt-1"><span>{now.toFixed(2)} s</span><span>{D.toFixed(1)} s</span></div>
            <Space className="mt-2" wrap>
              <Button icon={previewing ? <PauseOutlined /> : <CaretRightOutlined />} onClick={preview} disabled={!lines.some(l => l.clip)}>{previewing ? 'Stop' : 'Preview with voices'}</Button>
              {canEdit && <Tooltip title="Mix voices + music onto the reel (a few seconds)"><Button type="primary" icon={<SoundOutlined />} loading={running} onClick={mix}>Mix voiced reel</Button></Tooltip>}
            </Space>
          </> : <Empty description={`The silent reel is missing: ${info.video_path}`} />}
          {job && <div className="mt-3"><JobPanel job={job} log={log} /></div>}
        </Card>
        <Card size="small" title="Voiced reel">
          {out ? <>
            <video key={out.mtime} src={api.rootUrl(out.path) + `?v=${Math.round(out.mtime)}`} controls playsInline className="rounded-lg bg-black w-full max-h-[52vh] object-contain" />
            <Space className="mt-2" wrap>
              <span className="text-xs opacity-60">{(out.size / 1e6).toFixed(1)} MB · {new Date(out.mtime * 1000).toLocaleString()}</span>
              <Button size="small" icon={<DownloadOutlined />} href={api.rootUrl(out.path, true)}>Download</Button>
              <Button size="small" icon={<ExportOutlined />} onClick={async () => { try { message.success(`Copied to ${(await api.exportFile(out.path)).path}`) } catch (e) { message.error((e as Error).message) } }}>Export</Button>
            </Space>
          </> : <Empty description="Press “Mix voiced reel” to make it." />}
        </Card>
      </Col>
      <VoiceCastDrawer open={castOpen} onClose={() => setCastOpen(false)} cast={cast} onSaved={setCast} eleven={info.eleven} />
      {tour}
    </Row>
  )
}
