import { useEffect, useState } from 'react'
import { App, Button, Input, Segmented, Skeleton, Space, Tooltip, Typography } from 'antd'
import { SaveOutlined, UndoOutlined } from '@ant-design/icons'
import { api } from '../api'
import { addLeaveGuard } from '../router'
import Markdown from './Markdown'
import type { Kind } from '../types'

/** Edit a project text file (synopsis.md, qa.md, prompts) with a live markdown preview. ⌘S saves. */
export default function TextEditor({ kind, id, name, onSaved, height = 'calc(100vh - 330px)', placeholder, markdown = true, template, extra }: {
  kind: Kind; id: string; name: string; onSaved?: () => void; height?: string; placeholder?: string; markdown?: boolean; template?: string; extra?: React.ReactNode
}) {
  const { message } = App.useApp()
  const [text, setText] = useState<string | null>(null)
  const [saved, setSaved] = useState('')
  const [exists, setExists] = useState(true)
  const [view, setView] = useState<string>(() => localStorage.getItem('kcs.mdview') ?? 'split')
  const [busy, setBusy] = useState(false)
  const dirty = text !== null && text !== saved
  useEffect(() => {
    api.text(kind, id, name).then(r => { setText(r.exists ? r.text : (template ?? '')); setSaved(r.exists ? r.text : ''); setExists(r.exists) })
      .catch(e => message.error(e.message))
  }, [kind, id, name, template, message])
  useEffect(() => addLeaveGuard(() => dirty), [dirty])
  const save = async () => {
    if (text === null) return
    setBusy(true)
    try { await api.saveText(kind, id, name, text); setSaved(text); setExists(true); message.success(`Saved ${name}`); onSaved?.() }
    catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && dirty) { e.preventDefault(); save() } }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  })
  if (text === null) return <Skeleton active />
  const editor = <Input.TextArea value={text} onChange={e => setText(e.target.value)} placeholder={placeholder} className="!font-mono !text-[13px] !leading-relaxed" style={{ height, resize: 'none' }} />
  const preview = <div className="rounded-lg border border-line bg-panel p-4 overflow-auto" style={{ height }}><Markdown text={text || '*(empty)*'} /></div>
  return (
    <div className="flex flex-col gap-2">
      <Space wrap>
        <Typography.Text strong>{name}</Typography.Text>
        {!exists && <Typography.Text type="warning">new file — save to create it</Typography.Text>}
        <Typography.Text type={dirty ? 'warning' : 'secondary'} className="text-xs">{dirty ? '● unsaved changes' : 'saved'}</Typography.Text>
        {markdown && <Segmented size="small" value={view} onChange={v => { setView(String(v)); localStorage.setItem('kcs.mdview', String(v)) }}
          options={[{ value: 'edit', label: 'Edit' }, { value: 'split', label: 'Side by side' }, { value: 'preview', label: 'Preview' }]} />}
        {extra}
        <Tooltip title="Throw away unsaved changes"><Button size="small" icon={<UndoOutlined />} disabled={!dirty} onClick={() => setText(saved)}>Revert</Button></Tooltip>
        <Tooltip title="⌘S — the previous version is kept in .studio_history/"><Button type="primary" size="small" icon={<SaveOutlined />} disabled={!dirty} loading={busy} onClick={save}>Save</Button></Tooltip>
      </Space>
      {!markdown || view === 'edit' ? editor : view === 'preview' ? preview : <div className="grid grid-cols-2 gap-3">{editor}{preview}</div>}
    </div>
  )
}
