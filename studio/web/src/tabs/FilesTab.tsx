import { useEffect, useState } from 'react'
import { App, Breadcrumb, Button, Image, Modal, Space, Table, Tooltip, Typography } from 'antd'
import { DownloadOutlined, EyeOutlined, ShareAltOutlined, FileOutlined, FileImageOutlined, FileTextOutlined, FolderFilled, SoundOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useAuth } from '../auth'
import type { TabProps } from '../pages/PiecePage'
import type { FileEntry } from '../types'

const ICON: Record<string, React.ReactNode> = { dir: <FolderFilled style={{ color: '#ffd84d' }} />, image: <FileImageOutlined />, text: <FileTextOutlined />, audio: <SoundOutlined />, video: <VideoCameraOutlined />, other: <FileOutlined /> }
const size = (n: number) => n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} B`

export default function FilesTab({ kind, id }: TabProps) {
  const { message } = App.useApp()
  const [dir, setDir] = useState('')
  const [rows, setRows] = useState<FileEntry[] | null>(null)
  const [view, setView] = useState<FileEntry | null>(null)
  const [text, setText] = useState('')
  const desktop = useAuth(s => !!s.state?.desktop)
  useEffect(() => { setRows(null); api.files(kind, id, dir).then(r => setRows(r.entries)).catch(e => message.error(e.message)) }, [kind, id, dir, message])
  const open = async (f: FileEntry) => {
    if (f.is_dir) { setDir(f.path); return }
    if (f.kind === 'text') { try { setText(await (await fetch(api.fileUrl(kind, id, f.path))).text()) } catch { setText('') } }
    setView(f)
  }
  // Mac app: the macOS share menu next to the button. Browser: the system share sheet with the file when the browser
  // has one (Safari, Chrome on phones), else the file's link is copied (opening it needs a Studio sign-in).
  const share = async (f: FileEntry, e: React.MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    try {
      if (desktop) { await api.share(kind, id, f.path, [r.left, r.top, r.width, r.height]); return }
      const blob = await (await fetch(api.fileUrl(kind, id, f.path), { credentials: 'same-origin' })).blob()
      const file = new File([blob], f.name, { type: blob.type })
      if (navigator.canShare?.({ files: [file] })) { await navigator.share({ files: [file], title: f.name }); return }
      await navigator.clipboard.writeText(new URL(api.fileUrl(kind, id, f.path), location.href).href)
      message.success('Link copied — opening it needs a Studio sign-in.')
    } catch (err) {
      if ((err as Error).name !== 'AbortError') message.error((err as Error).message || 'Could not share this file')
    }
  }
  const crumbs = dir ? dir.split('/') : []
  return (
    <>
      <Space className="mb-2" wrap>
        <Breadcrumb items={[{ title: <a onClick={() => setDir('')}>{id}</a> }, ...crumbs.map((c, i) => ({ title: <a onClick={() => setDir(crumbs.slice(0, i + 1).join('/'))}>{c}</a> }))]} />
        <Typography.Text type="secondary" className="text-xs">Everything in {kind === 'strip' ? 'projects' : 'music_videos'}/{id}/{dir}. Click a folder to open it, a file to look at it.</Typography.Text>
      </Space>
      <Table<FileEntry> size="small" scroll={{ x: 560 }} loading={!rows} dataSource={rows ?? []} rowKey="path" pagination={{ pageSize: 50, hideOnSinglePage: true }}
        onRow={r => ({ onDoubleClick: () => open(r) })}
        columns={[
          { title: 'Name', dataIndex: 'name', render: (n, r) => <a onClick={() => open(r)} className="flex items-center gap-2">{ICON[r.kind] ?? ICON.other}<span>{n}</span></a>, sorter: (a, b) => a.name.localeCompare(b.name) },
          { title: 'Size', dataIndex: 'size', width: 110, render: (n, r) => r.is_dir ? '' : size(n), sorter: (a, b) => a.size - b.size },
          { title: 'Changed', dataIndex: 'mtime', width: 190, render: t => new Date(t * 1000).toLocaleString(), sorter: (a, b) => a.mtime - b.mtime, defaultSortOrder: undefined },
          { title: '', width: 140, render: (_, r) => r.is_dir ? null : <Space>
            <Tooltip title="Look"><Button size="small" icon={<EyeOutlined />} onClick={() => open(r)} /></Tooltip>
            <Tooltip title="Share"><Button size="small" icon={<ShareAltOutlined />} onClick={e => share(r, e)} /></Tooltip>
            <Tooltip title="Download"><Button size="small" icon={<DownloadOutlined />} href={api.downloadUrl(kind, id, r.path)} /></Tooltip>
          </Space> },
        ]} />
      <Modal open={!!view} onCancel={() => setView(null)} footer={view && <Space>
        <Button icon={<ShareAltOutlined />} onClick={e => share(view, e)}>Share</Button>
        <Button icon={<DownloadOutlined />} href={api.downloadUrl(kind, id, view.path)}>Download</Button>
      </Space>} width={900} title={view?.path}>
        {view?.kind === 'image' && <div className="flex justify-center checker rounded"><Image src={api.fileUrl(kind, id, view.path, view.mtime)} style={{ maxHeight: '70vh' }} /></div>}
        {view?.kind === 'video' && <video src={api.fileUrl(kind, id, view.path)} controls className="w-full max-h-[70vh] bg-black rounded" />}
        {view?.kind === 'audio' && <audio src={api.fileUrl(kind, id, view.path)} controls className="w-full" />}
        {view?.kind === 'text' && <pre className="max-h-[70vh] overflow-auto text-xs whitespace-pre-wrap">{text}</pre>}
        {view?.kind === 'other' && <Typography.Text type="secondary">No preview for this kind of file — download it instead.</Typography.Text>}
      </Modal>
    </>
  )
}
