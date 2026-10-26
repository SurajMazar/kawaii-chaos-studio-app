import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Card, Checkbox, Col, Empty, Image, Input, Row, Select, Space, Steps, Tooltip, Typography, Skeleton } from 'antd'
import { CopyOutlined, DownloadOutlined, ExportOutlined, PictureOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { TabProps } from '../pages/PiecePage'

type Parts = Awaited<ReturnType<typeof api.promptParts>>

export default function PromptTab({ id, reload, goTab }: TabProps) {
  const { message, modal } = App.useApp()
  const [parts, setParts] = useState<Parts | null>(null)
  const [locks, setLocks] = useState<string[]>([])
  const [useRule, setUseRule] = useState(true)
  const [useLayout, setUseLayout] = useState(true)
  const [text, setText] = useState('')
  const [savedText, setSavedText] = useState('')
  const [refs, setRefs] = useState<{ name: string; path: string }[]>([])
  const [style, setStyle] = useState('style_ref.png')
  const [board, setBoard] = useState<{ path: string; mtime: number } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.promptParts(id).then(p => {
      setParts(p); setLocks(p.locks.filter(l => l.default).map(l => l.key)); setStyle(p.style_ref || 'style_ref.png')
      setText(p.prompt_final); setSavedText(p.prompt_final)
    }).catch(e => message.error(e.message))
    api.refs().then(setRefs).catch(() => {})
    api.files('strip', id, '').then(f => { const b = f.entries.find(e => e.name === 'studio_board.jpg'); if (b) setBoard({ path: b.path, mtime: b.mtime }) }).catch(() => {})
  }, [id, message])

  const built = useMemo(() => {
    if (!parts) return ''
    const out = [parts.header]
    if (useRule && parts.couple_rule) out.push(parts.couple_rule)
    if (useLayout && parts.layout) out.push(parts.layout)
    if (parts.panels.length) out.push(parts.panels.map(p => `Panel ${p.n}: ${p.text}`).join('\n'))
    for (const l of parts.locks) if (locks.includes(l.key)) out.push(l.text)
    return out.filter(Boolean).join('\n\n')
  }, [parts, locks, useRule, useLayout])

  useEffect(() => { if (parts && !parts.prompt_final && !text) setText(built) }, [built, parts]) // eslint-disable-line react-hooks/exhaustive-deps

  const rebuild = () => text && text !== built
    ? modal.confirm({ title: 'Rebuild the prompt from the parts?', content: 'Your edits in the prompt box are replaced.', okText: 'Rebuild', onOk: () => setText(built) })
    : setText(built)
  const copy = async () => { await navigator.clipboard.writeText(text); message.success('Prompt copied — paste it into ChatGPT') }
  const save = async () => {
    try { await api.saveText('strip', id, 'prompt_final.txt', text); setSavedText(text); message.success('Saved as prompt_final.txt'); reload() }
    catch (e) { message.error((e as Error).message) }
  }
  const makeBoard = async () => {
    setBusy(true)
    try { const b = await api.board('strip', id, style); setBoard({ path: b.path, mtime: b.mtime }); message.success(`Reference board ready (parts ${b.parts.join(' + ')})`) }
    catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  if (!parts) return <Skeleton active />

  return (
    <Row gutter={16}>
      <Col xs={24} xl={15}>
        <Card size="small" title="The prompt" extra={<Space>
          <Tooltip title="Put the prompt together again from the parts below"><Button size="small" icon={<SyncOutlined />} onClick={rebuild}>Rebuild</Button></Tooltip>
          <Button size="small" icon={<SaveOutlined />} disabled={text === savedText} onClick={save}>Save as prompt_final.txt</Button>
          <Button size="small" type="primary" icon={<CopyOutlined />} onClick={copy} disabled={!text}>Copy prompt</Button>
        </Space>}>
          {!parts.panels.length && <Alert className="!mb-2" type="warning" showIcon message="The script has no numbered panels yet (1. 2. 3. …)." action={<Button size="small" onClick={() => goTab('script')}>Write the script</Button>} />}
          <Input.TextArea value={text} onChange={e => setText(e.target.value)} className="!font-mono !text-[12.5px]" style={{ height: 'calc(100vh - 420px)', minHeight: 300 }} />
          <Typography.Text type="secondary" className="text-xs">Replace the [CHARACTER A] / [SERIES] placeholders and add each character's canon look (couples.md). You can edit everything here.</Typography.Text>
        </Card>
        <Card size="small" title="Parts" className="!mt-3">
          <Space direction="vertical" className="w-full">
            <Checkbox checked={useLayout} disabled={!parts.layout} onChange={e => setUseLayout(e.target.checked)}>Layout description {parts.layout ? '' : '(make a layout first)'}</Checkbox>
            <Checkbox checked={useRule} disabled={!parts.couple_rule} onChange={e => setUseRule(e.target.checked)}>COUPLE RULE {parts.couple_rule ? `(${parts.couple})` : '(couple unknown)'}</Checkbox>
            <div className="label mt-1">Locks from style.md</div>
            <Checkbox.Group value={locks} onChange={v => setLocks(v as string[])} className="!flex !flex-col gap-1"
              options={parts.locks.map(l => ({ value: l.key, label: <Tooltip title={<span className="text-xs whitespace-pre-wrap">{l.text.slice(0, 600)}</span>} placement="right"><span>{l.title}</span></Tooltip> }))} />
            <Typography.Text type="secondary" className="text-xs">After changing parts press <b>Rebuild</b>.</Typography.Text>
          </Space>
        </Card>
      </Col>
      <Col xs={24} xl={9}>
        <Card size="small" title="How to use it in ChatGPT">
          <Steps direction="vertical" size="small" current={-1} items={[
            { title: 'Build the reference board', description: 'One picture with A = our art style, B = character sheet, C = the layout.' },
            { title: 'Open a NEW ChatGPT chat', description: 'Attach the board, paste the prompt, ask for ONE image.' },
            { title: 'Check the conversation record', description: 'Make sure the board really is attached (uploads get dropped silently).' },
            { title: 'Bring the picture back', description: <span>Pictures tab → <b>Import from Downloads</b>, then QA.</span> },
          ]} />
          <Space wrap>
            <Button icon={<ExportOutlined />} href={parts.chatgpt_url || 'https://chatgpt.com/'} target="_blank">Open ChatGPT</Button>
            <Button onClick={() => goTab('pictures')}>Go to Pictures →</Button>
          </Space>
        </Card>
        <Card size="small" title="Reference board" className="!mt-3" extra={board && <Space>
          <Tooltip title="Download"><Button size="small" icon={<DownloadOutlined />} href={api.downloadUrl('strip', id, board.path)} /></Tooltip>
        </Space>}>
          <Space.Compact className="w-full mb-2">
            <Select value={style} onChange={setStyle} className="flex-1" options={refs.map(r => ({ value: r.name, label: `Style: ${r.name}` }))} />
            <Button type="primary" icon={<PictureOutlined />} loading={busy} onClick={makeBoard}>{board ? 'Rebuild board' : 'Build board'}</Button>
          </Space.Compact>
          {!parts.has_charsheet && <Alert className="!mb-2" type="warning" showIcon message="No character sheet yet — the board will only have the style and layout." action={<Button size="small" onClick={() => goTab('sheet')}>Sheet</Button>} />}
          {board ? <Image src={api.fileUrl('strip', id, board.path, board.mtime)} className="rounded" /> : <Empty description="Build the board to attach it in ChatGPT." />}
        </Card>
      </Col>
    </Row>
  )
}
