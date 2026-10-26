import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Drawer, Empty, Input, List, Modal, Select, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import { CustomerServiceOutlined, DeleteOutlined, PauseCircleOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useCan } from '../auth'
import type { CastMember, ElVoice, VoiceCast } from '../types'

/** One shared player for voice samples (served through the Studio — the page may only play its own media). */
function useSample() {
  const a = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)
  useEffect(() => () => { a.current?.pause() }, [])
  const toggle = (id: string) => {
    a.current?.pause()
    if (playing === id) { setPlaying(null); return }
    const el = new Audio(api.voicePreviewUrl(id)); a.current = el
    el.onended = () => setPlaying(null); el.onerror = () => setPlaying(null)
    el.play().catch(() => setPlaying(null)); setPlaying(id)
  }
  return { playing, toggle }
}

/** Pick an ElevenLabs voice: your voices (incl. ones you designed) or the public Voice Library. */
export function VoicePicker({ open, onClose, onPick, hint }: { open: boolean; onClose: () => void; onPick: (v: ElVoice) => void; hint?: string }) {
  const { message } = App.useApp()
  const [mine, setMine] = useState<ElVoice[] | null>(null)
  const [lib, setLib] = useState<ElVoice[] | null>(null)
  const [filter, setFilter] = useState(hint ?? '')
  const [search, setSearch] = useState(hint ?? '')
  const [busy, setBusy] = useState(false)
  const { playing, toggle } = useSample()
  const load = (refresh = false) => api.myVoices(refresh).then(setMine).catch(e => { message.error(e.message); setMine([]) })
  useEffect(() => { if (open) { setFilter(hint ?? ''); setSearch(hint ?? ''); load() } }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const find = async () => { setBusy(true); try { setLib(await api.voiceLibrary(search)) } catch (e) { message.error((e as Error).message) } finally { setBusy(false) } }
  const addAndUse = async (v: ElVoice) => {
    try { const r = await api.addLibraryVoice({ public_owner_id: v.public_owner_id!, voice_id: v.voice_id, name: v.name }); onPick({ ...v, voice_id: r.voice_id }); load(true) }
    catch (e) { message.error((e as Error).message) }
  }
  const row = (v: ElVoice, action: React.ReactNode) => (
    <List.Item actions={[
      v.has_preview ? <Tooltip title="Listen to the sample" key="p"><Button size="small" icon={playing === v.voice_id ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={() => toggle(v.voice_id)} /></Tooltip> : null,
      action,
    ]}>
      <List.Item.Meta title={<Space size={6}>{v.name}{v.category && <Tag className="!text-[10px]">{v.category}</Tag>}</Space>}
        description={<span className="text-xs">{[v.labels, v.description].filter(Boolean).join(' · ').slice(0, 220)}</span>} />
    </List.Item>)
  const shown = (mine ?? []).filter(v => !filter || `${v.name} ${v.labels} ${v.description}`.toLowerCase().includes(filter.toLowerCase()))
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={720} title={<span><CustomerServiceOutlined /> Choose a voice</span>} destroyOnHidden>
      <Tabs items={[
        { key: 'mine', label: 'My voices', children: <>
          <Space.Compact className="w-full mb-2">
            <Input allowClear prefix={<SearchOutlined />} placeholder="Filter by name, e.g. Sarah" value={filter} onChange={e => setFilter(e.target.value)} />
            <Tooltip title="Reload from ElevenLabs"><Button icon={<ReloadOutlined />} onClick={() => { setMine(null); load(true) }} /></Tooltip>
          </Space.Compact>
          <List size="small" loading={!mine} dataSource={shown} className="max-h-[55vh] overflow-auto" locale={{ emptyText: <Empty description="No voice matches — try the Voice Library tab." /> }}
            renderItem={v => row(v, <Button size="small" type="primary" key="u" onClick={() => onPick(v)}>Use</Button>)} />
        </> },
        { key: 'lib', label: 'Voice Library', children: <>
          <Typography.Paragraph type="secondary" className="text-xs">Public voices made by the ElevenLabs community. “Add & use” copies the voice into your account.</Typography.Paragraph>
          <Input.Search className="mb-2" enterButton="Search" loading={busy} value={search} onChange={e => setSearch(e.target.value)} onSearch={find} placeholder="e.g. young sarcastic, calm mature woman, Valf" />
          {lib && <List size="small" dataSource={lib} className="max-h-[50vh] overflow-auto" renderItem={v => row(v, <Button size="small" key="a" onClick={() => addAndUse(v)}>Add & use</Button>)} />}
        </> },
      ]} />
    </Modal>
  )
}

/** The voice cast: which ElevenLabs voice each character speaks with (voices.json, shared by every project). */
export default function VoiceCastDrawer({ open, onClose, cast, onSaved, eleven }: { open: boolean; onClose: () => void; cast: VoiceCast | null; onSaved: (c: VoiceCast) => void; eleven: boolean }) {
  const { message } = App.useApp()
  const canEdit = useCan('editor')
  const [rows, setRows] = useState<CastMember[]>([])
  const [model, setModel] = useState('eleven_v3')
  const [models, setModels] = useState<{ value: string; label: string }[]>([])
  const [pick, setPick] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  const { playing, toggle } = useSample()
  useEffect(() => { if (open && cast) { setRows(cast.characters.map(c => ({ ...c }))); setModel(cast.model); setDirty(false) } }, [open, cast])
  useEffect(() => { api.voiceStatus().then(s => setModels(s.models)).catch(() => {}) }, [])
  const set = (i: number, patch: Partial<CastMember>) => { setRows(r => r.map((x, k) => k === i ? { ...x, ...patch } : x)); setDirty(true) }
  const save = async () => { try { const c = await api.saveCast({ model, characters: rows }); onSaved(c); setDirty(false); message.success('Voice cast saved') } catch (e) { message.error((e as Error).message) } }
  return (
    <Drawer open={open} onClose={onClose} width={Math.min(980, window.innerWidth - 40)} title="Voice cast"
      extra={canEdit && <Button type="primary" icon={<SaveOutlined />} disabled={!dirty} onClick={save}>Save cast</Button>}>
      <Typography.Paragraph type="secondary">The voice each character speaks with in every voiced reel — so each character always sounds the same. Shared by all projects (<code>voices.json</code>).</Typography.Paragraph>
      {!eleven && <Alert className="!mb-3" type="info" showIcon message="ElevenLabs is not connected"
        description="You can still write the cast by voice name. To pick voices from your account and make lines here, an admin adds the API key in Settings → Integrations → ElevenLabs." />}
      <Space className="mb-3"><span>Model for new lines</span><Select className="!w-[420px]" value={model} options={models} onChange={v => { setModel(v); setDirty(true) }} /></Space>
      <Table<CastMember> size="small" scroll={{ x: 820 }} pagination={false} rowKey={(_, i) => String(i)} dataSource={rows}
        columns={[
          { title: 'Character', width: 150, render: (_, r, i) => <Input value={r.name} disabled={!canEdit} onChange={e => set(i, { name: e.target.value })} /> },
          { title: 'Series', width: 120, render: (_, r, i) => <Input value={r.series} disabled={!canEdit} onChange={e => set(i, { series: e.target.value })} /> },
          { title: 'ElevenLabs voice', render: (_, r, i) => <div className="flex flex-col gap-1">
            <Space.Compact className="w-full">
              <Input value={r.voice_name} disabled={!canEdit} placeholder="voice name" onChange={e => set(i, { voice_name: e.target.value })} />
              <Tooltip title={eleven ? 'Choose from your ElevenLabs voices' : 'Connect ElevenLabs first'}><Button disabled={!eleven || !canEdit} onClick={() => setPick(i)}>Choose…</Button></Tooltip>
            </Space.Compact>
            <Space size={4}>
              {r.voice_id ? <Tag color="green" className="!text-[10px]">id {r.voice_id}</Tag> : <Tag color="orange" className="!text-[10px]">no voice id yet</Tag>}
              {r.voice_id && eleven && <Button size="small" type="text" icon={playing === r.voice_id ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={() => toggle(r.voice_id)}>sample</Button>}
            </Space>
          </div> },
          { title: 'Notes', render: (_, r, i) => <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} value={r.notes} disabled={!canEdit} onChange={e => set(i, { notes: e.target.value })} /> },
          { title: '', width: 44, render: (_, __, i) => canEdit && <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => { setRows(r => r.filter((_, k) => k !== i)); setDirty(true) }} /> },
        ]} />
      {canEdit && <Button className="!mt-3" icon={<PlusOutlined />} onClick={() => { setRows(r => [...r, { name: '', voice_name: '', voice_id: '' }]); setDirty(true) }}>Add a character</Button>}
      <VoicePicker open={pick !== null} hint={pick !== null ? rows[pick]?.voice_name?.split(/[–-]/)[0].trim() : ''} onClose={() => setPick(null)}
        onPick={v => { if (pick !== null) set(pick, { voice_id: v.voice_id, voice_name: v.name }); setPick(null) }} />
    </Drawer>
  )
}
