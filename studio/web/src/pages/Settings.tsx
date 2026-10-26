import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Form, Input, InputNumber, List, Radio, Row, Select, Space, Tabs, Typography, Upload } from 'antd'
import { CloudServerOutlined, HeartOutlined, FontSizeOutlined, SaveOutlined, SlidersOutlined, UploadOutlined, RedoOutlined } from '@ant-design/icons'
import { api } from '../api'
import { PageHeader } from '../App'
import { useCan } from '../auth'
import Integrations from '../components/Integrations'
import ElevenLabsCard from '../components/ElevenLabs'
import CouplesEditor from '../components/Couples'
import { resetTours, usePageTour } from '../components/Tours'
import { go } from '../router'
import { setAppSettings } from '../settings'
import type { Settings } from '../types'

export default function SettingsPage({ tab }: { tab?: string }) {
  const isAdmin = useCan('admin')
  const active = tab === 'integrations' && isAdmin ? 'integrations' : tab === 'couples' ? 'couples' : 'defaults'
  return (
    <>
      <PageHeader title="Settings" sub={active === 'integrations' ? 'Storage (local folder, S3, R2) and ElevenLabs voices' : 'Defaults, fonts and tours'} />
      <div className="flex-1 overflow-auto px-5 pb-5">
        <Tabs activeKey={active} onChange={k => go(k === 'defaults' ? '/settings' : `/settings/${k}`)} items={[
          { key: 'defaults', label: <span><SlidersOutlined /> Defaults</span>, children: <DefaultsTab /> },
          { key: 'couples', label: <span><HeartOutlined /> Couples</span>, children: <CouplesEditor /> },
          ...(isAdmin ? [{ key: 'integrations', label: <span data-tour="settings-integrations"><CloudServerOutlined /> Integrations</span>, children: <div className="flex flex-col gap-3"><Integrations /><ElevenLabsCard /></div> }] : []),
        ]} />
      </div>
    </>
  )
}

