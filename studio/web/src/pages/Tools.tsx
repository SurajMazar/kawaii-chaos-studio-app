import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Empty, Input, Popconfirm, Row, Space, Typography } from 'antd'
import { BookOutlined, CompressOutlined, DownloadOutlined, EyeOutlined, ImportOutlined, PlayCircleOutlined, SyncOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'
import { PageHeader } from '../App'
import { JobPanel, useJob } from '../components/Jobs'
import { usePageTour } from '../components/Tours'
import type { Tool } from '../types'

const ICONS: Record<string, React.ReactNode> = { book: <BookOutlined />, eye: <EyeOutlined />, compress: <CompressOutlined />, video: <VideoCameraOutlined />, sync: <SyncOutlined />, import: <ImportOutlined /> }
/** projects/<id>/x or music_videos/<id>/x -> a URL the server serves */
function repoFileUrl(p: string) {
  const [top, id, ...rest] = p.split('/')
  return api.fileUrl(top === 'projects' ? 'strip' : 'mv', id, rest.join('/'), Date.now())
}
const HEAVY = new Set(['build_missing', 'update_trackers', 'upload_encode'])

export default function Tools() {
  const [tools, setTools] = useState<Tool[] | null>(null)
  useEffect(() => { api.tools().then(setTools).catch(() => setTools([])) }, [])
  const { tour, button } = usePageTour('tools', [
    { title: 'Tools', description: 'The repo scripts as buttons. Each one runs in the background with its progress and log; the Jobs button keeps track of them.' },
    { target: 'tool-make_pdf', title: 'Example: the PDF book', description: 'Press Run, watch the log, then download the result.' },
  ], !!tools)
  return (
    <>
      <PageHeader title="Tools" sub="Scripts from scripts/ — run as background jobs" extra={button} />
      <div className="flex-1 overflow-auto p-5">
        {!tools ? null : tools.length === 0 ? <Empty description="No tools found in scripts/." /> :
          <Row gutter={[16, 16]}>{tools.map(t => <Col key={t.key} xs={24} lg={12} xxl={8}><ToolCard t={t} /></Col>)}</Row>}
      </div>
      {tour}
    </>
  )
}

function ToolCard({ t }: { t: Tool }) {
  const { message } = App.useApp()
  const [args, setArgs] = useState<Record<string, string>>(Object.fromEntries(t.args.map(a => [a.name, a.default])))
  const [jobId, setJobId] = useState<string | null>(null)
  const { job, log, running } = useJob(jobId, j => { if (j.state === 'done') message.success(`${t.title}: done`); else if (j.state === 'error') message.error(`${t.title}: ${j.error}`) })
  const run = async () => { try { setJobId((await api.runTool(t.key, args)).id) } catch (e) { message.error((e as Error).message) } }
  const missing = t.args.some(a => a.required && !args[a.name]?.trim())
  const runBtn = <Button type="primary" icon={<PlayCircleOutlined />} disabled={missing || (running && !!jobId)} onClick={HEAVY.has(t.key) ? undefined : run}>Run</Button>
  const res = job?.state === 'done' ? job.result : null
  return (
    <Card size="small" title={<Space>{ICONS[t.icon]}{t.title}</Space>} data-tour={`tool-${t.key}`} extra={<Typography.Text type="secondary" className="text-xs">{t.script}</Typography.Text>}>
      <Typography.Paragraph type="secondary">{t.desc}</Typography.Paragraph>
      {t.args.map(a => <div key={a.name} className="mb-2"><span className="label">{a.label}</span>
        <Input value={args[a.name]} onChange={e => setArgs(s => ({ ...s, [a.name]: e.target.value }))} placeholder={a.kind === 'image' ? 'projects/001_rainy_day/strip.png' : ''} /></div>)}
      {HEAVY.has(t.key) ? <Popconfirm title={`Run "${t.title}"?`} description="This can change many files (backups are kept for the tracker files)." onConfirm={run}>{runBtn}</Popconfirm> : runBtn}
      {job && <div className="mt-3"><JobPanel job={job} log={log} /></div>}
      {res?.download ? <Button className="!mt-2" icon={<DownloadOutlined />} href={api.rootUrl(String(res.download), true)}>Download {String(res.download).split('/').pop()}</Button> : null}
      {res?.output && t.key === 'style_check' ? <img className="mt-2 w-full rounded" src={repoFileUrl(String(res.output))} /> : null}
    </Card>
  )
}
