import { useEffect, useState } from 'react'
import { App, Form, Input, InputNumber, Modal, Radio, Select, Typography } from 'antd'
import { api } from '../api'
import { go } from '../router'
import { parseTime } from '../lib'
import type { LyricProject } from '../types'

/** "New lyric edit" flow: pick the folder, start blank / from your pictures / from your lyrics / as a copy, choose the start time. */
export default function NewLyricEdit({ open, onClose, pid }: { open: boolean; onClose: () => void; pid?: string }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [all, setAll] = useState<LyricProject[]>([])
  const [busy, setBusy] = useState(false)
  const mode = Form.useWatch('mode', form)
  const target = Form.useWatch('pid', form)
  const srcPid = Form.useWatch('src_pid', form)
  useEffect(() => { if (open) { api.lyricProjects(true).then(setAll).catch(() => {}); form.resetFields() } }, [open, form])
  const existing = all.find(p => p.id === target)?.files ?? []
  const nextName = () => { let k = existing.length ? 2 : 1, n = 'lyric_edit.json'; while (existing.includes(n)) n = `lyric_edit_v${k++}.json`; return n }
  useEffect(() => { if (target) form.setFieldValue('file', nextName()) }, [target, all]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    const v = await form.validateFields(); setBusy(true)
    try {
      const start = parseTime(String(v.start ?? '0')) ?? 0
      await api.newEdit(v.pid, { file: v.file, mode: v.mode, src_pid: v.src_pid, src_file: v.src_file, start, seconds_per_line: v.spl, lines_text: v.lines ?? '' })
      message.success(`Made ${v.file}`); onClose(); go(`/lyric/${v.pid}/${v.file}`)
    } catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onCancel={onClose} onOk={submit} confirmLoading={busy} okText="Make it and open the editor" title="New lyric edit" width={620} destroyOnClose>
      <Typography.Paragraph type="secondary">A lyric edit = your pictures + words timed to a song. Need a brand-new folder first? Use <a onClick={() => { onClose(); go('/new') }}>New project → Lyric edit</a>.</Typography.Paragraph>
      <Form form={form} layout="vertical" initialValues={{ pid, mode: 'frames', start: '0:00', spl: 3, file: 'lyric_edit.json' }}>
        <Form.Item name="pid" label="Folder (music_videos/)" rules={[{ required: true, message: 'Pick a folder' }]}>
          <Select showSearch options={all.map(p => ({ value: p.id, label: `${p.id}${p.files.length ? ` · ${p.files.length} edit${p.files.length > 1 ? 's' : ''}` : ''}` }))} placeholder="pick a folder" />
        </Form.Item>
        <Form.Item name="mode" label="Start from">
          <Radio.Group optionType="button" buttonStyle="solid" options={[
            { value: 'frames', label: 'My pictures' }, { value: 'lyrics', label: 'My lyrics' }, { value: 'blank', label: 'Blank' }, { value: 'copy', label: 'Copy an edit' }]} />
        </Form.Item>
        {mode === 'frames' && <Typography.Paragraph type="secondary" className="!-mt-3">One line per picture in edit_frames/ (or frame*.png). Add pictures later in the editor too.</Typography.Paragraph>}
        {mode === 'lyrics' && <Form.Item name="lines" label="Lyrics — one line per row (use / for a new row, *word* for a big word)" rules={[{ required: true }]}>
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 10 }} placeholder={'*POLITE* / little maid / of the mansion\n*PRAY* / for the night / to stay quiet'} />
        </Form.Item>}
        {mode === 'copy' && <div className="grid grid-cols-2 gap-3">
          <Form.Item name="src_pid" label="Copy from folder" rules={[{ required: true }]}><Select options={all.filter(p => p.files.length).map(p => ({ value: p.id, label: p.id }))} /></Form.Item>
          <Form.Item name="src_file" label="Edit" rules={[{ required: true }]}><Select options={(all.find(p => p.id === srcPid)?.files ?? []).map(f => ({ value: f, label: f }))} /></Form.Item>
        </div>}
        <div className="grid grid-cols-3 gap-3">
          <Form.Item name="start" label="Song starts at" tooltip="Where in the song the video begins, e.g. 0:25.47 (copies are shifted to it)"><Input placeholder="0:25.47" /></Form.Item>
          {mode !== 'copy' && <Form.Item name="spl" label="Seconds per line"><InputNumber min={0.5} max={20} step={0.5} className="!w-full" /></Form.Item>}
          <Form.Item name="file" label="File name" rules={[{ required: true }, { pattern: /^lyric_edit[A-Za-z0-9_-]*\.json$/, message: 'lyric_edit….json' }]}><Input /></Form.Item>
        </div>
      </Form>
    </Modal>
  )
}
