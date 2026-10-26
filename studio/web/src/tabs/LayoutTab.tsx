import { useEffect, useState } from 'react'
import { App, Button, Card, Checkbox, Col, Empty, Image, InputNumber, Row, Segmented, Space, Tooltip, Typography } from 'antd'
import { CopyOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { TabProps } from '../pages/PiecePage'

export default function LayoutTab({ id, reload, goTab }: TabProps) {
  const { message, modal } = App.useApp()
  const [info, setInfo] = useState<{ exists: boolean; text: string; mtime: number | null; panels: number } | null>(null)
  const [panels, setPanels] = useState(4)
  const [seed, setSeed] = useState<number | null>(null)
  const [punch, setPunch] = useState(true)
  const [busy, setBusy] = useState(false)
  const load = () => api.layout(id).then(i => { setInfo(i); if (i.panels) setPanels(i.panels) }).catch(e => message.error(e.message))
  useEffect(() => { load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  const make = async () => {
    setBusy(true)
    try { await api.makeLayout(id, panels, seed, punch); await load(); await reload(); message.success('New layout ready') }
    catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  const confirmMake = () => info?.exists
    ? modal.confirm({ title: 'Make a new layout?', content: 'The current layout is replaced (a copy is kept in layout/.studio_history/).', okText: 'Make a new one', onOk: make })
    : make()

  return (
    <Row gutter={16}>
      <Col xs={24} lg={9}>
        <Card title="Make a panel layout" size="small">
          <Typography.Paragraph type="secondary">A fresh, random comic-page layout (slanted gutters, uneven panels) for every strip. ChatGPT follows the wireframe; if you draw the strip yourself you can skip this.</Typography.Paragraph>
          <Space direction="vertical" className="w-full">
            <div><span className="label">Panels</span><br />
              <Segmented value={panels} onChange={v => setPanels(Number(v))} options={[1, 2, 3, 4, 5, 6].map(n => ({ value: n, label: String(n) }))} /></div>
            <div><Tooltip title="Same number = same layout. Leave empty for a surprise."><span className="label cursor-help">Seed (optional)</span></Tooltip><br />
              <Space.Compact>
                <InputNumber value={seed} onChange={v => setSeed(v === null ? null : Number(v))} placeholder="random" min={0} />
                <Button icon={<ReloadOutlined />} onClick={() => setSeed(Math.floor(Math.random() * 1000))}>Roll</Button>
              </Space.Compact></div>
            <Checkbox checked={punch} onChange={e => setPunch(e.target.checked)}>Keep the last panel big for the punchline</Checkbox>
            <Button type="primary" icon={<ThunderboltOutlined />} loading={busy} onClick={confirmMake} block>{info?.exists ? 'Make a new layout' : 'Make the layout'}</Button>
          </Space>
        </Card>
        {info?.exists && <Card title="Layout description" size="small" className="!mt-3"
          extra={<Button size="small" icon={<CopyOutlined />} onClick={() => { navigator.clipboard.writeText(info.text); message.success('Copied') }}>Copy</Button>}>
          <Typography.Paragraph className="!mb-2">{info.text}</Typography.Paragraph>
          <Typography.Text type="secondary" className="text-xs">This text goes into the prompt automatically (Prompt tab).</Typography.Text>
        </Card>}
      </Col>
      <Col xs={24} lg={15}>
        <Card size="small" title="Wireframe (layout.png)" extra={info?.exists && <Button size="small" type="link" onClick={() => goTab('prompt')}>Next: Prompt →</Button>}>
          {info?.exists ? <div className="flex justify-center"><Image src={api.fileUrl('strip', id, 'layout/layout.png', info.mtime ?? 0)} style={{ maxHeight: 'calc(100vh - 340px)' }} /></div>
            : <Empty description="No layout yet — pick the number of panels and press Make the layout." />}
        </Card>
      </Col>
    </Row>
  )
}
