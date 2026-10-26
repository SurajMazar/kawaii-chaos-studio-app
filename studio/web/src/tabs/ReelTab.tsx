import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Col, Descriptions, Empty, Image, Popconfirm, Result, Row, Space, Tooltip, Typography } from 'antd'
import { DownloadOutlined, ExportOutlined, PlayCircleOutlined, ThunderboltOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'
import { go } from '../router'
import { JobPanel, useJob } from '../components/Jobs'
import type { TabProps } from '../pages/PiecePage'

type Status = Awaited<ReturnType<typeof api.reelStatus>>

export default function ReelTab({ id, item, reload, goTab }: TabProps) {
  const { message } = App.useApp()
  const [st, setSt] = useState<Status | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const { job, log } = useJob(jobId, j => { load(); reload(); if (j.state === 'done') message.success('Strip reel ready'); if (j.state === 'error') message.error(j.error ?? 'Build failed') })
  const load = () => api.reelStatus(id).then(setSt).catch(e => message.error(e.message))
  useEffect(() => { load(); api.jobs(true).then(js => { const r = js.find(j => j.ref === `strip/${id}` && j.kind === 'reel'); if (r) setJobId(r.id) }).catch(() => {}) }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  const qaOk = item.status.qa === 'pass'
  const running = !!job && (job.state === 'running' || job.state === 'queued')
  const build = async () => { try { setJobId((await api.reelAuto(id)).id) } catch (e) { message.error((e as Error).message) } }
  const exp = async (p: string) => { try { const r = await api.exportFile(p); message.success(`Copied to ${r.path}`) } catch (e) { message.error((e as Error).message) } }
  const reel = st?.reel, img = st?.image_png ?? st?.image_jpg

  if (!item.status.strip) return <Result status="info" title="No strip picture yet" subTitle="Choose the final strip in Pictures first, then QA it." extra={<Button type="primary" onClick={() => goTab('pictures')}>Go to Pictures</Button>} />
  return (
    <Row gutter={16}>
      <Col xs={24} xl={10}>
        {!qaOk && <Alert className="!mb-3" type="error" showIcon message="QA PASS missing"
          description="The reel is only built for a strip that passed QA: qa.md needs a PASS line for the current strip.png." action={<Button onClick={() => goTab('qa')}>Do the QA</Button>} />}
        <Card size="small" title="Build the strip reel">
          <Typography.Paragraph type="secondary">A silent reel that shows the strip panel by panel and only reveals the whole strip at the end. The song is added in the Instagram app.</Typography.Paragraph>
          <Space direction="vertical" className="w-full">
            <Popconfirm title="Build automatically?" description="Panels are found again and the timing is reset to the defaults — edits made in the Reel editor are replaced." onConfirm={build} disabled={!qaOk || running}>
              <Tooltip title="Find the panels, make the storyboard, render and encode — about 2 minutes"><Button type="primary" icon={<ThunderboltOutlined />} block disabled={!qaOk || running}>Build reel (automatic)</Button></Tooltip>
            </Popconfirm>
            <Button icon={<VideoCameraOutlined />} block onClick={() => go(`/reel/${id}`)}>Open the reel editor (fix panels, timing, camera)</Button>
          </Space>
          {job && <div className="mt-3"><JobPanel job={job} log={log} /></div>}
        </Card>
        <Card size="small" className="!mt-3" title="Upload files (upload/)">
          {!reel && !img ? <Empty description="Nothing built yet." /> :
            <Descriptions size="small" column={1} items={[
              ...(reel ? [{ key: 'r', label: 'Reel', children: <Space wrap><span>{(reel.size / 1e6).toFixed(1)} MB · {new Date(reel.mtime * 1000).toLocaleString()}</span>
                <Button size="small" icon={<DownloadOutlined />} href={api.rootUrl(reel.path, true)}>Download</Button>
                <Tooltip title="Copy into your export folder (Settings)"><Button size="small" icon={<ExportOutlined />} onClick={() => exp(reel.path)}>Export</Button></Tooltip></Space> }] : []),
              ...(img ? [{ key: 'i', label: 'Strip image', children: <Space wrap><span>{(img.size / 1e6).toFixed(1)} MB</span>
                <Button size="small" icon={<DownloadOutlined />} href={api.rootUrl(img.path, true)}>Download</Button>
                <Button size="small" icon={<ExportOutlined />} onClick={() => exp(img.path)}>Export</Button></Space> }] : []),
            ]} />}
          <Typography.Paragraph type="secondary" className="!mt-2 !mb-0 text-xs">Post the reel from the Instagram <b>app</b>: + → Reel → pick the video → Audio → search the song → original audio to 0 → caption → Share to Facebook OFF.</Typography.Paragraph>
          {reel && <Button type="link" className="!px-0" onClick={() => goTab('post')}>Next: caption & post →</Button>}
        </Card>
      </Col>
      <Col xs={24} xl={14}>
        <Card size="small" title={<span><PlayCircleOutlined /> Result</span>}>
          {reel ? <div className="flex gap-3 justify-center">
            <video key={reel.mtime} src={api.rootUrl(reel.path) + `?v=${Math.round(reel.mtime)}`} controls className="rounded-lg bg-black" style={{ maxHeight: 'calc(100vh - 320px)' }} />
            {img && <Image src={api.rootUrl(img.path)} style={{ maxHeight: 'calc(100vh - 320px)' }} />}
          </div> : <Empty description="The finished reel plays here." />}
        </Card>
      </Col>
    </Row>
  )
}