function DefaultsTab() {
  const isAdmin = useCan('admin'), isEditor = useCan('editor')
  const { message } = App.useApp()
  const [form] = Form.useForm<Settings>()
  const artSource = Form.useWatch('art_source', form)
  const [loaded, setLoaded] = useState(false)
  const [fonts, setFonts] = useState<{ name: string; path: string; size: number }[]>([])
  const [refs, setRefs] = useState<{ name: string }[]>([])
  const [sample, setSample] = useState('Kawaii Chaos')
  const [local, setLocal] = useState(true)
  const loadFonts = () => api.fonts().then(setFonts).catch(() => {})
  useEffect(() => {
    api.settings().then(s => { form.setFieldsValue(s); setLocal(s.local_features !== false); setLoaded(true) }).catch(e => message.error(e.message))
    loadFonts(); api.refs().then(setRefs).catch(() => {})
  }, [form, message])
  const { tour, button } = usePageTour('settings', [
    { title: 'Settings', description: 'Your defaults: handle, hashtags, where things are exported, and which Python runs the scripts. Admins also find Integrations (where files are stored) here.' },
    ...(isAdmin ? [{ target: 'settings-integrations', title: 'Integrations', description: 'Choose where the Studio keeps its files: this computer, Amazon S3, Cloudflare R2 or another S3-compatible service.' }] : []),
    { target: 'set-form', title: 'Defaults', description: 'The handle/signature is used for new lyric edits; the hashtags are added with one click in the Post tab.' },
    { target: 'set-fonts', title: 'Your own fonts', description: 'Upload .ttf/.otf fonts; pick them per lyric edit in the editor\'s "Fonts & colours" panel.' },
  ], loaded)

  return (
    <>
      <div className="flex justify-end mb-3">{button}</div>
      <div>
        <Row gutter={16}>
          <Col xs={24} xl={13}>
            <Card size="small" title="Defaults" data-tour="set-form" extra={!isAdmin && <Typography.Text type="secondary" className="text-xs">only admins can change these</Typography.Text>}>
              <Form form={form} layout="vertical" disabled={!isAdmin} onFinish={async v => { try { const saved = await api.saveSettings(v); form.setFieldsValue(saved); setAppSettings(saved); message.success('Settings saved') } catch (e) { message.error((e as Error).message) } }}>
                <div className="grid grid-cols-2 gap-x-4">
                  <Form.Item name="handle" label="Instagram handle"><Input placeholder="@your.account" /></Form.Item>
                  <Form.Item name="signature" label="End-card text for new lyric edits" tooltip="Shown on the black end card; change it per edit in the editor"><Input /></Form.Item>
                </div>
                <Form.Item name="art_source" label="Where do the pictures come from?" tooltip="Changes which steps a strip shows. You can switch any time; nothing is deleted.">
                  <Radio.Group options={[
                    { value: 'own', label: 'I draw them myself (or another app)' },
                    { value: 'chatgpt', label: 'ChatGPT (prompt + reference board)' },
                  ]} />
                </Form.Item>
                <Form.Item name="hashtags" label="Default hashtags" tooltip="Added by '+ hashtags' in the Post tab and to new strip scripts"><Input.TextArea autoSize={{ minRows: 2 }} /></Form.Item>
                <div className="grid grid-cols-2 gap-x-4">
                  <Form.Item name="style_ref" label="Style reference for boards"><Select options={refs.map(r => ({ value: r.name, label: r.name }))} /></Form.Item>
                  <Form.Item name="reel_seconds_per_panel" label="Strip reel: seconds per panel" tooltip="Used when the reel editor makes a new storyboard"><InputNumber min={1} max={10} step={0.1} className="!w-full" /></Form.Item>
                </div>
                {local && <>
                  <Form.Item name="downloads" label="Downloads folder" tooltip="Where 'Import from Downloads' looks for pictures and ChatGPT bundles"><Input /></Form.Item>
                  <Form.Item name="export_dir" label="Export folder" tooltip="'Export' buttons copy finished files here (e.g. an AirDrop or iCloud folder)"><Input /></Form.Item>
                  <Form.Item name="python" label="Python for the scripts" tooltip="Needs numpy, opencv, pillow and scipy (pip install -r scripts/requirements.txt)"><Input /></Form.Item>
                </>}
                {artSource !== 'own' && <Form.Item name="chatgpt_url" label="ChatGPT link"><Input /></Form.Item>}
                {isAdmin && <Button type="primary" htmlType="submit" icon={<SaveOutlined />}>Save settings</Button>}
              </Form>
            </Card>
          </Col>
          <Col xs={24} xl={11}>
            <Card size="small" title={<span><FontSizeOutlined /> Fonts (fonts/)</span>} data-tour="set-fonts" extra={isEditor &&
              <Upload accept=".ttf,.otf" showUploadList={false} beforeUpload={async f => { try { await api.uploadFont(f); message.success(`Added ${f.name}`); loadFonts() } catch (e) { message.error((e as Error).message) } return false }}>
                <Button size="small" type="primary" icon={<UploadOutlined />}>Upload a font</Button>
              </Upload>}>
              <Input className="!mb-2" value={sample} onChange={e => setSample(e.target.value)} placeholder="sample text" />
              <List size="small" dataSource={fonts} renderItem={f => (
                <List.Item><div className="flex flex-col gap-1 w-full">
                  <Space><Typography.Text strong>{f.name}</Typography.Text><Typography.Text type="secondary" className="text-xs">{Math.round(f.size / 1024)} KB</Typography.Text></Space>
                  <img src={api.fontSample(f.path, sample || 'Aa')} className="h-9 self-start" />
                </div></List.Item>)} />
            </Card>
            <Card size="small" title="Guided tours" className="!mt-3">
              <Typography.Paragraph type="secondary">Every page has a short tour (the Tour button in its header). Show them all again automatically:</Typography.Paragraph>
              <Button icon={<RedoOutlined />} onClick={() => { resetTours(); message.success('Tours will show again on each page') }}>Show all tours again</Button>
            </Card>
          </Col>
        </Row>
      </div>
      {tour}
    </>
  )
}
