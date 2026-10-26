import { useEffect, useState } from 'react'
import { App, Button, Card, Empty, Form, Grid, Input, Modal, Popconfirm, Space, Table, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { api } from '../api'
import { useCan } from '../auth'
import type { Couple } from '../types'

type Row = Pick<Couple, 'name' | 'tag' | 'series' | 'looks' | 'dynamic'>
const toRow = (c: Couple): Row => ({ name: c.name, tag: c.tag, series: c.series, looks: c.looks, dynamic: c.dynamic })

/** Add one couple (used from New project); returns the saved list. */
export function AddCoupleModal({ open, onClose, onAdded, initial }: { open: boolean; onClose: () => void; onAdded: (list: Couple[], added: string) => void; initial?: string }) {
  const { message } = App.useApp()
  const [form] = Form.useForm<Row>()
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) form.setFieldsValue({ name: initial ?? '', tag: '', series: '', looks: '', dynamic: '' }) }, [open, initial, form])
  const save = async () => {
    const v = await form.validateFields(); setBusy(true)
    try {
      const cur = (await api.couples()).map(toRow)
      const list = await api.saveCouples([...cur, v])
      message.success(`Added ${v.name}`); onAdded(list, v.name); onClose()
    } catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onCancel={onClose} onOk={save} confirmLoading={busy} okText="Add couple" title="New couple" destroyOnHidden>
      <CoupleFields form={form} />
    </Modal>
  )
}

function CoupleFields({ form }: { form: ReturnType<typeof Form.useForm<Row>>[0] }) {
  return (
    <Form form={form} layout="vertical" requiredMark={false}>
      <Form.Item name="name" label="Couple" rules={[{ required: true, message: 'e.g. Hero x Heroine' }]} extra='Two names with "x" between them, e.g. Hero x Heroine'><Input placeholder="Hero x Heroine" /></Form.Item>
      <div className="grid grid-cols-2 gap-x-3">
        <Form.Item name="tag" label="Hashtag" rules={[{ pattern: /^(#\w+)?$/, message: 'like #HeroxHeroine' }]}><Input placeholder="#HeroxHeroine" /></Form.Item>
        <Form.Item name="series" label="Series"><Input placeholder="the anime / game / your own" /></Form.Item>
      </div>
      <Form.Item name="looks" label="Looks" extra="Hair, eyes, outfit, accessories — keeps them on-model."><Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} /></Form.Item>
      <Form.Item name="dynamic" label="Dynamic / joke angles"><Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} /></Form.Item>
    </Form>
  )
}

/** Settings → Couples: the list the New project wizard suggests (couples.md). */
export default function CouplesEditor() {
  const { message } = App.useApp()
  const canEdit = useCan('editor')
  const [rows, setRows] = useState<Row[] | null>(null)
  const [dirty, setDirty] = useState(false)
  const [add, setAdd] = useState(false)
  const phone = Grid.useBreakpoint().md === false
  const load = () => api.couples().then(c => { setRows(c.map(toRow)); setDirty(false) }).catch(e => message.error(e.message))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (i: number, p: Partial<Row>) => { setRows(r => r && r.map((x, k) => k === i ? { ...x, ...p } : x)); setDirty(true) }
  const save = async () => { try { setRows((await api.saveCouples(rows ?? [])).map(toRow)); setDirty(false); message.success('Couples saved') } catch (e) { message.error((e as Error).message) } }
  const cell = (k: keyof Row, i: number, r: Row, area = false) => area
    ? <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={r[k]} disabled={!canEdit} onChange={e => set(i, { [k]: e.target.value })} />
    : <Input value={r[k]} disabled={!canEdit} onChange={e => set(i, { [k]: e.target.value })} />
  return (
    <Card size="small" title="Couples" loading={!rows} extra={canEdit && <Space>
      <Button icon={<PlusOutlined />} onClick={() => setAdd(true)}>Add a couple</Button>
      <Button type="primary" icon={<SaveOutlined />} disabled={!dirty} onClick={save}>Save</Button>
    </Space>}>
      <Typography.Paragraph type="secondary">The couples your comics are about. New project suggests them, captions use their hashtag. Saved in <code>couples.md</code>.</Typography.Paragraph>
      {rows && !rows.length ? <Empty description="No couples yet — add your first one." /> : phone ?
        <div className="flex flex-col gap-2">{(rows ?? []).map((r, i) => (
          <Card key={i} size="small" title={cell('name', i, r)} extra={canEdit && <Popconfirm title="Remove this couple?" onConfirm={() => { setRows(x => x && x.filter((_, k) => k !== i)); setDirty(true) }}>
            <Button size="small" type="text" danger icon={<DeleteOutlined />} /></Popconfirm>}>
            <div className="flex flex-col gap-2">
              <div className="grid grid-cols-2 gap-2">{cell('tag', i, r)}{cell('series', i, r)}</div>
              <Typography.Text type="secondary" className="text-xs">Looks</Typography.Text>{cell('looks', i, r, true)}
              <Typography.Text type="secondary" className="text-xs">Dynamic</Typography.Text>{cell('dynamic', i, r, true)}
            </div>
          </Card>))}</div> :
        <Table<Row> scroll={{ x: 900 }} size="small" pagination={false} rowKey={(_, i) => String(i)} dataSource={rows ?? []} columns={[
          { title: 'Couple', width: 190, render: (_, r, i) => cell('name', i, r) },
          { title: 'Hashtag', width: 150, render: (_, r, i) => cell('tag', i, r) },
          { title: 'Series', width: 160, render: (_, r, i) => cell('series', i, r) },
          { title: 'Looks', render: (_, r, i) => cell('looks', i, r, true) },
          { title: 'Dynamic', render: (_, r, i) => cell('dynamic', i, r, true) },
          { title: '', width: 44, render: (_, __, i) => canEdit && <Popconfirm title="Remove this couple?" description="Projects are not changed." onConfirm={() => { setRows(r => r && r.filter((_, k) => k !== i)); setDirty(true) }}>
            <Button size="small" type="text" danger icon={<DeleteOutlined />} /></Popconfirm> },
        ]} />}
      <AddCoupleModal open={add} onClose={() => setAdd(false)} onAdded={list => { setRows(list.map(toRow)); setDirty(false) }} />
    </Card>
  )
}
