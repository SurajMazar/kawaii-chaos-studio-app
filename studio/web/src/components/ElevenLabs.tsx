import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Input, Popconfirm, Space, Tag, Typography } from 'antd'
import { CustomerServiceOutlined, LockOutlined, SaveOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { ElSubscription } from '../types'

/** Settings → Integrations → ElevenLabs: the API key for character voices (stored encrypted, never shown again). */
export default function ElevenLabsCard() {
  const { message } = App.useApp()
  const [st, setSt] = useState<{ set: boolean; locked: boolean; can_store: boolean } | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [sub, setSub] = useState<ElSubscription | null>(null)
  const load = () => api.eleven().then(setSt).catch(e => message.error(e.message))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (st?.set) api.voiceStatus(true).then(s => setSub(s.subscription)).catch(() => setSub(null)) }, [st?.set])
  const save = async () => {
    setBusy(true)
    try { const r = await api.saveEleven(key.trim()); setSub(r.subscription); setKey(''); message.success('ElevenLabs connected'); load() }
    catch (e) { message.error((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Card size="small" title={<span><CustomerServiceOutlined /> ElevenLabs (character voices)</span>} loading={!st}>
      <Typography.Paragraph type="secondary">Used by the <b>Voiceover</b> tab of a strip to make each character's lines with their voice. Without a key you can still upload clips made on elevenlabs.io.</Typography.Paragraph>
      {st?.locked ? <Alert type="info" showIcon message="The key is set by the ELEVENLABS_API_KEY environment variable on the server." /> : <>
        {!st?.can_store && <Alert className="!mb-2" type="warning" showIcon message="The server has no STUDIO_SECRET_KEY, so the key cannot be saved here — set ELEVENLABS_API_KEY instead." />}
        <Space wrap>
          {st?.set && <Tag icon={<LockOutlined />} color="green">key saved</Tag>}
          <Input.Password className="!w-80" autoComplete="new-password" placeholder={st?.set ? 'new key (replaces the saved one)' : 'sk_…'} value={key} onChange={e => setKey(e.target.value)} />
          <Button type="primary" icon={<SaveOutlined />} loading={busy} disabled={!key.trim() || !st?.can_store} onClick={save}>Test & save</Button>
          {st?.set && <Popconfirm title="Remove the ElevenLabs key?" onConfirm={async () => { await api.removeEleven(); setSub(null); load() }}><Button danger>Remove</Button></Popconfirm>}
        </Space>
      </>}
      {sub && <Typography.Paragraph className="!mt-2 !mb-0 text-xs">Plan <b>{sub.tier}</b> · credits used {(sub.used ?? 0).toLocaleString()} of {(sub.limit ?? 0).toLocaleString()}{sub.resets ? ` · resets ${new Date(sub.resets * 1000).toLocaleDateString()}` : ''}</Typography.Paragraph>}
      <Typography.Paragraph type="secondary" className="!mt-2 !mb-0 text-xs">elevenlabs.io → Profile → API keys → Create (allow Text to Speech, Voices and User read). The key is stored encrypted on the server and never sent back to the browser.</Typography.Paragraph>
    </Card>
  )
}
