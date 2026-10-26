import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Checkbox, Empty, Image, Input, Modal, Popconfirm, Space, Tag, Tooltip, Typography, Upload, Skeleton } from 'antd'
import {
  CloudDownloadOutlined, DeleteOutlined, DownloadOutlined, InboxOutlined, RollbackOutlined, StarOutlined,
  IdcardOutlined, DiffOutlined, BgColorsOutlined,
} from '@ant-design/icons'
import { api } from '../api'
import { useJob, JobPanel } from '../components/Jobs'
import ImageCompare, { type CmpSource } from '../components/ImageCompare'
import type { TabProps } from '../pages/PiecePage'
import type { ImgItem } from '../types'
import { useOwnArt } from '../settings'

type Groups = Awaited<ReturnType<typeof api.images>>

export default function ImagesTab({ kind, id, item, reload, goTab }: TabProps) {
  const { message } = App.useApp()
  const [groups, setGroups] = useState<Groups | null>(null)
  const [refs, setRefs] = useState<CmpSource[]>([])
  const [cmp, setCmp] = useState<CmpSource | null>(null)
  const [dl, setDl] = useState(false)
  const [asStrip, setAsStrip] = useState(false)
  const ownArt = useOwnArt()
  useEffect(() => { if (ownArt && kind === 'strip' && !item.status.strip) setAsStrip(true) }, [ownArt]) // eslint-disable-line react-hooks/exhaustive-deps
  const [jobId, setJobId] = useState<string | null>(null)
  const [rejectFor, setRejectFor] = useState<ImgItem | null>(null)
  const [reason, setReason] = useState('')
  const { job, log } = useJob(jobId, j => { load(); reload(); if (j.state === 'done') message.success(`${j.title}: done`); if (j.state === 'error') message.error(j.error ?? 'failed') })
  const load = () => api.images(kind, id).then(setGroups).catch(e => message.error(e.message))
  useEffect(() => {
    load()
    api.refs().then(r => setRefs(r.map(x => ({ label: `references/${x.name}`, url: api.rootUrl(x.path) })))).catch(() => {})
  }, [kind, id]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); message.success(ok); await load(); await reload() } catch (e) { message.error((e as Error).message) } }
  const uploadFiles = async (files: File[]) => {
    for (const [k, f] of files.entries()) {
      const role = asStrip && kind === 'strip' && k === files.length - 1 ? 'strip' : ''
      try { const r = await api.upload(kind, id, f, kind === 'mv' ? 'edit_frames' : 'raw', role); message.success(`Added ${r.path}${role ? ' and set it as strip.png' : ''}`) }
      catch (e) { message.error(`${f.name}: ${(e as Error).message}`) }
    }
    await load(); await reload()
  }
  const sources: CmpSource[] = [...refs, ...(item.status.charsheet ? [{ label: 'charsheet.png (this project)', url: api.fileUrl(kind, id, 'charsheet.png') }] : [])]
  const defaultRef = refs.find(r => r.label.endsWith('style_ref_master.jpg'))?.url ?? refs.find(r => r.label.endsWith('style_ref.png'))?.url

  const card = (m: ImgItem, g: string) => {
    const isStrip = m.path === 'strip.png', isSheet = m.path === 'charsheet.png'
    return (
      <Card key={m.path} size="small" styles={{ body: { padding: 8 } }}
        cover={<div className="checker flex items-center justify-center h-44 overflow-hidden">
          <Image src={api.thumbUrl(kind, id, m.path, 360, m.mtime)} preview={{ src: api.fileUrl(kind, id, m.path, m.mtime) }} rootClassName="!w-full !h-full" className="!w-full !h-44 object-contain" />
        </div>}>
        <div className="flex items-center gap-1 mb-1">
          <Typography.Text className="text-xs truncate" title={m.path}>{m.name}</Typography.Text>
          {isStrip && <Tag color="magenta" className="!ml-auto">strip</Tag>}
          {isSheet && <Tag color="purple" className="!ml-auto">sheet</Tag>}
        </div>
        <div className="flex flex-wrap gap-1">
          {kind === 'strip' && !isStrip && <Popconfirm title="Use this as the strip?" description="strip.png is replaced (the old one is kept in .studio_history/) and its QA must be done again."
            onConfirm={() => act(() => api.setRole(kind, id, m.path, 'strip'), 'Set as strip.png')}>
            <Tooltip title="Use as the final strip (strip.png)"><Button size="small" icon={<StarOutlined />} /></Tooltip></Popconfirm>}
          {!isSheet && <Popconfirm title="Use this as the character sheet?" description="charsheet.png is replaced (the old one is kept in .studio_history/)."
            onConfirm={() => act(() => api.setRole(kind, id, m.path, 'charsheet'), 'Set as charsheet.png')}>
            <Tooltip title="Use as the character sheet (charsheet.png)"><Button size="small" icon={<IdcardOutlined />} /></Tooltip></Popconfirm>}
          <Tooltip title="Compare side by side with the style master (zoom together)"><Button size="small" icon={<DiffOutlined />} onClick={() => setCmp({ label: m.path, url: api.fileUrl(kind, id, m.path, m.mtime) })} /></Tooltip>
          <Tooltip title="Style check: master crop next to this picture's characters"><Button size="small" icon={<BgColorsOutlined />} disabled={!!job && job.state === 'running'}
            onClick={async () => { try { setJobId((await api.styleCheck(kind, id, m.path)).id) } catch (e) { message.error((e as Error).message) } }} /></Tooltip>
          <Tooltip title="Download"><Button size="small" icon={<DownloadOutlined />} href={api.downloadUrl(kind, id, m.path)} /></Tooltip>
          {(g === 'raw' || g === 'edit_frames') && <Tooltip title="Move to Rejected (raw/rejected/)"><Button size="small" danger icon={<DeleteOutlined />} onClick={() => { setRejectFor(m); setReason('') }} /></Tooltip>}
          {g === 'rejected' && <Tooltip title="Bring back to Drafts"><Button size="small" icon={<RollbackOutlined />} onClick={() => act(() => api.restore(kind, id, m.path), 'Moved back to raw/')} /></Tooltip>}
        </div>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <Card size="small">
        <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
          <Upload.Dragger multiple accept="image/*" showUploadList={false} beforeUpload={(f, list) => { if (f === list[list.length - 1]) uploadFiles(list); return false }}>
            <p className="ant-upload-drag-icon !mb-1"><InboxOutlined /></p>
            <p className="ant-upload-text">{ownArt && kind === 'strip' ? 'Drop your finished drawing here, or click to choose' : 'Drop your own pictures here, or click to choose'}</p>
            <p className="ant-upload-hint">They go into {kind === 'mv' ? 'edit_frames/' : 'raw/ (drafts)'}. PNG, JPG or WEBP.</p>
          </Upload.Dragger>
          <div className="flex flex-col gap-2 justify-center">
            {kind === 'strip' && <Checkbox checked={asStrip} onChange={e => setAsStrip(e.target.checked)}>Use the dropped picture as strip.png right away</Checkbox>}
            <Button icon={<CloudDownloadOutlined />} onClick={() => setDl(true)}>Import from Downloads…</Button>
            {kind === 'strip' && item.status.strip && <Button type="link" onClick={() => goTab('qa')}>Next: QA the strip →</Button>}
          </div>
        </div>
      </Card>
      {job && <Card size="small"><JobPanel job={job} log={log} />
        {job.state === 'done' && job.result?.output ? <Space className="mt-2" wrap>
          <Image width={360} src={api.fileUrl(kind, id, String(job.result.output), Date.now())} />
          {job.result.orange ? <Image width={220} src={api.fileUrl(kind, id, String(job.result.orange), Date.now())} /> : null}
          <Typography.Text type="secondary" className="text-xs max-w-[260px] block">Left: master crops, right: this picture's characters at the same scale — judge line, colour and proportions by eye..</Typography.Text>
        </Space> : null}
      </Card>}
      {!groups ? <Skeleton active /> : groups.groups.map(g => (
        <Card key={g.key} size="small" title={<span>{g.title} <Typography.Text type="secondary" className="text-xs">{g.items.length}</Typography.Text></span>}>
          {g.items.length === 0 ? <Typography.Text type="secondary">{g.key === 'main' ? 'No strip or character sheet yet — drop a picture above and press ★ on it.' : 'Nothing here.'}</Typography.Text> :
            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>{g.items.map(m => card(m, g.key))}</div>}
        </Card>
      ))}
      {groups && groups.stylechecks.length > 0 && <Card size="small" title="Style checks">
        <Image.PreviewGroup><Space wrap>{groups.stylechecks.map(s => <Image key={s.path} width={220} src={api.fileUrl(kind, id, s.path, s.mtime)} />)}</Space></Image.PreviewGroup>
      </Card>}

      <DownloadsModal open={dl} onClose={() => setDl(false)} kind={kind} id={id} onImported={async () => { await load(); await reload() }} onJob={setJobId} />
      {cmp && <ImageCompare open onClose={() => setCmp(null)} left={cmp} sources={sources} defaultRight={defaultRef} />}
      <Modal open={!!rejectFor} title="Move to Rejected" okText="Move" okButtonProps={{ danger: true }} onCancel={() => setRejectFor(null)}
        onOk={async () => { if (rejectFor) await act(() => api.reject(kind, id, rejectFor.path, reason), 'Moved to raw/rejected/'); setRejectFor(null) }}>
        <Typography.Paragraph>Why does <b>{rejectFor?.name}</b> fail? The reason becomes part of the file name (QA rule), e.g. <i>G style watercolour</i>.</Typography.Paragraph>
        <Input value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. C order swapped" autoFocus />
      </Modal>
    </div>
  )
}

