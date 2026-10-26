import { useEffect, useState } from 'react'
import { Alert, App, AutoComplete, Button, Card, Checkbox, Form, Input, InputNumber, Result, Segmented, Space, Steps, Typography } from 'antd'
import { CustomerServiceOutlined, PictureOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'
import { go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import { parseTime } from '../lib'
import type { Couple } from '../types'
import { AddCoupleModal } from '../components/Couples'

const KINDS = [
  { value: 'strip', label: 'Comic strip', icon: <PictureOutlined />, desc: 'A 2–5 panel strip (image post) + its silent strip reel. Folder projects/NNN_name.' },
  { value: 'mv', label: 'Music video', icon: <VideoCameraOutlined />, desc: 'A NEW story told in frames with an original song. Folder music_videos/NN_name.' },
  { value: 'lyric', label: 'Lyric edit', icon: <CustomerServiceOutlined />, desc: 'Your pictures + words timed to a song, made in the lyric editor. Folder music_videos/NN_name.' },
]

export default function NewProject() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [couples, setCouples] = useState<Couple[]>([])
  const [busy, setBusy] = useState(false)
  const [addCouple, setAddCouple] = useState(false)
  const [done, setDone] = useState<{ kind: 'strip' | 'mv'; id: string; lyric: boolean } | null>(null)
  const kind = Form.useWatch('kind', form) ?? 'strip'
  const name = Form.useWatch('name', form)
  useEffect(() => { api.couples().then(setCouples).catch(() => {}) }, [])
  const { tour, button } = usePageTour('new', [
    { title: 'New project', description: 'Three questions and the folder is ready, numbered in order like the others.' },
    { target: 'np-kind', title: 'What are you making?', description: 'A comic strip, a music video, or a lyric edit of your own pictures.' },
    { target: 'np-name', title: 'Name and couple', description: 'A short name (letters, numbers, _). Pick a couple from couples.md or type your own.' },
    { target: 'np-create', title: 'Create', description: 'Makes the folder, writes a script template, and (for strips) a random panel layout.' },
  ])

  const submit = async () => {
    const v = await form.validateFields(); setBusy(true)
    try {
      const c = couples.find(x => x.short === v.couple || x.name === v.couple)
      const r = await api.newProject({ kind: v.kind, name: v.name, couple: v.couple ?? '', tag: c?.tag ?? '', premise: v.premise ?? '', panels: v.panels ?? 4,
        seed: null, layout: !!v.layout, mood: v.mood ?? '', lines: v.lines ?? '', start: parseTime(String(v.start ?? '0')) ?? 0 })
      setDone({ kind: r.kind, id: r.id, lyric: v.kind === 'lyric' }); message.success(`Created ${r.id}`)
    } catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }

  if (done) return <>
    <PageHeader title="New project" />
    <Result status="success" title={`${done.id} is ready`} subTitle={done.kind === 'strip' ? 'Next: finish the script, then make the picture (ChatGPT prompt or your own drawing).' : done.lyric ? 'Next: add your pictures and song, then time the lyrics.' : 'Next: write the story and make the character sheet.'}
      extra={[
        done.lyric ? <Button key="l" type="primary" onClick={() => go(`/lyric/${done.id}/lyric_edit.json`)}>Open the lyric editor</Button>
          : <Button key="o" type="primary" onClick={() => go(`/p/${done.kind}/${done.id}/script`)}>Open the project</Button>,
        done.lyric && <Button key="p" onClick={() => go(`/p/mv/${done.id}/pictures`)}>Add pictures first</Button>,
        <Button key="n" onClick={() => { setDone(null); form.resetFields() }}>Make another</Button>,
      ]} />
  </>

  return (
    <>
      <PageHeader title="New project" sub="Creates the next numbered folder with scripts/new_project.py" extra={button} />
      <div className="flex-1 overflow-auto p-5">
        <div className="max-w-3xl mx-auto">
          <Steps size="small" className="!mb-5" current={name ? 2 : 1} items={[{ title: 'What' }, { title: 'Details' }, { title: 'Create' }]} />
          <Form form={form} layout="vertical" initialValues={{ kind: 'strip', panels: 4, layout: true, start: '0:00' }}>
            <Form.Item name="kind" label="What are you making?" data-tour="np-kind">
              <Segmented block size="large" options={KINDS.map(k => ({ value: k.value, label: <span className="py-1 inline-flex gap-2 items-center">{k.icon}{k.label}</span> }))} />
            </Form.Item>
            <Alert className="!-mt-3 !mb-4" type="info" message={KINDS.find(k => k.value === kind)?.desc} />
            <Card size="small" data-tour="np-name">
              <div className="grid grid-cols-2 gap-x-4">
                <Form.Item name="name" label="Short name" tooltip="lowercase letters, numbers and _ — e.g. rem_rainy_day" rules={[{ required: true, message: 'Give it a name' }, { pattern: /^[a-z0-9][a-z0-9_]*$/, message: 'lowercase letters, numbers and _ only' }]}
                  normalize={v => String(v ?? '').toLowerCase().replace(/[\s-]+/g, '_')}>
                  <Input placeholder={kind === 'strip' ? 'rainy_day' : 'first_date'} />
                </Form.Item>
                <Form.Item label="Couple" tooltip="Pick one of your couples, type any couple, or add a new one">
                  <Space.Compact className="w-full">
                    <Form.Item name="couple" noStyle>
                      <AutoComplete placeholder={couples.length ? 'Pick or type a couple' : 'Hero x Heroine'} options={couples.map(c => ({ value: c.short, label: <span>{c.short} <span className="opacity-50 text-xs">· {c.series}</span></span> }))}
                        filterOption={(i, o) => String(o?.value ?? '').toLowerCase().includes(i.toLowerCase())} />
                    </Form.Item>
                    <Button onClick={() => setAddCouple(true)}>+ New</Button>
                  </Space.Compact>
                </Form.Item>
              </div>
              <Form.Item name="premise" label={kind === 'strip' ? 'Title / premise' : 'Story in one line'}>
                <Input placeholder={kind === 'strip' ? 'Hottest day of the year' : 'A day off'} />
              </Form.Item>
              <div className="grid grid-cols-2 gap-x-4">
                <Form.Item name="mood" label="Mood"><AutoComplete placeholder="sweet / funny / slapstick" options={['sweet', 'funny', 'slapstick', 'bittersweet', 'devoted'].map(v => ({ value: v }))} /></Form.Item>
                {kind === 'strip' && <Form.Item name="panels" label="Panels"><InputNumber min={1} max={6} className="!w-full" /></Form.Item>}
                {kind === 'lyric' && <Form.Item name="start" label="Song starts at" tooltip="e.g. 0:25.47 — you can change it later"><Input /></Form.Item>}
              </div>
              {kind === 'strip' && <Form.Item name="layout" valuePropName="checked" className="!-mt-2"><Checkbox>Make a random panel layout now</Checkbox></Form.Item>}
              {kind !== 'mv' && <Form.Item name="lines" label={kind === 'strip' ? 'Panel lines (optional, one per row)' : 'Lyrics (optional, one line per row)'}>
                <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={kind === 'strip' ? 'Caption "Hottest day of the year." He is melting on the floor…\nShe: "Leave it to me!"…' : '*HELLO* / first line / of the song'} />
              </Form.Item>}
            </Card>
            <Space className="mt-4" data-tour="np-create">
              <Button type="primary" size="large" loading={busy} onClick={submit}>Create {KINDS.find(k => k.value === kind)?.label.toLowerCase()}</Button>
              <Typography.Text type="secondary">Nothing existing is overwritten — a name that already exists is refused.</Typography.Text>
            </Space>
          </Form>
        </div>
      </div>
      <AddCoupleModal open={addCouple} onClose={() => setAddCouple(false)} initial={form.getFieldValue('couple')}
        onAdded={(list, name) => { setCouples(list); const c = list.find(x => x.name === name.replace(/\s+x\s+/, ' × ')); form.setFieldValue('couple', c?.short ?? name) }} />
      {tour}
    </>
  )
}
