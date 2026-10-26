import { useEffect, useState } from 'react'
import { App, Button, Divider, Drawer, Grid, Input, Modal, Select, Space, Tooltip, Typography } from 'antd'
import { CopyOutlined, ImportOutlined, RedoOutlined, SaveOutlined, UndoOutlined, QuestionOutlined, SettingOutlined } from '@ant-design/icons'
import { useDirty, useStore } from '../store'
import { clamp, round2, videoEnd } from '../lib'
import Preview from '../components/Preview'
import Timeline from '../components/Timeline'
import { LineEditor, LineList } from '../components/Lines'
import Side from '../components/Side'
import LrcImport from '../components/LrcImport'
import { api } from '../api'
import { addLeaveGuard, canLeave, go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import type { LyricProject } from '../types'

const SHORTCUTS: [string, string][] = [
  ['Space', 'play / pause'], ['T', 'tap: selected line starts NOW (previous ends), go to next line'],
  ['[  ]', 'set selected line start / end to the playhead'], ['← →', 'move playhead 0.1 s (Shift: 1 s)'],
  ['↑ ↓', 'select previous / next line'], ['⌘S', 'save'], ['⌘Z  ⇧⌘Z', 'undo / redo'], ['?', 'show these shortcuts'],
]

export default function LyricEditor({ pid, file }: { pid: string; file?: string }) {
  const { message } = App.useApp()
  const edit = useStore(s => s.edit)
  const curPid = useStore(s => s.pid)
  const curFile = useStore(s => s.file)
  const toast = useStore(s => s.toast)
  const past = useStore(s => s.past.length)
  const future = useStore(s => s.future.length)
  const dirty = useDirty()
  const [projects, setProjects] = useState<LyricProject[]>([])
  const [lrc, setLrc] = useState(false)
  const [help, setHelp] = useState(false)
  const [copyOpen, setCopyOpen] = useState(false)
  const [sideOpen, setSideOpen] = useState(false)
  const bp = Grid.useBreakpoint()
  const wide = bp.xl !== false, phone = bp.md === false      // ≥1200: 4 columns · 768–1199: 3 + drawer · <768: one column
  const [copyName, setCopyName] = useState('lyric_edit_v2.json')
  const [err, setErr] = useState<string | null>(null)
  const S = useStore.getState

  useEffect(() => {
    api.lyricProjects(true).then(setProjects).catch(() => {})
    const f = file ?? 'lyric_edit.json'
    S().open(pid, f).then(() => setErr(null)).catch(e => setErr(String(e.message ?? e)))
  }, [pid, file, S])
  useEffect(() => { if (toast) message.info(toast) }, [toast, message])
  useEffect(() => addLeaveGuard(() => { const s = useStore.getState(); return !!s.edit && JSON.stringify(s.edit) !== s.savedJson }), [])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { const s = useStore.getState(); if (s.edit && JSON.stringify(s.edit) !== s.savedJson) e.preventDefault() }
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const st = useStore.getState(); if (!st.edit) return
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); st.save(); return }
      const tag = (e.target as HTMLElement).tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target as HTMLElement).isContentEditable
      if (mod && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); if (e.shiftKey) st.redo(); else st.undo(); return }
      if (typing || mod || document.querySelector('.ant-modal-wrap, .ant-tour')) return
      const ph = st.playhead, ed = st.edit, i = st.sel
      if (e.code === 'Space') { e.preventDefault(); st.setPlaying(!st.playing) }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault(); const d = (e.shiftKey ? 1 : 0.1) * (e.key === 'ArrowLeft' ? -1 : 1)
        st.setPlayhead(clamp(round2(ph + d), ed.start - 2, videoEnd(ed) + 2))
      }
      else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault(); const n = clamp(i + (e.key === 'ArrowUp' ? -1 : 1), 0, ed.lines.length - 1)
        st.setSel(n); if (!st.playing) st.setPlayhead(ed.lines[n].start + 0.01)
      }
      else if (e.key === '[') st.updateLine(i, { start: round2(ph) })
      else if (e.key === ']') st.updateLine(i, { end: round2(ph) })
      else if (e.key.toLowerCase() === 't') {
        const t = round2(ph)
        st.change(x => {
          const L = x.lines[i], dur = L.end - L.start
          L.start = t; if (L.end <= t + 0.1) L.end = round2(t + Math.max(dur, 1))
          if (i > 0) x.lines[i - 1].end = t
        }, `tap${i}`)
        if (i < ed.lines.length - 1) st.setSel(i + 1)
        st.notify(`Line ${i + 1} → ${t.toFixed(2)} s`)
      }
      else if (e.key === '?') setHelp(h => !h)
    }
    // buttons drop focus after a click, so Space / T always reach the shortcuts (a focused button would eat Space)
    const blur = () => { const a = document.activeElement as HTMLElement | null; if (a && (a.tagName === 'BUTTON' || (a as HTMLInputElement).type === 'checkbox' || a.getAttribute('role') === 'slider')) a.blur() }
    window.addEventListener('keydown', onKey); window.addEventListener('mouseup', blur)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('mouseup', blur) }
  }, [])

  const ready = !!edit && curPid === pid
  const { tour, button } = usePageTour('lyric', [
    { title: 'Lyric editor', description: 'Make a lyric-edit reel: words on your pictures, timed to the song. What you see in the preview is exactly what the final video will look like.' },
    { target: 'ly-lines', title: 'Lyrics', description: 'Every line with its time. Click one to edit it. "+ line" adds a line at the playhead.', placement: 'right' },
    { target: 'ly-editor', title: 'Line editor', description: 'Times, text (use / for a new row and *word* for a BIG word), the look, and the pictures & cuts for this line.', placement: 'right' },
    { target: 'ly-preview', title: 'Preview', description: 'The real frame. Press Play (or Space) to watch it with your song.', placement: 'left' },
    { target: 'ly-side', title: 'Render, song, pictures & look', description: 'Quick preview (fast) or Final video, add your song and pictures, pick fonts and colours, and set the end-card text.', placement: 'left' },
    { target: 'ly-timeline', title: 'Timeline', description: 'Drag lyrics to move them, drag their edges to retime. Ctrl/⌘ + wheel zooms. Tip: select line 1, press Space and tap T as each lyric starts.', placement: 'top' },
    { target: 'ly-save', title: 'Save', description: 'Saves the edit (⌘S). Older versions are kept in .studio_history/, so you can always go back.' },
  ], ready)

  if (err) return <><PageHeader title="Lyric editor" back={() => go('/music')} /><div className="p-8"><Typography.Text type="danger">Could not open this lyric edit: {err}</Typography.Text><br /><Button className="mt-3" onClick={() => go('/music')}>Back to music videos</Button></div></>
  if (!ready) return <><PageHeader title="Lyric editor" /><div className="p-8 opacity-60">Loading…</div></>
  const proj = projects.find(p => p.id === pid)
  const switchTo = (p: string, f?: string) => { if (!canLeave()) return; go(`/lyric/${p}/${f ?? projects.find(x => x.id === p)?.files[0] ?? 'lyric_edit.json'}`) }

  return (
    <div className={`h-full grid ${phone ? 'grid-rows-[auto_1fr_200px]' : 'grid-rows-[auto_1fr_250px]'} grid-cols-[minmax(0,1fr)] overflow-hidden`}>
      <PageHeader title={<span className="whitespace-nowrap">Lyric editor</span>}
        back={() => { if (canLeave()) go('/music') }}
        extra={<Space size={6} wrap className="justify-end">
          <Select size="middle" value={pid} style={{ width: wide ? 190 : 160 }} onChange={v => switchTo(v)} options={projects.filter(p => p.files.length).map(p => ({ value: p.id, label: p.id }))} />
          <Select value={curFile} style={{ width: wide ? 170 : 150 }} onChange={v => switchTo(pid, v)} options={(proj?.files ?? [curFile]).map(f => ({ value: f, label: f }))} />
          <Tooltip title="Make a copy of this edit to try ideas"><Button icon={<CopyOutlined />} onClick={() => setCopyOpen(true)}>Copy</Button></Tooltip>
          <Divider type="vertical" />
          <Tooltip title="Undo (⌘Z)"><Button icon={<UndoOutlined />} disabled={!past} onClick={() => S().undo()} /></Tooltip>
          <Tooltip title="Redo (⇧⌘Z)"><Button icon={<RedoOutlined />} disabled={!future} onClick={() => S().redo()} /></Tooltip>
          <Tooltip title="Import LRC: paste [mm:ss.xx] timings from an .lrc file"><Button icon={<ImportOutlined />} onClick={() => setLrc(true)}><span className="hidden 2xl:inline">Import LRC</span><span className="2xl:hidden">LRC</span></Button></Tooltip>
          <Typography.Text type={dirty ? 'warning' : 'secondary'} className="text-xs w-16 text-right whitespace-nowrap">{dirty ? '● unsaved' : 'saved'}</Typography.Text>
          <Button type="primary" icon={<SaveOutlined />} disabled={!dirty} onClick={() => S().save()} data-tour="ly-save">Save</Button>
          {!wide && <Button icon={<SettingOutlined />} onClick={() => setSideOpen(true)}>Render & look</Button>}
          <Tooltip title="Keyboard shortcuts (?)"><Button icon={<QuestionOutlined />} onClick={() => setHelp(true)} /></Tooltip>
          {button}
        </Space>} />

      {phone ? (
        <main className="min-h-0 overflow-y-auto">
          <section className="h-[62vh] p-3" data-tour="ly-preview"><Preview /></section>
          <section className="bg-panel/60 border-y border-line flex flex-col" data-tour="ly-editor"><LineEditor /></section>
          <aside className="bg-panel h-[50vh]" data-tour="ly-lines"><LineList /></aside>
        </main>
      ) : (
        <main className={`grid ${wide ? 'grid-cols-[230px_310px_minmax(0,1fr)_300px] 2xl:grid-cols-[280px_360px_minmax(0,1fr)_340px]' : 'grid-cols-[210px_290px_minmax(0,1fr)]'} min-h-0 min-w-0`}>
          <aside className="bg-panel border-r border-line min-h-0" data-tour="ly-lines"><LineList /></aside>
          <section className="bg-panel/60 border-r border-line min-h-0 flex flex-col" data-tour="ly-editor"><LineEditor /></section>
          <section className="min-h-0 p-4" data-tour="ly-preview"><Preview /></section>
          {wide && <aside className="bg-panel border-l border-line min-h-0" data-tour="ly-side"><Side /></aside>}
        </main>
      )}
      {!wide && <Drawer open={sideOpen} onClose={() => setSideOpen(false)} title="Render & look" width={Math.min(380, window.innerWidth - 24)}
        styles={{ body: { padding: 0 } }}><div className="h-full" data-tour="ly-side"><Side /></div></Drawer>}

      <div data-tour="ly-timeline" className="min-h-0"><Timeline /></div>

      {lrc && <LrcImport onClose={() => setLrc(false)} />}
      <Modal open={help} onCancel={() => setHelp(false)} footer={null} title="Keyboard shortcuts" width={440}>
        {SHORTCUTS.map(([k, v]) => <div key={k} className="flex gap-3 text-sm py-1"><span className="kbd w-20 text-center">{k}</span><span className="opacity-80">{v}</span></div>)}
        <Typography.Paragraph type="secondary" className="!mt-3 text-xs">Timing a song fast: add the song, select line 1, press Space, then tap <span className="kbd">T</span> as each lyric begins.</Typography.Paragraph>
      </Modal>
      <Modal open={copyOpen} title="Copy this edit" okText="Make the copy" onCancel={() => setCopyOpen(false)}
        onOk={async () => {
          try { await api.copy(pid, curFile, copyName); setCopyOpen(false); message.success(`Made ${copyName}`); setProjects(await api.lyricProjects(true)); go(`/lyric/${pid}/${copyName}`) }
          catch (e) { message.error((e as Error).message) }
        }}>
        <Typography.Paragraph type="secondary">A copy lets you try ideas without touching <b>{curFile}</b>. The name must start with <code>lyric_edit</code> and end with <code>.json</code>.</Typography.Paragraph>
        <Input value={copyName} onChange={e => setCopyName(e.target.value)} />
      </Modal>
      {tour}
    </div>
  )
}
