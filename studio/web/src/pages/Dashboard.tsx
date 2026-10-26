import { useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Col, Empty, Input, Progress, Row, Segmented, Select, Skeleton, Space, Statistic, Tag, Tooltip, Typography, Upload } from 'antd'
import { ImportOutlined, PlusOutlined, ReloadOutlined, InstagramOutlined } from '@ant-design/icons'
import { useCan } from '../auth'
import { api } from '../api'
import { go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import type { Item, Stats } from '../types'

type Filter = 'all' | 'todo_qa' | 'todo_reel' | 'todo_caption' | 'ready' | 'posted' | 'no_strip'
const FILTERS: { value: Filter; label: string; test: (i: Item) => boolean }[] = [
  { value: 'all', label: 'Any status', test: () => true },
  { value: 'no_strip', label: 'No final picture yet', test: i => i.kind === 'strip' && !i.status.strip },
  { value: 'todo_qa', label: 'Needs QA', test: i => i.kind === 'strip' && !!i.status.strip && ['none', 'stale', 'revoked'].includes(i.status.qa ?? '') },
  { value: 'todo_reel', label: 'Needs a reel', test: i => i.kind === 'strip' && !!i.status.strip && !i.status.reel },
  { value: 'todo_caption', label: 'Needs a caption', test: i => i.kind === 'strip' && !i.status.caption },
  { value: 'ready', label: 'Ready to post', test: i => i.kind === 'strip' ? !!i.status.reel && !i.status.posted : !!i.status.reel && !i.status.posted },
  { value: 'posted', label: 'Posted', test: i => !!i.status.posted },
]

export function QaTag({ i }: { i: Item }) {
  const s = i.status
  if (i.kind === 'mv') {
    if (!s.frames) return null
    return <Tag color={s.frames_pass === s.frames ? 'green' : 'default'}>QA {s.frames_pass}/{s.frames}</Tag>
  }
  if (!s.strip) return <Tag>no picture yet</Tag>
  const m: Record<string, [string, string, string]> = {
    pass: ['green', 'QA passed', 'qa.md has a PASS line for the current strip.png'],
    stale: ['orange', 'QA outdated', 'strip.png changed after its PASS — check it again'],
    none: ['gold', 'needs QA', 'no PASS line yet'], revoked: ['red', 'QA revoked', 'the PASS for this picture was revoked'],
    nofile: ['default', 'no QA file', 'made before the QA gate (no qa.md)'],
  }
  const [c, t, tip] = m[s.qa ?? 'none'] ?? m.none
  return <Tooltip title={tip}><Tag color={c}>{t}</Tag></Tooltip>
}

export function StatusTags({ i }: { i: Item }) {
  const s = i.status
  return (
    <div className="flex flex-wrap gap-y-1">
      <QaTag i={i} />
      {i.kind === 'strip' && (s.reel ? <Tag color="blue">reel built</Tag> : s.strip ? <Tag>no reel</Tag> : null)}
      {i.kind === 'strip' && s.voiceover && <Tag color="purple">voiced</Tag>}
      {i.kind === 'mv' && (s.edits ? <Tag color="purple">{s.edits} lyric edit{s.edits > 1 ? 's' : ''}</Tag> : null)}
      {i.kind === 'mv' && s.reel && <Tag color="blue">video</Tag>}
      {i.kind === 'strip' && (s.caption ? <Tag color="cyan">caption</Tag> : <Tag>no caption</Tag>)}
      {s.posted && <Tag color="magenta" icon={<InstagramOutlined />}>{i.kind === 'strip' ? [s.posted_image && 'image', s.posted_reel && 'reel'].filter(Boolean).join(' + ') : 'posted'}</Tag>}
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState<{ items: Item[]; stats: Stats } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [search, setSearch] = useState(() => sessionStorage.getItem('kcs.lib.q') ?? '')
  const [type, setType] = useState<string>(() => sessionStorage.getItem('kcs.lib.type') ?? 'all')
  const [couple, setCouple] = useState<string>(() => sessionStorage.getItem('kcs.lib.couple') ?? 'all')
  const [filter, setFilter] = useState<Filter>(() => (sessionStorage.getItem('kcs.lib.filter') as Filter) ?? 'all')
  const [allCouples, setAllCouples] = useState(false)
  const [sort, setSort] = useState<string>(() => sessionStorage.getItem('kcs.lib.sort') ?? 'newest')
  const { message } = App.useApp()
  const canEdit = useCan('editor')
  const [importing, setImporting] = useState(false)
  const importZip = async (f: File) => {
    setImporting(true); const hide = message.loading(`Importing ${f.name}…`, 0)
    try { const r = await api.importProject(f); hide(); message.success(`Imported as ${r.id} (${r.files} files)`); if (r.skipped.length) message.warning(`Skipped ${r.skipped.length} file(s) that cannot be imported: ${r.skipped.slice(0, 5).join(', ')}`, 8); go(`/p/${r.kind}/${r.id}`) }
    catch (e) { hide(); message.error((e as Error).message) } finally { setImporting(false) }
  }
  const load = () => api.library().then(d => { setData(d); setErr(null) }).catch(e => setErr(String(e.message)))
  useEffect(() => { load() }, [])
  useEffect(() => {
    sessionStorage.setItem('kcs.lib.q', search); sessionStorage.setItem('kcs.lib.type', type); sessionStorage.setItem('kcs.lib.couple', couple)
    sessionStorage.setItem('kcs.lib.filter', filter); sessionStorage.setItem('kcs.lib.sort', sort)
  }, [search, type, couple, filter, sort])

  const { tour, button } = usePageTour('dashboard', [
    { title: 'Welcome to Kawaii Chaos Studio 💙', description: 'Everything for your comic account in one place: strips, strip reels, music videos, lyric edits, captions and the posting log. This short tour shows you around.' },
    { target: 'menu', title: 'Main menu', description: 'Library (this page), Music videos & lyric edits, New project, Tools and Settings.', placement: 'right' },
    { target: 'stats', title: 'Account at a glance', description: 'Followers, what is posted and what is ready to post — read from posting_log.json.' },
    { target: 'filters', title: 'Find anything', description: 'Search by name or title, filter by type, couple or status (e.g. "Needs QA" or "Ready to post").' },
    { target: 'grid', title: 'Your projects', description: 'Each card shows the picture and its status: QA, reel, caption, posted. Click a card to open it.' },
    { target: 'new', title: 'Start something new', description: 'Make a new strip, music video or lyric edit — with your own pictures too.' },
    { target: 'jobs', title: 'Background jobs', description: 'Reel builds and renders keep running here while you work on other things.' },
  ], !!data)

  const couples = useMemo(() => [...new Set((data?.items ?? []).map(i => i.couple))].sort(), [data])
  const items = useMemo(() => {
    if (!data) return []
    const s = search.trim().toLowerCase(); const f = FILTERS.find(x => x.value === filter)!
    const out = data.items.filter(i =>
      (type === 'all' || i.type === type || (type === 'mv' && i.kind === 'mv')) &&
      (couple === 'all' || i.couple === couple) && f.test(i) &&
      (!s || `${i.id} ${i.title} ${i.couple}`.toLowerCase().includes(s)))
    const made = (i: Item) => i.created ?? i.mtime
    out.sort((a, b) => sort === 'newest' ? (a.kind === b.kind ? b.num - a.num : made(b) - made(a)) : sort === 'oldest' ? (a.kind === b.kind ? a.num - b.num : made(a) - made(b)) : b.mtime - a.mtime)
    return out
  }, [data, search, type, couple, filter, sort])

  const st = data?.stats
  return (
    <>
      <PageHeader title="Library" sub={st ? `${st.handle ?? ''} · ${st.strips} strips · ${st.music_videos} music videos` : 'loading…'}
        extra={<>{button}<Button icon={<ReloadOutlined />} onClick={load}>Refresh</Button>
          {canEdit && <Upload accept=".zip" showUploadList={false} beforeUpload={f => { importZip(f); return false }}>
            <Tooltip title="Add a project exported from a Studio (.zip) — it becomes a new project, nothing is overwritten"><Button icon={<ImportOutlined />} loading={importing}>Import</Button></Tooltip>
          </Upload>}
          <Button type="primary" icon={<PlusOutlined />} onClick={() => go('/new')} data-tour="new">New project</Button></>} />
      <div className="flex-1 overflow-auto p-5">
        {err && <Empty description={`Could not load the library: ${err}`} />}
        {!data && !err && <Skeleton active paragraph={{ rows: 8 }} />}
        {st && <Row gutter={[12, 12]} className="mb-4" data-tour="stats">
          <Col xs={12} lg={4}><Card size="small"><Statistic title={`Followers${st.followers_date ? ` (${st.followers_date})` : ''}`} value={st.followers ?? '–'} valueStyle={{ color: '#ff5d8f' }} /></Card></Col>
          <Col xs={12} lg={4}><Card size="small"><Statistic title="Posts marked posted" value={st.posted + st.mv_posted} suffix={<span className="text-xs opacity-60">({st.mv_posted} videos)</span>} /></Card></Col>
          <Col xs={12} lg={4}><Card size="small"><Statistic title="Ready, not posted yet" value={st.ready} valueStyle={{ color: '#ffd84d' }} /></Card></Col>
          <Col xs={12} lg={4}><Card size="small"><Statistic title="Strip reels built" value={st.reels} suffix={`/ ${st.strips_done}`} /></Card></Col>
          <Col xs={24} lg={8}><Card size="small" title={<span className="text-sm">Posts per couple</span>} styles={{ body: { paddingTop: 6, paddingBottom: 6 } }}
            extra={st.per_couple.length > 4 && <Button size="small" type="link" className="!px-0" onClick={() => setAllCouples(v => !v)}>{allCouples ? 'show less' : `show all ${st.per_couple.length}`}</Button>}>
            {(allCouples ? st.per_couple : st.per_couple.slice(0, 4)).map(c => (
              <div key={c.couple} className="flex items-center gap-2 text-xs cursor-pointer h-5" onClick={() => setCouple(c.couple)} title="filter by this couple">
                <span className="w-32 truncate">{c.couple}</span>
                <Progress className="flex-1 !m-0" size="small" showInfo={false} percent={100 * (c.posted + c.ready) / Math.max(1, ...st.per_couple.map(x => x.posted + x.ready))}
                  success={{ percent: 100 * c.posted / Math.max(1, ...st.per_couple.map(x => x.posted + x.ready)) }} />
                <span className="w-16 text-right opacity-70">{c.posted} / {c.posted + c.ready}</span>
              </div>))}
          </Card></Col>
        </Row>}
        {data && <>
          <Space wrap className="mb-4" data-tour="filters">
            <Input.Search allowClear placeholder="Search name, title, couple…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 260 }} />
            <Segmented value={type} onChange={v => setType(String(v))} options={[{ value: 'all', label: 'All' }, { value: 'strip', label: 'Strips' }, { value: 'mv', label: 'Music videos' }, { value: 'lyric_edit', label: 'Lyric edits' }]} />
            <Select value={couple} onChange={setCouple} style={{ width: 180 }} options={[{ value: 'all', label: 'Every couple' }, ...couples.map(c => ({ value: c, label: c }))]} />
            <Select value={filter} onChange={setFilter} style={{ width: 190 }} options={FILTERS.map(f => ({ value: f.value, label: f.label }))} />
            <Select value={sort} onChange={setSort} style={{ width: 150 }} options={[{ value: 'newest', label: 'Newest first' }, { value: 'oldest', label: 'Oldest first' }, { value: 'changed', label: 'Recently changed' }]} />
            <Typography.Text type="secondary">{items.length} shown</Typography.Text>
          </Space>
          {items.length === 0 ? <Empty description="Nothing matches these filters." className="mt-10"><Button onClick={() => { setSearch(''); setType('all'); setCouple('all'); setFilter('all') }}>Clear filters</Button></Empty> :
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(196px, 1fr))' }} data-tour="grid">
              {items.map(i => <ItemCard key={i.kind + i.id} i={i} />)}
            </div>}
        </>}
      </div>
      {tour}
    </>
  )
}

function ItemCard({ i }: { i: Item }) {
  const open = () => go(`/p/${i.kind}/${i.id}`)
  return (
    <Card hoverable size="small" onClick={open} styles={{ body: { padding: 10 } }}
      cover={<div className="aspect-[4/5] overflow-hidden bg-[#120f15] flex items-center justify-center">
        {i.thumb ? <img loading="lazy" src={api.thumbUrl(i.kind, i.id, i.thumb, 320, i.mtime)} className="w-full h-full object-cover object-top" draggable={false} />
          : <span className="text-xs opacity-50 px-4 text-center">No picture yet — open it to add one</span>}
      </div>}>
      <div className="flex items-center gap-1.5 text-[11px] opacity-60">
        <span>#{i.num}</span><span>·</span><span>{i.kind === 'strip' ? 'Strip' : i.type === 'lyric_edit' ? 'Lyric edit' : 'Music video'}</span>
        <span className="ml-auto truncate">{i.couple}</span>
      </div>
      <div className="font-display font-bold text-[15px] leading-tight my-1 line-clamp-2" title={i.title}>{i.headline}</div>
      <StatusTags i={i} />
    </Card>
  )
}
