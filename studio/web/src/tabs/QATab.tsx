import { useEffect, useState } from 'react'
import { Alert, App, Badge, Button, Card, Checkbox, Col, Empty, Image, Input, List, Popconfirm, Row, Segmented, Space, Tag, Tooltip, Typography, Skeleton } from 'antd'
import { CheckCircleFilled, CloseCircleOutlined, DiffOutlined, SafetyCertificateOutlined, StopOutlined } from '@ant-design/icons'
import { api } from '../api'
import TextEditor from '../components/TextEditor'
import ImageCompare, { type CmpSource } from '../components/ImageCompare'
import type { TabProps } from '../pages/PiecePage'
import type { QaCheck, QaTarget } from '../types'

const STATUS: Record<string, [string, string]> = {
  pass: ['green', 'PASS'], stale: ['orange', 'changed since PASS'], none: ['gold', 'not checked'], revoked: ['red', 'revoked'],
  nofile: ['default', 'no qa.md'], noimage: ['default', 'missing'],
}

export default function QATab({ kind, id, reload, goTab }: TabProps) {
  const { message } = App.useApp()
  const [data, setData] = useState<{ exists: boolean; text: string; checklist: QaCheck[]; targets: QaTarget[] } | null>(null)
  const [target, setTarget] = useState<string>('')
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [stranger, setStranger] = useState('')
  const [view, setView] = useState('check')
  const [cmp, setCmp] = useState(false)
  const [refs, setRefs] = useState<CmpSource[]>([])
  const [ver, setVer] = useState(0)
  const load = () => api.qa(kind, id).then(d => { setData(d); setTarget(t => t && d.targets.some(x => x.file === t) ? t : d.targets[0]?.file ?? '') }).catch(e => message.error(e.message))
  useEffect(() => { load(); api.refs().then(r => setRefs(r.map(x => ({ label: `references/${x.name}`, url: api.rootUrl(x.path) })))).catch(() => {}) }, [kind, id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setChecks({}); setNotes({}); setStranger('') }, [target])
  if (!data) return <Skeleton active />
  const t = data.targets.find(x => x.file === target)
  const all = data.checklist.length > 0 && data.checklist.every(c => checks[c.key])
  const failed = data.checklist.filter(c => !checks[c.key] && notes[c.key]?.trim())
  const after = async () => { await load(); await reload(); setVer(v => v + 1) }

  const pass = async () => {
    try { await api.qaPass(kind, id, target, checks, notes, stranger); message.success(`PASS written for ${target}`); await after() }
    catch (e) { message.error((e as Error).message) }
  }
  const fail = async () => {
    try { await api.qaFail(kind, id, target, Object.fromEntries(failed.map(c => [c.key, notes[c.key]])), stranger); message.info('FAIL written to qa.md — fix the prompt and redraw, or reject the picture'); await after() }
    catch (e) { message.error((e as Error).message) }
  }

  return (
    <>
      <Segmented className="!mb-3" value={view} onChange={v => setView(String(v))} options={[{ value: 'check', label: 'Check a picture' }, { value: 'file', label: 'qa.md (full notes)' }]} />
      {view === 'file' ? <TextEditor key={ver} kind={kind} id={id} name="qa.md" onSaved={after} /> :
        <Row gutter={16}>
          <Col xs={24} xl={7}>
            <Card size="small" title="Pictures to check">
              {data.targets.length === 0 ? <Empty description="Nothing to check yet."><Button onClick={() => goTab('pictures')}>Add pictures</Button></Empty> :
                <List size="small" dataSource={data.targets} renderItem={x => (
                  <List.Item onClick={() => setTarget(x.file)} className={`cursor-pointer !px-2 rounded ${x.file === target ? 'bg-[#2a2431]' : ''}`}>
                    <div className="flex items-center gap-2 w-full">
                      {x.sha ? <img src={api.thumbUrl(kind, id, x.file, 80)} className="w-10 h-10 object-cover rounded" />
                        : <div className="w-10 h-10 rounded bg-[#2a2431] grid place-items-center text-xs opacity-50">?</div>}
                      <span className="text-sm truncate flex-1">{x.file}</span>
                      <Tag color={STATUS[x.status]?.[0]}>{STATUS[x.status]?.[1]}</Tag>
                    </div>
                  </List.Item>)} />}
            </Card>
            <Alert className="!mt-3" type="warning" showIcon message="The QA gate"
              description={<span>Judge each picture <b>alone</b> — never “the better of two”. Unsure = FAIL. Only when every check passes, press <b>Mark PASS</b>: it writes <code>PASS &lt;sha1&gt;</code> into qa.md and the reel can be built.</span>} />
          </Col>
          <Col xs={24} xl={9}>
            {t && <Card size="small" title={<Space>{t.file}<Tag color={STATUS[t.status]?.[0]}>{STATUS[t.status]?.[1]}</Tag></Space>}
              extra={<Tooltip title="Side by side with the style master (QA check G)"><Button size="small" icon={<DiffOutlined />} onClick={() => setCmp(true)}>Compare</Button></Tooltip>}>
              {t.sha ? <>
                <div className="checker rounded flex justify-center"><Image src={api.fileUrl(kind, id, t.file, ver + 1)} style={{ maxHeight: 'calc(100vh - 380px)' }} /></div>
                <Typography.Text type="secondary" className="text-xs">Click the picture to zoom every panel at full size. sha1 {t.sha.slice(0, 12)}</Typography.Text>
              </> : <Empty description={`There is no ${t.file} yet.`}><Button onClick={() => goTab('pictures')}>Add it in Pictures</Button></Empty>}
              {t.status === 'pass' && <Popconfirm title="Revoke this PASS?" description="The PASS line becomes REVOKED; the reel can't be rebuilt until it passes again."
                onConfirm={async () => { try { await api.qaRevoke(kind, id, t.file); message.success('Revoked'); await after() } catch (e) { message.error((e as Error).message) } }}>
                <Button className="!mt-2" danger size="small" icon={<StopOutlined />}>Revoke PASS</Button></Popconfirm>}
            </Card>}
          </Col>
          <Col xs={24} xl={8}>
            {t && <Card size="small" title={<span><SafetyCertificateOutlined /> Checklist (qa_rules.md)</span>}
              extra={<Badge count={`${data.checklist.filter(c => checks[c.key]).length}/${data.checklist.length}`} color={all ? '#7ed69a' : '#3a3342'} />}>
              <Typography.Text strong className="text-xs">What does a stranger see? (write it from the picture, panel by panel, before re-reading the script)</Typography.Text>
              <Input.TextArea className="!mb-2 !mt-1" autoSize={{ minRows: 2, maxRows: 5 }} value={stranger} onChange={e => setStranger(e.target.value)} placeholder="P1 … P2 … P3 … P4 …" />
              <div className="max-h-[calc(100vh-520px)] min-h-[200px] overflow-auto pr-1">
                {data.checklist.map(c => (
                  <div key={c.key} className="py-1.5 border-b border-line/50">
                    <Checkbox checked={!!checks[c.key]} onChange={e => setChecks(s => ({ ...s, [c.key]: e.target.checked }))}>
                      <Tooltip title={<span className="text-xs">{c.text}</span>} placement="left"><span><b>{c.key}.</b> {c.title}</span></Tooltip>
                    </Checkbox>
                    <Input size="small" variant="borderless" className="!pl-6 !text-xs" placeholder={checks[c.key] ? 'note (optional)' : 'why it fails (for a FAIL)'}
                      value={notes[c.key] ?? ''} onChange={e => setNotes(s => ({ ...s, [c.key]: e.target.value }))} />
                  </div>
                ))}
              </div>
              <Space className="mt-2 pt-3 border-t border-line w-full" wrap>
                <Popconfirm title={`Mark ${t.file} as PASS?`} description="Every item really passes, judged alone?" disabled={!all} onConfirm={pass}>
                  <Tooltip title={all ? 'Write PASS <sha1> into qa.md' : 'Tick every check first'}><Button type="primary" icon={<CheckCircleFilled />} disabled={!all || t.status === 'pass'}>Mark PASS</Button></Tooltip>
                </Popconfirm>
                <Tooltip title="Untick the failing checks and write why — then save the FAIL into qa.md"><Button danger icon={<CloseCircleOutlined />} disabled={!failed.length} onClick={fail}>Write FAIL ({failed.length})</Button></Tooltip>
              </Space>
              {t.status === 'pass' && kind === 'strip' && t.file === 'strip.png' && <Alert className="!mt-3" type="success" showIcon message="This strip passed QA." action={<Button size="small" type="primary" onClick={() => goTab('reel')}>Build the reel →</Button>} />}
            </Card>}
          </Col>
        </Row>}
      {cmp && t && <ImageCompare open onClose={() => setCmp(false)} left={{ label: t.file, url: api.fileUrl(kind, id, t.file, ver + 1) }}
        sources={refs} defaultRight={refs.find(r => r.label.endsWith('style_ref_master.jpg'))?.url} />}
    </>
  )
}
