import { useCallback, useEffect, useState } from 'react'
import { Button, Dropdown, Grid, Progress, Result, Skeleton, Steps, Tabs, Tag, Tooltip } from 'antd'
import { ExportOutlined, FolderOpenOutlined, ReloadOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { api } from '../api'
import { canLeave, go } from '../router'
import { PageHeader } from '../App'
import { usePageTour } from '../components/Tours'
import { StatusTags } from './Dashboard'
import { useOwnArt } from '../settings'
import type { Item, Kind } from '../types'
import ScriptTab from '../tabs/ScriptTab'
import LayoutTab from '../tabs/LayoutTab'
import PromptTab from '../tabs/PromptTab'
import ImagesTab from '../tabs/ImagesTab'
import SheetTab from '../tabs/SheetTab'
import QATab from '../tabs/QATab'
import ReelTab from '../tabs/ReelTab'
import PostTab from '../tabs/PostTab'
import FilesTab from '../tabs/FilesTab'
import LyricTab from '../tabs/LyricTab'
import VoiceTab from '../tabs/VoiceTab'

export interface TabProps { kind: Kind; id: string; item: Item; reload: () => Promise<void>; goTab: (t: string) => void }

interface StepDef { key: string; title: string; done: (i: Item) => boolean; hint: string }
const STRIP_STEPS: StepDef[] = [
  { key: 'script', title: 'Script', done: i => !!i.status.synopsis, hint: 'Write the panels, one short line each' },
  { key: 'layout', title: 'Layout', done: i => !!i.status.layout, hint: 'Random panel layout (optional for your own art)' },
  { key: 'prompt', title: 'Prompt', done: i => !!i.texts?.['prompt_final.txt'] || !!i.status.strip, hint: 'Prompt + reference board for ChatGPT (skip if you draw it yourself)' },
  { key: 'pictures', title: 'Pictures', done: i => !!i.status.strip, hint: 'Import or upload the strip, choose the final strip.png' },
  { key: 'qa', title: 'QA', done: i => i.status.qa === 'pass', hint: 'Check every item, then Mark PASS' },
  { key: 'reel', title: 'Reel', done: i => !!i.status.reel, hint: 'Build the silent strip reel' },
  { key: 'post', title: 'Post', done: i => !!i.status.posted, hint: 'Caption, song, mark as posted' },
]
const OWN_STEPS: StepDef[] = STRIP_STEPS.filter(s => s.key !== 'prompt').map(s =>
  s.key === 'layout' ? { ...s, hint: 'Optional panel guide to draw on' } : s.key === 'pictures' ? { ...s, hint: 'Upload your drawing, make it strip.png' } : s)
const MV_STEPS: StepDef[] = [
  { key: 'script', title: 'Story', done: i => !!i.status.synopsis, hint: 'A NEW story, never a strip joke' },
  { key: 'sheet', title: 'Character sheet', done: i => !!i.status.charsheet, hint: 'Make and check the cast sheet first' },
  { key: 'pictures', title: 'Pictures', done: i => (i.status.frames ?? 0) > 0, hint: 'Frames or your own pictures' },
  { key: 'qa', title: 'QA', done: i => !!i.status.frames && i.status.frames_pass === i.status.frames, hint: 'PASS every frame' },
  { key: 'lyric', title: 'Video', done: i => !!i.status.reel, hint: 'Lyric edit or music video render' },
  { key: 'post', title: 'Post', done: i => !!i.status.posted, hint: 'Caption and mark as posted' },
]

export default function PiecePage({ kind, id, tab }: { kind: Kind; id: string; tab?: string }) {
  const [item, setItem] = useState<Item | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const reload = useCallback(async () => {
    try { setItem(await api.piece(kind, id)); setErr(null) } catch (e) { setErr((e as Error).message) }
  }, [kind, id])
  useEffect(() => { reload() }, [reload])
  const own = useOwnArt()       // drawing the pictures yourself: no ChatGPT prompt step
  const steps = kind === 'strip' ? (own ? OWN_STEPS : STRIP_STEPS) : MV_STEPS
  const bp = Grid.useBreakpoint()
  const phone = bp.md === false
  const compactSteps = bp.xl === false               // < 1200 px: the 6–7 steps with their hints do not fit in one row
  const firstOpen = item ? steps.find(s => !s.done(item))?.key ?? 'post' : 'script'
  const active = tab ?? firstOpen
  const goTab = (t: string) => { if (t !== active && canLeave()) go(`/p/${kind}/${id}/${t}`) }

  const { tour, button } = usePageTour(kind === 'strip' ? 'strip' : 'mv', kind === 'strip' ? [
    { title: 'A strip project', description: 'Everything for one comic strip lives here, from the script to the Instagram post.' },
    { target: 'steps', title: 'Your progress', description: 'The steps light up as you finish them. Click a step to jump there. Drawing it yourself? Skip Layout and Prompt and go straight to Pictures.' },
    { target: 'tabs', title: 'Tabs', description: 'Script, Layout, Prompt for ChatGPT, Pictures, Character sheet, QA, Reel, Voiceover (an optional voiced version of the reel), Post and all Files.' },
    { target: 'status', title: 'Status', description: 'QA, reel, caption and posted badges — the same as on the library card.' },
    { target: 'reel-editor', title: 'Strip-reel editor', description: 'Fix the panel boxes, timing and camera moves of the reel, preview it and build it.' },
  ] : [
    { title: 'A music video / lyric edit', description: 'Story, character sheet, pictures, QA of every frame, the lyric edits and the post — all here.' },
    { target: 'steps', title: 'Your progress', description: 'Click a step to jump to it. Using your own pictures? Go straight to Pictures and Video.' },
    { target: 'tabs', title: 'Tabs', description: 'The Video tab lists the lyric edits of this folder and makes new ones.' },
  ], !!item)

  if (err) return <><PageHeader title={id} back={() => go('/')} /><Result status="warning" title="Could not open this project" subTitle={err} extra={<Button onClick={() => go('/')}>Back to the library</Button>} /></>
  if (!item) return <><PageHeader title={id} /><div className="p-6"><Skeleton active /></div></>

  const props: TabProps = { kind, id, item, reload, goTab }
  const tabs = kind === 'strip' ? [
    { key: 'script', label: 'Script', children: <ScriptTab {...props} /> },
    { key: 'layout', label: 'Layout', children: <LayoutTab {...props} /> },
    ...(own ? [] : [{ key: 'prompt', label: 'Prompt', children: <PromptTab {...props} /> }]),
    { key: 'pictures', label: 'Pictures', children: <ImagesTab {...props} /> },
    { key: 'sheet', label: 'Character sheet', children: <SheetTab {...props} /> },
    { key: 'qa', label: 'QA', children: <QATab {...props} /> },
    { key: 'reel', label: 'Reel', children: <ReelTab {...props} /> },
    { key: 'voice', label: <span>Voiceover{item.status.voiceover && <Tag color="purple" className="!ml-1 !text-[10px]">voiced</Tag>}</span>, children: <VoiceTab {...props} /> },
    { key: 'post', label: 'Post', children: <PostTab {...props} /> },
    { key: 'files', label: <span><FolderOpenOutlined /> Files</span>, children: <FilesTab {...props} /> },
  ] : [
    { key: 'script', label: 'Story', children: <ScriptTab {...props} /> },
    { key: 'sheet', label: 'Character sheet', children: <SheetTab {...props} /> },
    { key: 'pictures', label: 'Pictures', children: <ImagesTab {...props} /> },
    { key: 'qa', label: 'QA', children: <QATab {...props} /> },
    { key: 'lyric', label: 'Video', children: <LyricTab {...props} /> },
    { key: 'post', label: 'Post', children: <PostTab {...props} /> },
    { key: 'files', label: <span><FolderOpenOutlined /> Files</span>, children: <FilesTab {...props} /> },
  ]
  const cur = steps.findIndex(s => s.key === active)

  return (
    <>
      <PageHeader back={() => { if (canLeave()) go(kind === 'strip' ? '/' : '/music') }}
        title={<span>{item.headline} <span className="opacity-40 text-sm font-sans font-normal">#{item.num} · {item.id}</span></span>}
        sub={<span>{kind === 'strip' ? 'Comic strip' : item.type === 'lyric_edit' ? 'Lyric edit' : 'Music video'} · {item.couple} · {item.title}</span>}
        extra={<>
          <div data-tour="status" className="hidden xl:block"><StatusTags i={item} /></div>
          {kind === 'strip' && <Tooltip title="Panels, timing and camera of the strip reel"><Button icon={<VideoCameraOutlined />} onClick={() => go(`/reel/${id}`)} data-tour="reel-editor">Reel editor</Button></Tooltip>}
          <Dropdown menu={{ items: [
            { key: 'all', label: <a href={api.exportUrl(kind, id)}>Everything (.zip)</a> },
            { key: 'small', label: <a href={api.exportUrl(kind, id, false)}>Without videos (smaller; reels can be rebuilt)</a> },
          ] }}><Tooltip title="Download this project as a .zip to back it up or open it in another Studio (Library → Import)" placement="left"><Button icon={<ExportOutlined />}>Export</Button></Tooltip></Dropdown>
          <Tooltip title="Reload from disk"><Button icon={<ReloadOutlined />} onClick={reload} /></Tooltip>
          {button}
        </>} />
      <div className="flex-1 overflow-auto">
        {compactSteps ? <div className={`${phone ? 'px-3' : 'px-5'} pt-3 flex items-center gap-3`} data-tour="steps">
          <Progress type="circle" size={34} percent={Math.round(100 * steps.filter(s => s.done(item)).length / steps.length)} format={() => `${steps.filter(s => s.done(item)).length}/${steps.length}`} />
          <div className="min-w-0 text-xs"><div className="font-semibold">{steps.find(s => !s.done(item))?.title ?? 'All done'}{steps.find(s => !s.done(item)) ? ' — next' : ''}</div>
            <div className="opacity-60 truncate">{steps.find(s => !s.done(item))?.hint ?? 'Ready to post'}</div></div>
        </div> :
        <div className="px-5 pt-4" data-tour="steps">
          <Steps size="small" current={cur < 0 ? undefined : cur} onChange={i => goTab(steps[i].key)}
            items={steps.map(s => ({
              title: s.title, description: <span className="text-[11px]">{s.done(item) ? <Tag color="green" className="!text-[10px] !m-0">done</Tag> : s.hint}</span>,
              status: s.key === active ? 'process' : s.done(item) ? 'finish' : 'wait',
            }))} />
        </div>}
        <div className={phone ? 'px-3 pb-6' : 'px-5 pb-6'} data-tour="tabs">
          <Tabs activeKey={active} onChange={goTab} items={tabs} destroyInactiveTabPane />
        </div>
      </div>
      {tour}
    </>
  )
}
