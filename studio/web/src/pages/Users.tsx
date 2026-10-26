import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd'
import { DeleteOutlined, KeyOutlined, LaptopOutlined, ReloadOutlined, SafetyOutlined, UserAddOutlined } from '@ant-design/icons'
import { api } from '../api'
import { PageHeader } from '../App'
import { roleColor, useUser } from '../auth'
import { usePageTour } from '../components/Tours'
import { SessionList, ago } from '../components/UserMenu'
import type { Role, SessionInfo, User } from '../types'

const ROLE_OPTS: { value: Role; label: string; desc: string }[] = [
  { value: 'viewer', label: 'Viewer', desc: 'sees everything, changes nothing' },
  { value: 'editor', label: 'Editor', desc: 'creates, edits, renders and marks posts' },
  { value: 'admin', label: 'Admin', desc: 'everything + users, storage, tools, settings' },
]

function TempPassword({ email, pw }: { email: string; pw: string }) {
  return <div>
    <Typography.Paragraph>Give <b>{email}</b> this temporary password. It is shown <b>only once</b>; they choose their own at first sign-in.</Typography.Paragraph>
    <Typography.Paragraph copyable code className="!text-base">{pw}</Typography.Paragraph>
  </div>
}

export default function UsersPage() {
  const { message, modal } = App.useApp()
  const me = useUser()
  const [users, setUsers] = useState<User[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [sessionsOf, setSessionsOf] = useState<User | null>(null)
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [form] = Form.useForm()
  const load = () => api.users().then(setUsers).catch(e => message.error(e.message))
  useEffect(() => { load() }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const loadSessions = (u: User) => api.userSessions(u.id).then(setSessions).catch(e => message.error(e.message))
  const { tour, button } = usePageTour('users', [
    { title: 'Users', description: 'Everyone who can sign in to the Studio, with their role. Only admins see this page.' },
    { target: 'users-add', title: 'Invite someone', description: 'Create an account: you get a one-time temporary password to send them; they pick their own at first sign-in.' },
    { target: 'users-table', title: 'Roles & access', description: 'Viewer = look only, Editor = make and change things, Admin = also users, storage and tools. Reset a password, turn an account off, or sign someone out of every device.' },
  ], !!users)

  const update = async (u: User, b: { role?: Role; disabled?: boolean }) => {
    try { await api.updateUser(u.id, b); message.success('Saved'); load() } catch (e) { message.error((e as Error).message) }
  }

  return <>
    <PageHeader title="Users" sub="Who can sign in, and what they can do" extra={<Space>{button}
      <Button icon={<ReloadOutlined />} onClick={load} />
      <Button type="primary" icon={<UserAddOutlined />} onClick={() => setAdding(true)} data-tour="users-add">Add user</Button></Space>} />
    <div className="flex-1 overflow-auto p-5">
      <Card size="small" data-tour="users-table">
        <Table<User> rowKey="id" loading={!users} dataSource={users ?? []} pagination={false} size="middle" scroll={{ x: 760 }} columns={[
          { title: 'Name', width: 260, render: (_, u) => <div><div className="font-semibold">{u.name || '—'} {u.id === me?.id && <Tag>you</Tag>}</div><div className="text-xs opacity-60">{u.email}</div></div> },
          { title: 'Role', width: 150, render: (_, u) => <Select size="small" value={u.role} style={{ width: 120 }} disabled={u.id === me?.id}
              options={ROLE_OPTS.map(o => ({ value: o.value, label: <Tooltip title={o.desc} placement="right"><Tag color={roleColor[o.value]}>{o.label}</Tag></Tooltip> }))}
              onChange={(v: Role) => update(u, { role: v })} /> },
          { title: 'Status', width: 170, render: (_, u) => <Space size={4} wrap>
              {u.disabled ? <Tag color="red">off</Tag> : <Tag color="green">active</Tag>}
              {u.must_change_password && <Tooltip title="Signs in with a temporary password and must choose a new one"><Tag color="gold">temp password</Tag></Tooltip>}
              {u.totp_enabled && <Tag icon={<SafetyOutlined />} color="purple">2FA</Tag>}
              {u.locked && <Tag color="orange">locked (too many tries)</Tag>}
            </Space> },
          { title: 'Last sign-in', width: 150, render: (_, u) => <span className="text-xs">{ago(u.last_login_at)}{u.last_login_ip ? ` · ${u.last_login_ip}` : ''}</span> },
          { title: 'Active', width: 80, render: (_, u) => <Switch size="small" checked={!u.disabled} disabled={u.id === me?.id} onChange={v => update(u, { disabled: !v })} /> },
          { title: '', width: 210, render: (_, u) => <Space size={4}>
              <Tooltip title="Sessions / devices"><Button size="small" icon={<LaptopOutlined />} onClick={() => { setSessionsOf(u); loadSessions(u) }} /></Tooltip>
              <Popconfirm title={`Reset ${u.email}'s password?`} description="They get a temporary password and are signed out everywhere." okText="Reset"
                onConfirm={async () => { try { const r = await api.resetPassword(u.id); modal.info({ title: 'Temporary password', content: <TempPassword email={u.email} pw={r.temporary_password} />, width: 480 }); load() } catch (e) { message.error((e as Error).message) } }}>
                <Tooltip title="Reset password"><Button size="small" icon={<KeyOutlined />} /></Tooltip>
              </Popconfirm>
              {u.totp_enabled && <Popconfirm title="Turn off two-factor for this user?" onConfirm={async () => { await api.disable2fa(u.id).catch(e => message.error(e.message)); load() }}>
                <Tooltip title="Turn off 2FA (lost phone)"><Button size="small" icon={<SafetyOutlined />} /></Tooltip>
              </Popconfirm>}
              {u.id !== me?.id && <Popconfirm title={`Delete ${u.email}?`} description="Their account and sessions are removed. Content they made stays." okText="Delete" okButtonProps={{ danger: true }}
                onConfirm={async () => { try { await api.deleteUser(u.id); message.success('Deleted'); load() } catch (e) { message.error((e as Error).message) } }}>
                <Tooltip title="Delete"><Button size="small" danger icon={<DeleteOutlined />} /></Tooltip>
              </Popconfirm>}
            </Space> },
        ]} />
      </Card>
      <Alert className="!mt-3" type="info" showIcon message="Tip" description="Prefer turning an account off (Active switch) over deleting it — it can be turned back on later. Changing a role or turning an account off takes effect immediately." />
    </div>

    <Modal open={adding} title="Add a user" okText="Create" onCancel={() => setAdding(false)} onOk={() => form.submit()} destroyOnHidden>
      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ role: 'editor' }} onFinish={async (v: { email: string; name: string; role: Role; password?: string }) => {
        try {
          const r = await api.createUser(v); setAdding(false); form.resetFields(); load()
          if (r.temporary_password) modal.success({ title: 'User created', content: <TempPassword email={r.user.email} pw={r.temporary_password} />, width: 480 })
          else message.success('User created')
        } catch (e) { message.error((e as Error).message) }
      }}>
        <Form.Item name="name" label="Name"><Input /></Form.Item>
        <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}><Input autoComplete="off" /></Form.Item>
        <Form.Item name="role" label="Role"><Select options={ROLE_OPTS.map(o => ({ value: o.value, label: `${o.label} — ${o.desc}` }))} /></Form.Item>
        <Form.Item name="password" label="Password (optional)" extra="Leave empty to generate a one-time temporary password (recommended)." rules={[{ min: 10, message: 'At least 10 characters' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>

    <Drawer open={!!sessionsOf} onClose={() => setSessionsOf(null)} width={520} title={`Sessions — ${sessionsOf?.email ?? ''}`}
      extra={<Popconfirm title="Sign this user out everywhere?" onConfirm={async () => { if (sessionsOf) { await api.revokeAllSessions(sessionsOf.id).catch(e => message.error(e.message)); loadSessions(sessionsOf) } }}>
        <Button danger size="small">Sign out everywhere</Button></Popconfirm>}>
      <SessionList items={sessions.map(s => ({ ...s, current: false }))} onRevoke={async s => { if (sessionsOf) { await api.revokeSession(sessionsOf.id, s.sid).catch(e => message.error(e.message)); loadSessions(sessionsOf) } }} />
    </Drawer>
    {tour}
  </>
}
