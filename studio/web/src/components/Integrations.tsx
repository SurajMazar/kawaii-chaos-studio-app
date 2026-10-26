import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Card, Col, Descriptions, Form, Input, Radio, Row, Space, Spin, Switch, Tag, Tooltip, Typography } from 'antd'
import { ApiOutlined, CloudOutlined, CloudServerOutlined, CopyOutlined, FolderOpenOutlined, LockOutlined, SaveOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { api } from '../api'
import { JobPanel, useJob } from './Jobs'
import { usePageTour } from './Tours'
import type { Backend, StorageConfig, StorageStatus } from '../types'

const BACKENDS: { key: Backend; title: string; icon: React.ReactNode; desc: string }[] = [
  { key: 'local', title: 'Local folder', icon: <FolderOpenOutlined />, desc: 'Files stay in a folder on this server (today: the repo). Simplest; back the folder up yourself.' },
  { key: 's3', title: 'Amazon S3', icon: <CloudOutlined />, desc: 'An S3 bucket in your AWS account.' },
  { key: 'r2', title: 'Cloudflare R2', icon: <CloudServerOutlined />, desc: 'R2 bucket — S3-compatible, no egress fees.' },
  { key: 's3compat', title: 'Other S3-compatible', icon: <ApiOutlined />, desc: 'MinIO, Backblaze B2, Wasabi, DigitalOcean Spaces…' },
]

const fmtBytes = (b?: number) => b === undefined ? '–' : b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`

type FormVals = Omit<StorageConfig, 'secret_access_key'> & { secret_access_key?: string }

export default function Integrations() {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<FormVals>()
  const [cfg, setCfg] = useState<StorageConfig | null>(null)
  const [status, setStatus] = useState<StorageStatus | null>(null)
  const [insecure, setInsecure] = useState(false)
  const [replaceSecret, setReplaceSecret] = useState(false)
  const [testing, setTesting] = useState(false)
  const [test, setTest] = useState<{ ok: boolean; error?: string; steps?: string[]; ms?: number; backend?: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const { job, log } = useJob(jobId, j => { if (j.state === 'done') message.success('All files copied'); else if (j.state === 'error') message.error(j.error ?? 'Copy failed') })
  const backend = Form.useWatch('backend', form) ?? cfg?.backend ?? 'local'
  const locked = useMemo(() => new Set(cfg?.locked ?? []), [cfg])

  const load = async () => {
    try {
      const r = await api.storage(); setCfg(r.config); setStatus(r.status); setInsecure(r.allow_insecure)
      const { secret_access_key: _s, locked: _l, can_store_secrets: _c, access_key_id_hint: _h, error: _e, ...rest } = r.config
      void _s; void _l; void _c; void _h; void _e
      form.setFieldsValue({ ...rest, secret_access_key: '' }); setReplaceSecret(false); setTest(null)
    } catch (e) { message.error((e as Error).message) }
  }
  useEffect(() => { load() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const { tour, button } = usePageTour('integrations', [
    { title: 'Storage integration', description: 'Where the Studio keeps every file: strips, music videos, uploads, fonts, captions and the posting log. Only admins see this.' },
    { target: 'int-status', title: 'What is in use now', description: 'The storage the Studio reads and writes right now. With a bucket, a local work cache keeps the files that jobs (renders, reels) need.' },
    { target: 'int-backend', title: 'Pick a storage', description: 'Local folder, Amazon S3, Cloudflare R2 or any S3-compatible service. Each one shows the fields it needs, with hints.' },
    { target: 'int-actions', title: 'Test → Copy → Switch', description: '1) Test connection checks the bucket and keys. 2) Copy my files there copies everything (your current files are never deleted). 3) Save & switch makes the Studio use it.' },
  ], !!cfg)

  const payload = (): Partial<StorageConfig> => {
    const v = form.getFieldsValue(true) as FormVals
    const out: Record<string, unknown> = {}
    for (const [k, val] of Object.entries(v)) {
      if (locked.has(k)) continue
      if (k === 'secret_access_key') { if (typeof val === 'string' && val.trim()) out[k] = val.trim(); continue }
      out[k] = val
    }
    return out as Partial<StorageConfig>
  }

  const doTest = async () => {
    setTesting(true); setTest(null)
    try { setTest(await api.storageTest(payload())) } catch (e) { setTest({ ok: false, error: (e as Error).message }) } finally { setTesting(false) }
  }

  const doMigrate = async () => {
    const p = payload()
    const hide = message.loading('Counting files…', 0)
    try {
      const plan = await api.storagePlan(p); hide()
      modal.confirm({
        title: 'Copy all files to the new storage?', width: 560, okText: 'Start copying',
        content: <div>
          <Descriptions size="small" column={1} bordered items={[
            { key: 'f', label: 'From', children: plan.source }, { key: 't', label: 'To', children: plan.target },
            { key: 'n', label: 'Files', children: `${plan.objects.toLocaleString()} (${fmtBytes(plan.bytes)})` },
            { key: 'e', label: 'Already there', children: `${plan.existing_same_size.toLocaleString()} with the same size (checked and skipped if identical)` },
          ]} />
          <Typography.Paragraph type="secondary" className="!mt-3 !mb-0">Nothing is deleted anywhere: your current files stay where they are. You can run this again later — it only copies what is missing or changed.</Typography.Paragraph>
        </div>,
        onOk: async () => { try { setJobId((await api.storageMigrate(p)).id) } catch (e) { message.error((e as Error).message) } },
      })
    } catch (e) { hide(); message.error((e as Error).message) }
  }

  const doSave = () => {
    const p = payload()
    modal.confirm({
      title: 'Save & switch storage?', width: 520, okText: 'Switch now',
      content: <div>
        <Typography.Paragraph>The Studio will read and write <b>{BACKENDS.find(b => b.key === p.backend)?.title}</b> from now on (it is tested first).</Typography.Paragraph>
        <Alert type="warning" showIcon message="Switching does not copy files" description="If the new storage is empty, use “Copy my files there” first, or the library will look empty. You can switch back any time." />
      </div>,
      onOk: async () => {
        setSaving(true)
        try { const r = await api.storageSave(p); setCfg(r.config); setStatus(r.status); message.success('Storage switched'); load() }
        catch (e) { message.error((e as Error).message) } finally { setSaving(false) }
      },
    })
  }

  if (!cfg) return <div className="p-10 flex justify-center"><Spin /></div>
  const secretSet = typeof cfg.secret_access_key === 'object' && cfg.secret_access_key?.set
  const L = (k: string) => locked.has(k)
  const lockIcon = (k: string) => L(k) ? <Tooltip title="Set by an environment variable on the server — change it there"><LockOutlined className="opacity-60" /></Tooltip> : null
  const field = (name: keyof FormVals, label: string, extra: React.ReactNode, input: React.ReactNode, rules: object[] = []) =>
    <Form.Item name={name as string} label={<Space size={4}>{label}{lockIcon(name as string)}</Space>} extra={extra} rules={L(name as string) ? [] : rules}>{input}</Form.Item>

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">{button}</div>
      <Card size="small" title="Storage in use" data-tour="int-status">
        {status?.error ? <Alert type="error" showIcon message="Storage is not available" description={status.error} /> :
          <Descriptions size="small" column={{ xs: 1, md: 2 }} items={[
            { key: 'a', label: 'Now using', children: <b>{status?.active}</b> },
            ...(status?.remote ? [
              { key: 'o', label: 'Files in the bucket', children: (status.objects ?? 0).toLocaleString() },
              { key: 'c', label: 'Local work cache', children: <Tooltip title={status.cache_dir}>{fmtBytes(status.cache_bytes)}</Tooltip> },
              { key: 'i', label: 'Listing refreshed', children: `${Math.round(status.index_age ?? 0)} s ago` },
            ] : []),
          ]} />}
        {cfg.error && <Alert className="!mt-2" type="warning" showIcon message={cfg.error} />}
      </Card>

      <Form form={form} layout="vertical" requiredMark={false} initialValues={{ backend: cfg.backend }}>
        <Card size="small" title="Where should the Studio keep its files?" data-tour="int-backend">
          <Form.Item name="backend" className="!mb-3">
            <Radio.Group className="!w-full" disabled={L('backend')}>
              <Row gutter={[10, 10]}>{BACKENDS.map(b => (
                <Col key={b.key} xs={24} md={12} xl={6}>
                  <Radio.Button value={b.key} className="!h-auto !w-full !p-3 !rounded-lg !leading-snug !whitespace-normal">
                    <div className="font-semibold">{b.icon} {b.title}</div>
                    <div className="text-xs opacity-60 mt-1">{b.desc}</div>
                  </Radio.Button>
                </Col>))}
              </Row>
            </Radio.Group>
          </Form.Item>
          {L('backend') && <Alert type="info" showIcon className="!mb-3" message="The backend is set by the STORAGE_BACKEND environment variable on the server." />}

          {backend === 'local' && field('local_path', 'Folder on the server', 'Absolute path of the folder that holds projects/, music_videos/, upload/… (default: the repo).',
            <Input placeholder="/data" />)}

          {backend !== 'local' && <>
            {!cfg.can_store_secrets && <Alert type="warning" showIcon className="!mb-3" message="Secrets cannot be saved here"
              description="The server has no STUDIO_SECRET_KEY, so keys are not stored. Set STUDIO_SECRET_KEY (see .env.example), or give the keys as S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY environment variables." />}
            {backend === 's3compat' && field('endpoint', 'Endpoint URL', <>e.g. <code>https://s3.us-west-004.backblazeb2.com</code>, <code>https://s3.wasabisys.com</code>, <code>https://minio.example.com</code>. https:// only{insecure ? ' (http:// and local addresses allowed: STUDIO_ALLOW_INSECURE_ENDPOINTS is on)' : ''}.</>,
              <Input placeholder="https://…" />, [{ required: true, message: 'The endpoint URL' }])}
            {backend === 'r2' && field('account_id', 'Cloudflare account ID', <>Cloudflare dashboard → R2 → the <b>Account ID</b> on the right (32 characters). The endpoint becomes <code>https://&lt;account id&gt;.r2.cloudflarestorage.com</code>, region <code>auto</code>.</>,
              <Input placeholder="0123456789abcdef0123456789abcdef" />, [{ required: true, message: 'The account ID' }])}
            <Row gutter={12}>
              <Col xs={24} md={12}>{field('bucket', 'Bucket', 'The bucket must already exist.', <Input placeholder="kawaii-chaos" />, [{ required: true, message: 'The bucket name' }])}</Col>
              <Col xs={24} md={12}>{field('prefix', 'Folder inside the bucket (optional)', 'Keeps the Studio files under this prefix, e.g. studio', <Input placeholder="studio" />)}</Col>
            </Row>
            {backend !== 'r2' && <Row gutter={12}>
              <Col xs={24} md={12}>{field('region', 'Region', backend === 's3' ? 'The bucket region, e.g. eu-west-1' : 'Usually us-east-1 unless your provider says otherwise', <Input placeholder="us-east-1" />)}</Col>
              {backend === 's3' && <Col xs={24} md={12}>{field('endpoint', 'Custom endpoint (optional)', 'Leave empty for AWS.', <Input placeholder="" />)}</Col>}
            </Row>}
            <Row gutter={12}>
              <Col xs={24} md={12}>{field('access_key_id', 'Access key ID', backend === 'r2' ? 'R2 → Manage API tokens → token with Object Read & Write on this bucket.' : backend === 's3' ? 'An IAM user/role key limited to this bucket (see DEPLOY.md for the policy). Leave both keys empty to use the server\'s IAM role.' : 'From your provider\'s console.',
                <Input autoComplete="off" />)}</Col>
              <Col xs={24} md={12}>
                <Form.Item label={<Space size={4}>Secret access key{lockIcon('secret_access_key')}</Space>} extra="Stored encrypted on the server and never shown again.">
                  {L('secret_access_key') ? <Input disabled value="••••••• set by environment" /> :
                    secretSet && !replaceSecret ? <Space><Tag icon={<LockOutlined />} color="green">••••• set</Tag><Button size="small" onClick={() => setReplaceSecret(true)}>Replace</Button></Space> :
                      <Form.Item name="secret_access_key" noStyle><Input.Password autoComplete="new-password" placeholder={secretSet ? 'new secret (leave empty to keep)' : ''} /></Form.Item>}
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col xs={24} md={8}><Form.Item name="force_path_style" valuePropName="checked" label={<Space size={4}>Path-style URLs{lockIcon('force_path_style')}</Space>} extra="On for MinIO and most self-hosted services."><Switch disabled={L('force_path_style')} /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="presign_downloads" valuePropName="checked" label={<Space size={4}>Direct downloads{lockIcon('presign_downloads')}</Space>} extra="Downloads go straight from the bucket via short-lived signed links (needs bucket CORS if used from the browser)."><Switch disabled={L('presign_downloads')} /></Form.Item></Col>
              <Col xs={24} md={8}>{field('public_base_url', 'Public base URL (optional)', 'Only if the bucket is served on a public https domain.', <Input placeholder="https://files.example.com" />)}</Col>
            </Row>
          </>}
        </Card>
      </Form>

      <Card size="small" data-tour="int-actions">
        <Space wrap>
          <Button icon={<ThunderboltOutlined />} loading={testing} onClick={doTest}>Test connection</Button>
          <Button icon={<CopyOutlined />} disabled={!!job && (job.state === 'running' || job.state === 'queued')} onClick={doMigrate}>Copy my files there…</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={doSave}>Save & switch</Button>
        </Space>
        {test && <Alert className="!mt-3" showIcon type={test.ok ? 'success' : 'error'}
          message={test.ok ? `Connected to ${test.backend} (${test.ms} ms)` : 'The connection test failed'}
          description={test.ok ? `Checked: ${(test.steps ?? []).join(', ')} a small test file.` : test.error} />}
        {job && <div className="mt-3"><JobPanel job={job} log={log} /></div>}
        <Typography.Paragraph type="secondary" className="!mt-3 !mb-0 text-xs">
          Environment variables on the server (STORAGE_BACKEND, S3_BUCKET, S3_SECRET_ACCESS_KEY, …) always win over what is saved here; those fields show a lock.
        </Typography.Paragraph>
      </Card>
      {tour}
    </div>
  )
}
