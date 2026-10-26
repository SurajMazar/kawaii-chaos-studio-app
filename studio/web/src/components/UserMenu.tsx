import { useEffect, useState } from 'react'
import { Alert, App, Avatar, Button, Dropdown, Form, Input, List, Modal, QRCode, Tabs, Tag, Tooltip, Typography } from 'antd'
import { KeyOutlined, LockOutlined, LogoutOutlined, SafetyOutlined, UserOutlined, LaptopOutlined, StopOutlined } from '@ant-design/icons'
import { api } from '../api'
import { roleColor, useAuth, useUser } from '../auth'
import type { SessionInfo } from '../types'

/** After an explicit sign-out start from a clean page (the sign-in overlay is only for sessions that expire mid-work). */
export function signedOut() { window.location.hash = '#/'; window.location.reload() }

export function ago(t?: number | null) {
  if (!t) return 'never'
  const s = Math.max(0, Date.now() / 1000 - t)
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`
  return new Date(t * 1000).toLocaleDateString()
}

export function SessionList({ items, onRevoke }: { items: SessionInfo[]; onRevoke: (s: SessionInfo) => void }) {
  return <List size="small" dataSource={items} locale={{ emptyText: 'No active sessions' }} renderItem={s => (
    <List.Item actions={[s.current ? <Tag color="green">this browser</Tag> : <Button size="small" danger icon={<StopOutlined />} onClick={() => onRevoke(s)}>Sign out</Button>]}>
      <List.Item.Meta avatar={<LaptopOutlined />} title={<span className="text-xs">{(s.user_agent || 'unknown browser').slice(0, 70)}</span>}
        description={<span className="text-xs">{s.ip || '?'} · active {ago(s.last_seen)} · signed in {ago(s.created_at)}</span>} />
    </List.Item>)} />
}

function AccountModal({ open, onClose, tab }: { open: boolean; onClose: () => void; tab: string }) {
  const { message } = App.useApp()
  const user = useUser()
  const { setUser, state, refresh } = useAuth()
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [active, setActive] = useState(tab)
  const [totp, setTotp] = useState<{ secret: string; uri: string } | null>(null)
  const [pwForm] = Form.useForm()
  const loadSessions = () => api.mySessions().then(setSessions).catch(() => {})
  useEffect(() => { if (open) { setActive(tab); loadSessions(); setTotp(null) } }, [open, tab])
  if (!user) return null
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Your account" width={560} destroyOnHidden>
      <Tabs activeKey={active} onChange={setActive} items={[
        { key: 'password', label: <span><KeyOutlined /> Password</span>, children: (
          <Form form={pwForm} layout="vertical" requiredMark={false} onFinish={async (v: { current: string; next: string }) => {
            try { const r = await api.changePassword(v.current, v.next); setUser(r.user, r.csrf); pwForm.resetFields(); message.success('Password changed — your other devices were signed out'); loadSessions() }
            catch (e) { message.error((e as Error).message) }
          }}>
            <Form.Item name="current" label="Current password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
            <Form.Item name="next" label="New password" rules={[{ required: true }, { min: 10, message: 'At least 10 characters' }]}><Input.Password autoComplete="new-password" /></Form.Item>
            <Button type="primary" htmlType="submit" icon={<LockOutlined />}>Change password</Button>
          </Form>) },
        { key: '2fa', label: <span><SafetyOutlined /> Two-factor</span>, children: !state?.two_factor_available ?
          <Alert type="info" showIcon message="Two-factor sign-in needs STUDIO_SECRET_KEY on the server." /> : user.totp_enabled ? (
          <div>
            <Alert type="success" showIcon message="Two-factor sign-in is on. You need your authenticator app code to sign in." className="!mb-3" />
            <Form layout="inline" onFinish={async (v: { password: string }) => {
              try { await api.totpDisable(v.password); message.success('Two-factor sign-in turned off'); refresh() } catch (e) { message.error((e as Error).message) }
            }}>
              <Form.Item name="password" rules={[{ required: true, message: 'Password' }]}><Input.Password placeholder="your password" /></Form.Item>
              <Button danger htmlType="submit">Turn off</Button>
            </Form>
          </div>) : totp ? (
          <div className="flex gap-4 items-start">
            <QRCode value={totp.uri} size={168} bgColor="#fff" />
            <div className="flex-1">
              <Typography.Paragraph>Scan with Google Authenticator, 1Password, Authy… then type the 6-digit code.</Typography.Paragraph>
              <Typography.Paragraph type="secondary" className="text-xs" copyable={{ text: totp.secret }}>Key: {totp.secret.replace(/(.{4})/g, '$1 ')}</Typography.Paragraph>
              <Form layout="inline" onFinish={async (v: { code: string }) => {
                try { await api.totpConfirm(v.code); message.success('Two-factor sign-in is on'); setTotp(null); refresh() } catch (e) { message.error((e as Error).message) }
              }}>
                <Form.Item name="code" rules={[{ required: true, pattern: /^\d{6}$/, message: '6 digits' }]}><Input placeholder="123456" maxLength={6} inputMode="numeric" /></Form.Item>
                <Button type="primary" htmlType="submit">Turn on</Button>
              </Form>
            </div>
          </div>) : (
          <div>
            <Typography.Paragraph>Add a second step to sign-in: a 6-digit code from an app on your phone. Recommended for admins.</Typography.Paragraph>
            <Form layout="inline" onFinish={async (v: { password: string }) => {
              try { setTotp(await api.totpSetup(v.password)) } catch (e) { message.error((e as Error).message) }
            }}>
              <Form.Item name="password" rules={[{ required: true, message: 'Password' }]}><Input.Password placeholder="confirm your password" /></Form.Item>
              <Button type="primary" htmlType="submit" icon={<SafetyOutlined />}>Set up</Button>
            </Form>
          </div>) },
        { key: 'sessions', label: <span><LaptopOutlined /> Sessions</span>, children: (
          <div>
            <SessionList items={sessions} onRevoke={async s => { await api.revokeMySession(s.sid).catch(e => message.error(e.message)); loadSessions() }} />
            <Button danger className="!mt-2" icon={<LogoutOutlined />} onClick={() => Modal.confirm({
              title: 'Sign out everywhere?', content: 'Every browser and device (including this one) will need to sign in again.',
              okText: 'Sign out everywhere', okButtonProps: { danger: true },
              onOk: async () => { await api.logoutAll().catch(() => {}); signedOut() },
            })}>Sign out everywhere</Button>
          </div>) },
      ]} />
    </Modal>
  )
}

/** Avatar + menu at the bottom of the sidebar: who is signed in, account settings, sign out. */
export function UserMenu({ collapsed }: { collapsed: boolean }) {
  const user = useUser()
  const desktop = useAuth(s => !!s.state?.desktop)      // Mac app: one local owner, no passwords to manage
  const [modal, setModal] = useState<string | null>(null)
  if (!user) return null
  const initials = (user.name || user.email).split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(s => s[0]!.toUpperCase()).join('')
  const items = [
    { key: 'who', type: 'group' as const, label: <div className="py-1"><div className="font-semibold">{user.name || user.email}</div><div className="text-xs opacity-60">{user.email}</div><Tag color={roleColor[user.role]} className="!mt-1">{user.role}</Tag></div> },
    ...(desktop ? [] : [
      { type: 'divider' as const },
      { key: 'password', icon: <KeyOutlined />, label: 'Change password' },
      { key: '2fa', icon: <SafetyOutlined />, label: 'Two-factor sign-in' },
      { key: 'sessions', icon: <LaptopOutlined />, label: 'Sessions & devices' },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Sign out', danger: true },
    ]),
  ]
  return <>
    <Dropdown placement="topLeft" trigger={['click']} menu={{ items, onClick: async ({ key }) => {
      if (key === 'logout') { await api.logout().catch(() => {}); signedOut() }
      else setModal(key)
    } }}>
      <Tooltip title={collapsed ? `${user.name || user.email} (${user.role})` : undefined} placement="right">
        <div className={`flex items-center gap-2 cursor-pointer rounded-lg hover:bg-white/5 py-1.5 ${collapsed ? 'justify-center px-0' : 'px-2'}`} data-tour="user-menu">
          <Avatar size={30} style={{ background: '#ff5d8f', flexShrink: 0 }} icon={initials ? undefined : <UserOutlined />}>{initials}</Avatar>
          {!collapsed && <div className="min-w-0 leading-tight">
            <div className="text-[13px] font-semibold truncate">{user.name || user.email}</div>
            <div className="text-[11px] opacity-60">{user.role}</div>
          </div>}
        </div>
      </Tooltip>
    </Dropdown>
    <AccountModal open={!!modal} tab={modal ?? 'password'} onClose={() => setModal(null)} />
  </>
}

export function ReadOnlyBanner() {
  const user = useUser()
  if (user?.role !== 'viewer') return null
  return <Alert banner type="info" showIcon message={<span>You have <b>view-only</b> access: you can look at everything, but changes are turned off. Ask an admin for editor access.</span>} />
}