function DownloadsModal({ open, onClose, kind, id, onImported, onJob }: { open: boolean; onClose: () => void; kind: TabProps['kind']; id: string; onImported: () => void; onJob: (id: string) => void }) {
  const { message } = App.useApp()
  const [data, setData] = useState<Awaited<ReturnType<typeof api.downloads>> | null>(null)
  const [sel, setSel] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { if (open) { setSel([]); api.downloads().then(d => { setData(d); setErr(null) }).catch(e => setErr(e.message)) } }, [open])
  const own = useOwnArt()
  const imgs = data?.items.filter(i => !i.bundle) ?? []
  const bundles = data?.items.filter(i => i.bundle) ?? []
  return (
    <Modal open={open} onCancel={onClose} width={860} title="Import from Downloads" okText={`Import ${sel.length || ''} picture${sel.length === 1 ? '' : 's'}`} okButtonProps={{ disabled: !sel.length }}
      onOk={async () => { try { const r = await api.importDownloads(kind, id, sel); message.success(`Imported ${r.paths.length} into raw/`); onImported(); onClose() } catch (e) { message.error((e as Error).message) } }}>
      {err && <Alert type="error" message={err} showIcon />}
      {bundles.length > 0 && !own && <Alert className="!mb-3" type="info" showIcon message={`${bundles.length} ChatGPT bundle file${bundles.length > 1 ? 's' : ''} found (*_bundle*.bin)`}
        description={kind === 'strip' ? 'Unpacking puts every bundle into the raw/ folder of the strip it belongs to (by name).' : 'Unpacking puts the bundle pictures into this folder\'s raw/.'}
        action={<Button type="primary" onClick={async () => { try { onJob((await api.importBundles(kind, id)).id); onClose() } catch (e) { message.error((e as Error).message) } }}>Unpack bundles</Button>} />}
      <Typography.Paragraph type="secondary">Newest pictures in <code>{data?.dir}</code>. Pick the ones to copy into this project's raw/ folder (the originals stay in Downloads).</Typography.Paragraph>
      {imgs.length === 0 ? <Empty description="No pictures in Downloads." /> :
        <Checkbox.Group value={sel} onChange={v => setSel(v as string[])} className="!grid gap-2 max-h-[55vh] overflow-auto" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
          {imgs.map(i => <label key={i.name} className={`rounded-lg border p-1 cursor-pointer ${sel.includes(i.name) ? 'border-pink' : 'border-line'}`}>
            <img src={api.downloadsThumb(i.name)} className="w-full h-32 object-contain checker rounded" loading="lazy" />
            <div className="flex items-center gap-1 mt-1"><Checkbox value={i.name} /><span className="text-[11px] truncate" title={i.name}>{i.name}</span></div>
            <div className="text-[10px] opacity-50">{new Date(i.mtime * 1000).toLocaleString()}</div>
          </label>)}
        </Checkbox.Group>}
    </Modal>
  )
}
