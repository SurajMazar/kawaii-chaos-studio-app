import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Col, Empty, Image, Input, InputNumber, Popconfirm, Row, Select, Space, Typography } from 'antd'
import { ColumnHeightOutlined, IdcardOutlined } from '@ant-design/icons'
import { api } from '../api'
import { JobPanel, useJob } from '../components/Jobs'
import TextEditor from '../components/TextEditor'
import type { TabProps } from '../pages/PiecePage'

export default function SheetTab({ kind, id, item, reload, goTab }: TabProps) {
  const { message } = App.useApp()
  const [imgs, setImgs] = useState<{ path: string; mtime: number }[]>([])
  const [src, setSrc] = useState('charsheet.png')
  const [ratios, setRatios] = useState('1.0,0.84')
  const [ref, setRef] = useState<number | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [bust, setBust] = useState(Date.now())
  const { job, log } = useJob(jobId, j => { if (j.state === 'done') message.success('Heights fixed — compare below'); else if (j.state === 'error') message.error(j.error ?? 'failed'); loadImgs() })
  const loadImgs = () => api.images(kind, id).then(g => setImgs(g.groups.flatMap(x => x.items).filter(i => !i.path.startsWith('layout/')))).catch(() => {})
  useEffect(() => { loadImgs() }, [kind, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const out = job?.state === 'done' ? String(job.result?.output ?? '') : ''
  const n = ratios.split(',').filter(x => x.trim()).length

  return (
    <Row gutter={16}>
      <Col xs={24} xl={12}>
        <Card size="small" title="Character sheet (charsheet.png)" extra={<Button size="small" onClick={() => goTab('pictures')}>Choose another in Pictures</Button>}>
          {item.status.charsheet ? <div className="flex justify-center checker rounded"><Image src={api.fileUrl(kind, id, 'charsheet.png', bust)} style={{ maxHeight: 420 }} /></div>
            : <Empty image={<IdcardOutlined style={{ fontSize: 48, opacity: .4 }} />} description={<span>No character sheet yet. Every piece starts with a sheet of its cast in the outfits it uses.<br />Upload one in <b>Pictures</b> and press its <IdcardOutlined /> button.</span>} />}
        </Card>
        <Card size="small" className="!mt-3" title={<span><ColumnHeightOutlined /> Fix the heights on a sheet</span>}>
          <Typography.Paragraph type="secondary">GPT ignores height specs on chibi sheets, so this scales each figure (standing in a row) to an exact height. Give one height per figure, left to right, relative to the reference figure (1.0). House standard: Subaru 1.0, Rem 0.84.</Typography.Paragraph>
          <Space direction="vertical" className="w-full">
            <div><span className="label">Picture</span>
              <Select className="w-full" value={src} onChange={setSrc} options={imgs.map(i => ({ value: i.path, label: i.path }))} /></div>
            <div><span className="label">Heights, left to right</span>
              <Input value={ratios} onChange={e => setRatios(e.target.value)} placeholder="e.g. 0.92,0.84,1.0" /></div>
            <div><span className="label">Reference figure (optional)</span><br />
              <InputNumber min={0} max={Math.max(0, n - 1)} value={ref} onChange={v => setRef(v === null ? null : Number(v))} placeholder="the one at 1.0" />
              <Typography.Text type="secondary" className="text-xs ml-2">0 = first figure on the left</Typography.Text></div>
            <Button type="primary" disabled={!src || !ratios.trim() || job?.state === 'running'} onClick={async () => {
              try { setJobId((await api.sheetHeights(kind, id, src, ratios, ref)).id) } catch (e) { message.error((e as Error).message) }
            }}>Fix heights</Button>
          </Space>
          {job && <div className="mt-3"><JobPanel job={job} log={log} /></div>}
          {out && <>
            <div className="grid grid-cols-2 gap-2 mt-3">
              <div><span className="label">Before</span><Image src={api.fileUrl(kind, id, src, bust)} className="checker rounded" /></div>
              <div><span className="label">After ({out})</span><Image src={api.fileUrl(kind, id, out, Date.now())} className="checker rounded" /></div>
            </div>
            <Popconfirm title="Use the fixed sheet as charsheet.png?" description="The old one is kept in .studio_history/." onConfirm={async () => {
              try { await api.setRole(kind, id, out, 'charsheet'); setBust(Date.now()); message.success('charsheet.png updated — QA it again'); reload() } catch (e) { message.error((e as Error).message) }
            }}><Button className="!mt-2" type="primary">Use as charsheet.png</Button></Popconfirm>
          </>}
        </Card>
      </Col>
      <Col xs={24} xl={12}>
        <Alert className="!mb-3" type="info" showIcon message="Sheet prompt" description="The prompt used for the character sheet (front + back view, height guide, key props). Attach the style master in a fresh chat, QA the sheet like a strip, and attach the sheet to every frame prompt." />
        <TextEditor kind={kind} id={id} name="charsheet_prompt.txt" markdown={false} height="calc(100vh - 470px)" placeholder="Write or paste the character-sheet prompt here…" />
      </Col>
    </Row>
  )
}
