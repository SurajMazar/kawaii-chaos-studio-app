import { useState } from 'react'
import { Button, Card, Col, Empty, List, Row, Space, Tooltip, Typography } from 'antd'
import { DownloadOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '../api'
import { go } from '../router'
import NewLyricEdit from '../components/NewLyricEdit'
import type { TabProps } from '../pages/PiecePage'

export default function LyricTab({ id, item }: TabProps) {
  const [open, setOpen] = useState(false)
  const [play, setPlay] = useState<string | null>(null)
  return (
    <Row gutter={16}>
      <Col xs={24} xl={10}>
        <Card size="small" title="Lyric edits in this folder" extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setOpen(true)}>New lyric edit</Button>}>
          {(item.edits ?? []).length === 0 ? <Empty description="No lyric edit yet. Make one from your pictures and your song." /> :
            <List size="small" dataSource={item.edits} renderItem={f => (
              <List.Item actions={[<Button key="o" type="primary" size="small" icon={<EditOutlined />} onClick={() => go(`/lyric/${id}/${f}`)}>Open editor</Button>]}>
                <span className="font-mono text-sm">{f}</span>
              </List.Item>)} />}
        </Card>
        <Card size="small" title="Rendered videos" className="!mt-3">
          {[...(item.renders ?? []).map(r => ({ path: r, url: api.fileUrl('mv', id, r), dl: api.downloadUrl('mv', id, r) })),
            ...(item.uploads ?? []).map(u => ({ path: `upload/music_videos/${u}`, url: api.rootUrl(`upload/music_videos/${u}`), dl: api.rootUrl(`upload/music_videos/${u}`, true) }))].map(v => (
            <div key={v.path} className="flex items-center gap-2 py-1">
              <a onClick={() => setPlay(play === v.url ? null : v.url)} className="truncate">{v.path}</a>
              <Tooltip title="Download"><Button className="ml-auto" size="small" icon={<DownloadOutlined />} href={v.dl} /></Tooltip>
            </div>))}
          {!(item.renders?.length || item.uploads?.length) && <Typography.Text type="secondary">Nothing rendered yet — use Quick preview / Final video in the editor.</Typography.Text>}
        </Card>
      </Col>
      <Col xs={24} xl={14}>
        <Card size="small" title="Player">{play ? <video key={play} src={play} controls autoPlay className="rounded-lg bg-black mx-auto block" style={{ maxHeight: 'calc(100vh - 330px)' }} /> : <Empty description="Click a video to play it." />}</Card>
        <Space className="mt-2"><Typography.Text type="secondary" className="text-xs">Older music videos (frames + song) were built with scripts/build_music_video.sh; their uploads are listed here too.</Typography.Text></Space>
      </Col>
      <NewLyricEdit open={open} onClose={() => setOpen(false)} pid={id} />
    </Row>
  )
}
