import { useState } from 'react'
import { Checkbox, Input, InputNumber, Modal, Typography } from 'antd'
import { useStore } from '../store'
import { fmt, parseLrc, round2 } from '../lib'

/** Paste an .lrc → line times (and optionally the text). Lines are matched in order; extra LRC rows add lines. */
export default function LrcImport({ onClose }: { onClose: () => void }) {
  const edit = useStore(s => s.edit)!
  const { change, notify } = useStore.getState()
  const [src, setSrc] = useState('')
  const [useText, setUseText] = useState(false)
  const [setStart, setSetStart] = useState(true)
  const [lastLen, setLastLen] = useState(3.5)
  const rows = parseLrc(src)

  const apply = () => {
    if (!rows.length) return
    change(e => {
      const template = e.lines[e.lines.length - 1]
      rows.forEach((r, i) => {
        const end = i + 1 < rows.length ? rows[i + 1].t : r.t + lastLen
        let l = e.lines[i]
        if (!l) { l = JSON.parse(JSON.stringify({ ...template, shots: undefined, image: undefined })); e.lines.push(l) }
        l.start = round2(r.t); l.end = round2(end)
        if (useText && r.text) l.text = r.text
        l.shots?.forEach(s => { if (s.at !== undefined && (s.at <= l.start || s.at >= l.end)) delete s.at })
      })
      if (setStart) e.start = round2(rows[0].t)
      if (rows.length >= e.lines.length) e.end = round2(rows[rows.length - 1].t + lastLen)   // LRC covers every line
      else if (e.end != null) e.end = Math.max(e.end, ...e.lines.map(l => l.end))
    })
    notify(`Timed ${rows.length} lines from the LRC`); onClose()
  }

  return (
    <Modal open onCancel={onClose} onOk={apply} okText={`Apply ${rows.length || ''} timings`} okButtonProps={{ disabled: !rows.length }} width={640}
      title="Import LRC timings">
      <Typography.Paragraph type="secondary">Paste lines like <code>[00:25.47]…</code>. Each LRC row becomes one lyric line, in order.</Typography.Paragraph>
      <Input.TextArea className="font-mono !text-xs" rows={8} placeholder={'[00:25.47]...\n[00:29.51]...'} value={src} onChange={e => setSrc(e.target.value)} autoFocus />
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm mt-3 items-center">
        <Checkbox checked={useText} onChange={e => setUseText(e.target.checked)}>also use the LRC text</Checkbox>
        <Checkbox checked={setStart} onChange={e => setSetStart(e.target.checked)}>video starts at the first line</Checkbox>
        <span>last line lasts <InputNumber size="small" step={0.1} value={lastLen} onChange={v => setLastLen(Number(v ?? 3.5))} /> s</span>
      </div>
      <div className="mt-3 max-h-32 overflow-y-auto text-xs font-mono opacity-60">
        {rows.map((r, i) => <div key={i}>{i + 1}. {fmt(r.t)} {i < edit.lines.length ? `→ line ${i + 1}` : '→ new line'}</div>)}
      </div>
    </Modal>
  )
}
