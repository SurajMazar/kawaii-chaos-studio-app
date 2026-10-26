import { useEffect, useState } from 'react'
import { Button, Empty, Input, Skeleton, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { EditOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import NewLyricEdit from '../components/NewLyricEdit'
import { StatusTags } from './Dashboard'
import type { Item } from '../types'

export default function MusicVideos() {
  const [items, setItems] = useState<Item[] | null>(null)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  useEffect(() => { api.library().then(d => setItems(d.items.filter(i => i.kind === 'mv').sort((a, b) => b.num - a.num))).catch(() => setItems([])) }, [])
  const { tour, button } = usePageTour('music', [
    { title: 'Music videos & lyric edits', description: 'Every folder in music_videos/. Lyric edits are opened in the lyric editor; older music videos show their frames and renders.' },
    { target: 'mv-new', title: 'New lyric edit', description: 'Start from your own pictures, your own lyrics, a blank edit or a copy of another edit — and choose where the song starts.' },
    { target: 'mv-table', title: 'Open an edit', description: 'Click an edit name to open the editor, or the folder to see its story, pictures, QA and files.' },
  ], !!items)
  const rows = (items ?? []).filter(i => !q || `${i.id} ${i.title}`.toLowerCase().includes(q.toLowerCase()))
  return (
    <>
      <PageHeader title="Music videos & lyric edits" sub="music_videos/ — lyric reels with original songs, and lyric edits of your pictures"
        extra={<>{button}<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)} data-tour="mv-new">New lyric edit</Button></>} />
      <div className="flex-1 overflow-auto p-5">
        {!items ? <Skeleton active /> : items.length === 0 ? <Empty description="No music videos yet." /> : <>
          <Space className="mb-3"><Input.Search allowClear placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} style={{ width: 260 }} />
            <Typography.Text type="secondary">{rows.length} {rows.length === 1 ? 'folder' : 'folders'}</Typography.Text></Space>
          <div data-tour="mv-table">
            <Table<Item> size="middle" scroll={{ x: 760 }} rowKey="id" dataSource={rows} pagination={false}
              columns={[
                { title: '', width: 76, render: (_, i) => i.thumb ? <img src={api.thumbUrl('mv', i.id, i.thumb, 120, i.mtime)} className="w-14 h-20 object-cover rounded" loading="lazy" /> : <div className="w-14 h-20 rounded bg-[#28232e]" /> },
                { title: 'Folder', render: (_, i) => <div><a onClick={() => go(`/p/mv/${i.id}`)} className="font-display font-bold text-[15px]">{i.headline}</a>
                  <div className="text-xs opacity-50">{i.id} · {i.couple}</div></div> },
                { title: 'Type', width: 120, render: (_, i) => i.type === 'lyric_edit' ? <Tag color="purple">lyric edit</Tag> : <Tag color="blue">music video</Tag> },
                { title: 'Lyric edits', render: (_, i) => (i.edits ?? []).length ? <Space wrap size={4}>{i.edits!.map(f => <Tooltip key={f} title="Open in the lyric editor"><Button size="small" icon={<EditOutlined />} onClick={() => go(`/lyric/${i.id}/${f}`)}>{f.replace('.json', '')}</Button></Tooltip>)}</Space> : <span className="opacity-40 text-xs">—</span> },
                { title: 'Status', render: (_, i) => <StatusTags i={i} /> },
                { title: '', width: 90, render: (_, i) => <Button size="small" icon={<FolderOpenOutlined />} onClick={() => go(`/p/mv/${i.id}`)}>Open</Button> },
              ]} />
          </div>
        </>}
      </div>
      <NewLyricEdit open={open} onClose={() => setOpen(false)} />
      {tour}
    </>
  )
}
