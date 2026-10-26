import { useEffect, useMemo, useState } from 'react'
import { Alert, App, AutoComplete, Button, Card, Col, Form, Input, Popconfirm, Row, Select, Space, Table, Tag, Tooltip, Typography, Skeleton } from 'antd'
import { CopyOutlined, InstagramOutlined, SaveOutlined, TagsOutlined } from '@ant-design/icons'
import { api } from '../api'
import { addLeaveGuard } from '../router'
import type { TabProps } from '../pages/PiecePage'
import type { PostEntry, Song } from '../types'

type Info = Awaited<ReturnType<typeof api.post>>
const today = () => new Date().toISOString().slice(0, 10)

export default function PostTab({ kind, id, reload }: TabProps) {
  const { message } = App.useApp()
  const [info, setInfo] = useState<Info | null>(null)
  const [cap, setCap] = useState(''); const [pin, setPin] = useState('')
  const [saved, setSaved] = useState(['', ''])
  const [songs, setSongs] = useState<Song[]>([])
  const [form] = Form.useForm()
  const load = () => api.post(kind, id).then(i => { setInfo(i); setCap(i.caption); setPin(i.pinned); setSaved([i.caption, i.pinned]) }).catch(e => message.error(e.message))
  useEffect(() => { load(); api.songs().then(setSongs).catch(() => {}) }, [kind, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = cap !== saved[0] || pin !== saved[1]
  useEffect(() => addLeaveGuard(() => dirty), [dirty])

  const [songQ, setSongQ] = useState('')
  const songOpts = useMemo(() => {
    const q = songQ.trim().toLowerCase(); const ok = (v: string, g = '') => !q || v.toLowerCase().includes(q) || g.toLowerCase().includes(q)
    const ideas = (info?.song_ideas ?? []).filter(s => ok(s)).map(s => ({ value: s, label: <span>{s} <Tag color="pink" className="!ml-1">idea for this strip</Tag></span> }))
    const groups = new Map<string, { value: string; label: string }[]>(); const seen = new Set<string>()
    for (const s of songs) {
      const v = s.artist ? `${s.title} (${s.artist})` : s.title
      if (!ok(v, s.group) || seen.has(s.group + v)) continue
      seen.add(s.group + v); if (!groups.has(s.group)) groups.set(s.group, []); groups.get(s.group)!.push({ value: v, label: v })
    }
    return [...(ideas.length ? [{ label: 'Ideas from the script', options: ideas }] : []), ...[...groups].map(([g, o]) => ({ label: g, options: o }))]
  }, [songs, info, songQ])

  const save = async () => { try { await api.saveCaption(kind, id, cap, pin); setSaved([cap, pin]); message.success('Caption saved (captions.json + synopsis)'); reload() } catch (e) { message.error((e as Error).message) } }
  const copy = (t: string, what: string) => { navigator.clipboard.writeText(t); message.success(`${what} copied`) }
  const tags = cap.match(/#\w+/g) ?? []
  if (!info) return <Skeleton active />

  return (
    <Row gutter={16}>
      <Col xs={24} xl={12}>
        <Card size="small" title="Caption" extra={<Space>
          <Tooltip title="Add your default hashtags (Settings)"><Button size="small" icon={<TagsOutlined />} onClick={() => setCap(c => (c.trim() + '\n\n' + info.hashtags).trim())}>+ hashtags</Button></Tooltip>
          <Button size="small" icon={<CopyOutlined />} onClick={() => copy(cap, 'Caption')} disabled={!cap}>Copy</Button>
          <Button size="small" type="primary" icon={<SaveOutlined />} disabled={!dirty} onClick={save}>Save</Button>
        </Space>}>
          <Typography.Paragraph type="secondary" className="text-xs">One sweet/funny line + emoji, a blank line, then ~5 hashtags including the couple tag and your account tag.</Typography.Paragraph>
          <Input.TextArea value={cap} onChange={e => setCap(e.target.value)} autoSize={{ minRows: 5, maxRows: 12 }} placeholder={'he lost the jacket. she found it (she was wearing it) 🧥💙\n\n#CoupleTag #AnimeComics #ChibiArt #FanArt #YourAccount'} />
          <div className="flex justify-between mt-1 text-xs opacity-60"><span>{tags.length} hashtag{tags.length === 1 ? '' : 's'}</span><span>{cap.length} / 2200</span></div>
          <div className="label mt-3 mb-1">Pinned comment</div>
          <Space.Compact className="w-full">
            <Input value={pin} onChange={e => setPin(e.target.value)} placeholder="a question for the comments 👇" />
            <Button icon={<CopyOutlined />} onClick={() => copy(pin, 'Pinned comment')} disabled={!pin} />
          </Space.Compact>
          {!info.in_captions_json && info.caption && <Alert className="!mt-3" type="info" showIcon message="This caption comes from the synopsis — press Save to put it in captions.json too." />}
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Card size="small" title={<span><InstagramOutlined /> Mark as posted</span>}>
          <Form form={form} layout="vertical" initialValues={{ format: kind === 'strip' ? 'strip_reel' : 'music_video', date: today(), song: '', url: '' }}
            onFinish={async v => {
              try { await api.markPosted(kind, id, { ...v, note: '' }); message.success('Saved to posting_log.json'); form.resetFields(); await load(); reload() }
              catch (e) { message.error((e as Error).message) }
            }}>
            <div className="grid grid-cols-2 gap-x-3">
              <Form.Item name="format" label="What did you post?" rules={[{ required: true }]}>
                <Select options={kind === 'strip' ? [{ value: 'strip_reel', label: 'Strip reel (video)' }, { value: 'image', label: 'Strip image' }, { value: 'carousel', label: 'Carousel' }] : [{ value: 'music_video', label: 'Music video / lyric edit' }, { value: 'story', label: 'Story' }]} />
              </Form.Item>
              <Form.Item name="date" label="Date" rules={[{ required: true }]}><Input type="date" /></Form.Item>
            </div>
            <Form.Item name="song" label="Song picked in the Instagram app" tooltip="Shortlists from songs.md — or type any song">
              <AutoComplete options={songOpts} placeholder="search or type a song (or a couple)" onSearch={setSongQ} filterOption={false} popupMatchSelectWidth={420} />
            </Form.Item>
            <Form.Item name="url" label="Link to the post (optional)" rules={[{ pattern: /^$|^https?:\/\//, message: 'must start with https://' }]}>
              <Input placeholder="https://www.instagram.com/your.account/reel/…" />
            </Form.Item>
            <Button type="primary" htmlType="submit">Mark as posted</Button>
          </Form>
        </Card>
        <Card size="small" title="Posting history" className="!mt-3">
          <Table<PostEntry> size="small" rowKey={r => r.format + (r.date ?? '')} dataSource={info.posts} pagination={false}
            locale={{ emptyText: 'Not in posting_log.json yet.' }}
            columns={[
              { title: 'Format', dataIndex: 'format' },
              { title: 'Status', render: (_, r) => r.posted ? <Tag color="magenta">posted {r.date ?? ''}</Tag> : <Tag>ready</Tag> },
              { title: 'Song', dataIndex: 'song', render: s => s || <span className="opacity-40">—</span> },
              { title: 'Link', dataIndex: 'url', render: u => u ? <a href={u} target="_blank" rel="noreferrer">open</a> : null },
              { title: '', render: (_, r) => r.posted ? <Popconfirm title="Mark as not posted?" onConfirm={async () => { await api.unmarkPosted(kind, id, r.format); await load(); reload() }}><Button size="small" type="text">undo</Button></Popconfirm> : null },
            ]} />
          {info.song_ideas.length > 0 && <div className="mt-2 text-xs opacity-70">Song ideas: {info.song_ideas.join(' · ')}</div>}
        </Card>
      </Col>
    </Row>
  )
}
