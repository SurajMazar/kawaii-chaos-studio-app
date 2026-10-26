import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Collapse, Drawer, Empty, List, Popconfirm, Progress, Space, Tag, Tooltip, Typography } from 'antd'
import { CloseCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { api } from '../api'
import type { Job } from '../types'

const active = (j?: Job | null) => !!j && (j.state === 'queued' || j.state === 'running')

/** Poll a job until it finishes; collects the log incrementally. onDone fires once with the final job. */
export function useJob(id: string | null, onDone?: (j: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const [log, setLog] = useState<string[]>([])
  const done = useRef(onDone); done.current = onDone
  useEffect(() => {
    setJob(null); setLog([]); if (!id) return
    let alive = true, since = 0
    const tick = async () => {
      try {
        const j = await api.job(id, since)
        if (!alive) return
        if (j.log?.length) { const add = j.log; setLog(l => [...l, ...add].slice(-3000)); since = j.log_total }
        setJob(j)
        if (active(j)) setTimeout(tick, 600)
        else done.current?.(j)
      } catch { if (alive) setTimeout(tick, 1500) }
    }
    tick()
    return () => { alive = false }
  }, [id])
  return { job, log, running: active(job) || (!!id && !job) }
}

export function JobPanel({ job, log, title, showLog = true }: { job: Job | null; log: string[]; title?: string; showLog?: boolean }) {
  const pre = useRef<HTMLPreElement>(null)
  useEffect(() => { if (pre.current) pre.current.scrollTop = pre.current.scrollHeight }, [log.length])
  if (!job) return null
  const status = job.state === 'error' ? 'exception' : job.state === 'done' ? 'success' : job.state === 'cancelled' ? 'normal' : 'active'
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Typography.Text strong>{title ?? job.title}</Typography.Text>
        <StateTag job={job} />
        {active(job) && <Popconfirm title="Stop this job?" onConfirm={() => api.cancel(job.id)}>
          <Button size="small" danger icon={<CloseCircleOutlined />}>Stop</Button>
        </Popconfirm>}
      </div>
      <Progress percent={Math.round(job.progress * 100)} status={status} size="small" />
      {job.step && active(job) && <Typography.Text type="secondary" className="text-xs">{job.step}…</Typography.Text>}
      {job.error && <Typography.Text type="danger">{job.error}</Typography.Text>}
      {showLog && log.length > 0 && <Collapse size="small" ghost items={[{
        key: 'log', label: <span className="text-xs">Details ({log.length} lines)</span>,
        children: <pre ref={pre} className="max-h-56 overflow-auto text-[11px] leading-snug m-0 whitespace-pre-wrap opacity-80">{log.join('\n')}</pre>,
      }]} />}
    </div>
  )
}

export function StateTag({ job }: { job: Job }) {
  const c = { queued: 'default', running: 'processing', done: 'success', error: 'error', cancelled: 'warning' }[job.state]
  const t = { queued: 'waiting', running: 'working', done: 'done', error: 'failed', cancelled: 'stopped' }[job.state]
  return <Tag color={c}>{t}</Tag>
}

/** Header button + drawer listing every background job. */
export function JobsButton() {
  const [open, setOpen] = useState(false)
  const [jobs, setJobs] = useState<Job[]>([])
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try { const js = await api.jobs(); if (alive) setJobs(js) } catch { /* server restarting */ }
      if (alive) setTimeout(tick, open ? 1000 : 3000)
    }
    tick(); return () => { alive = false }
  }, [open])
  const n = jobs.filter(active).length
  return <>
    <Tooltip title="Background jobs (reel builds, renders, tools)">
      <Badge count={n} size="small" color="#ff5d8f">
        <Button icon={<ThunderboltOutlined />} onClick={() => setOpen(true)} data-tour="jobs">Jobs</Button>
      </Badge>
    </Tooltip>
    <Drawer title="Background jobs" open={open} onClose={() => setOpen(false)} width={520}>
      {jobs.length === 0 ? <Empty description="Nothing has run yet. Builds, renders and tools show up here while they work." /> :
        <List dataSource={jobs} renderItem={j => <List.Item><JobRow id={j.id} initial={j} /></List.Item>} />}
    </Drawer>
  </>
}

function JobRow({ id, initial }: { id: string; initial: Job }) {
  const [show, setShow] = useState(false)
  const { job, log } = useJob(show || active(initial) ? id : null)
  const j = job ?? initial
  return (
    <div className="w-full">
      <Space className="w-full" direction="vertical" size={2}>
        {show ? <JobPanel job={j} log={log} /> : <>
          <div className="flex items-center gap-2"><Typography.Text strong>{j.title}</Typography.Text><StateTag job={j} /></div>
          <Progress percent={Math.round(j.progress * 100)} size="small" status={j.state === 'error' ? 'exception' : j.state === 'done' ? 'success' : 'active'} />
        </>}
        <div className="flex gap-2 text-xs opacity-70">
          <span>{new Date(j.started * 1000).toLocaleTimeString()}</span>
          <a onClick={() => setShow(s => !s)}>{show ? 'hide details' : 'details'}</a>
        </div>
      </Space>
    </div>
  )
}
