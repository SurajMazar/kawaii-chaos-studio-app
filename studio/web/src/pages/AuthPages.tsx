import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Card, Form, Input, Modal, Result, Spin, Steps, Typography } from 'antd'
import { FileImageOutlined, LockOutlined, MailOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'
import { AUTH_EVENT, ApiError, api, setCsrf } from '../api'
import { useAuth } from '../auth'

function Shell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-auto flex items-center justify-center p-4" style={{ background: 'radial-gradient(circle at 30% 20%, rgba(255,93,143,.12), transparent 50%), #16131a' }}>
      <div className={`w-full ${wide ? 'max-w-[520px]' : 'max-w-[420px]'}`}>
        <div className="flex items-center justify-center gap-2.5 mb-5 select-none">
          <FileImageOutlined style={{ color: '#ff5d8f', fontSize: 30 }} />
          <div className="leading-none">
            <div className="font-display font-extrabold text-[24px]"><span className="text-pink">Kawaii</span> <span className="text-sun">Chaos</span></div>
            <div className="text-[11px] font-semibold tracking-[0.22em] uppercase opacity-60 mt-1">Studio</div>
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}

const pwRules = [
  { required: true, message: 'Choose a password' },
  { min: 10, message: 'At least 10 characters' },
]

export function SetupPage({ tokenRequired }: { tokenRequired: boolean }) {
  const { message } = App.useApp()
  const refresh = useAuth(s => s.refresh)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const finish = async (v: { name: string; email: string; password: string; setup_token?: string }) => {
    setBusy(true); setErr(null)
    try {
      const r = await api.setup(v); setCsrf(r.csrf); await refresh(); message.success(`Welcome, ${r.user.name || r.user.email}! You are the admin.`)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Shell wide>
      <Card>
        <Steps size="small" current={0} className="!mb-4" items={[{ title: 'Create the admin' }, { title: 'Use the Studio' }]} />
        <Typography.Title level={4} className="!mt-0">Welcome! Let's create your admin account</Typography.Title>
        <Typography.Paragraph type="secondary">
          This is the first start of Kawaii Chaos Studio, so nobody can sign in yet. The account you create now is the
          <b> admin</b>: it can do everything, invite other people (Users page) and set up storage (Settings → Integrations).
          There are no default passwords — this screen disappears once the admin exists.
        </Typography.Paragraph>
        {err && <Alert type="error" showIcon message={err} className="!mb-3" />}
        <Form layout="vertical" onFinish={finish} requiredMark={false} data-tour="setup-form">
          {tokenRequired && <Form.Item name="setup_token" label="One-time setup code" rules={[{ required: true, message: 'Enter the setup code' }]}
            tooltip="Printed in the server log at start-up (look for FIRST-RUN SETUP), or the STUDIO_SETUP_TOKEN you set">
            <Input prefix={<SafetyOutlined />} placeholder="from the server log" autoComplete="off" />
          </Form.Item>}
          <Form.Item name="name" label="Your name"><Input prefix={<UserOutlined />} placeholder="Suraj" autoComplete="name" /></Form.Item>
          <Form.Item name="email" label="Email (your sign-in name)" rules={[{ required: true, type: 'email', message: 'Enter a valid email' }]}>
            <Input prefix={<MailOutlined />} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={pwRules} extra="10+ characters. A short sentence is easy to remember and hard to guess.">
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="confirm" label="Password again" dependencies={['password']} rules={[{ required: true, message: 'Type it again' },
            ({ getFieldValue }) => ({ validator: (_, v) => v === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('The two passwords are different')) })]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={busy}>Create admin & open the Studio</Button>
        </Form>
      </Card>
    </Shell>
  )
}

export function LoginPage() {
  return (
    <Shell>
      <Card>
        <Typography.Title level={4} className="!mt-0">Sign in</Typography.Title>
        <LoginForm />
        <Typography.Paragraph type="secondary" className="!mt-4 !mb-0 text-xs">
          Forgot your password? Ask an admin to reset it on the Users page.
        </Typography.Paragraph>
      </Card>
    </Shell>
  )
}

function LoginForm() {
  const refresh = useAuth(s => s.refresh)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [needCode, setNeedCode] = useState(false)
  const [form] = Form.useForm()
  const finish = async (v: { email: string; password: string; totp?: string }) => {
    setBusy(true); setErr(null)
    try { const r = await api.login(v); setCsrf(r.csrf); await refresh() }   // confirm the session before showing the app
    catch (e) {
      const ae = e as ApiError
      if (ae.code === 'totp_required') { setNeedCode(true); setErr(null) }
      else setErr(ae.message)
    } finally { setBusy(false) }
  }
  return (
      <>
        {err && <Alert type="error" showIcon message={err} className="!mb-3" />}
        <Form form={form} layout="vertical" onFinish={finish} requiredMark={false}>
          <Form.Item name="email" label="Email" rules={[{ required: true, message: 'Enter your email' }]}>
            <Input prefix={<MailOutlined />} autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, message: 'Enter your password' }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          {needCode && <Form.Item name="totp" label="6-digit code from your authenticator app" rules={[{ required: true, pattern: /^\d{6}$/, message: '6 digits' }]}>
            <Input prefix={<SafetyOutlined />} inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus />
          </Form.Item>}
          <Button type="primary" htmlType="submit" block size="large" loading={busy}>Sign in</Button>
        </Form>
      </>
  )
}

export function ForcePasswordChange() {
  const setUser = useAuth(s => s.setUser)
  const { message } = App.useApp()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <Shell>
      <Card>
        <Typography.Title level={4} className="!mt-0">Choose your own password</Typography.Title>
        <Typography.Paragraph type="secondary">You signed in with a temporary password. Pick a new one to continue.</Typography.Paragraph>
        {err && <Alert type="error" showIcon message={err} className="!mb-3" />}
        <Form layout="vertical" requiredMark={false} onFinish={async (v: { current: string; next: string }) => {
          setBusy(true); setErr(null)
          try { const r = await api.changePassword(v.current, v.next); setUser(r.user, r.csrf); message.success('Password changed') }
          catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
        }}>
          <Form.Item name="current" label="Temporary password" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
          <Form.Item name="next" label="New password" rules={pwRules}><Input.Password autoComplete="new-password" /></Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>Save and continue</Button>
        </Form>
        <Button type="link" className="!px-0 !mt-2" onClick={async () => { await api.logout().catch(() => {}); setUser(null) }}>Sign out</Button>
      </Card>
    </Shell>
  )
}

/** Shows setup / sign-in / forced password change until there is a usable session, then the app. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { state, loading, error, refresh } = useAuth()
  const wasIn = useRef(false)              // the app was already open: keep it mounted (unsaved edits!) and overlay sign-in
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    const on = () => { refresh() }
    window.addEventListener(AUTH_EVENT, on)
    return () => window.removeEventListener(AUTH_EVENT, on)
  }, [refresh])
  if (loading) return <div className="h-full flex items-center justify-center"><Spin size="large" /></div>
  if (error || !state) return <Result status="warning" title="The Studio server is not running" subTitle="Start it with studio/run.sh, then reload this page."
    extra={<Button onClick={() => refresh()}>Try again</Button>} />
  if (state.desktop && !state.user) return <Result status="info" title="Please reopen the app" subTitle="Close Kawaii Chaos Studio and open it again — it signs you in by itself." />
  if (state.setup_required) return <SetupPage tokenRequired={state.setup_token_required} />
  if (!state.user && wasIn.current) return <>
    {children}
    <Modal open closable={false} maskClosable={false} keyboard={false} footer={null} title="Your session ended — sign in again">
      <Typography.Paragraph type="secondary">Nothing on this page is lost: sign in and carry on (then save).</Typography.Paragraph>
      <LoginForm />
    </Modal>
  </>
  if (!state.user) return <LoginPage />
  wasIn.current = true
  if (state.user.must_change_password) return <ForcePasswordChange />
  return <>{children}</>
}
