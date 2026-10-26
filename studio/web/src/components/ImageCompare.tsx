import { useRef, useState } from 'react'
import { Button, Modal, Select, Space, Slider, Typography } from 'antd'
import { ZoomInOutlined } from '@ant-design/icons'

export interface CmpSource { label: string; url: string }

/** Side-by-side compare with the style master: both sides zoom and pan together (wheel = zoom, drag = pan). */
export default function ImageCompare({ open, onClose, left, sources, defaultRight }: {
  open: boolean; onClose: () => void; left: CmpSource; sources: CmpSource[]; defaultRight?: string
}) {
  const [right, setRight] = useState(defaultRight ?? sources[0]?.url)
  const [v, setV] = useState({ s: 1, x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top
    setV(o => { const s = Math.min(8, Math.max(1, o.s * (e.deltaY < 0 ? 1.15 : 0.87))); const k = s / o.s; return { s, x: mx - (mx - o.x) * k, y: my - (my - o.y) * k } })
  }
  const pane = (src: CmpSource, sel?: React.ReactNode) => (
    <div className="flex-1 min-w-0 flex flex-col gap-1">
      <div className="h-8 flex items-center">{sel ?? <Typography.Text strong className="truncate">{src.label}</Typography.Text>}</div>
      <div className="relative flex-1 overflow-hidden rounded-lg checker cursor-grab active:cursor-grabbing" onWheel={onWheel}
        onPointerDown={e => { (e.target as Element).setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, vx: v.x, vy: v.y } }}
        onPointerMove={e => { const d = drag.current; if (d) setV(o => ({ ...o, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y })) }}
        onPointerUp={() => { drag.current = null }}>
        <img src={src.url} draggable={false} className="absolute left-0 top-0 w-full select-none"
          style={{ transform: `translate(${v.x}px, ${v.y}px) scale(${v.s})`, transformOrigin: '0 0' }} />
      </div>
    </div>
  )
  return (
    <Modal open={open} onCancel={onClose} footer={null} width="94vw" style={{ top: 20 }} title={<Space><ZoomInOutlined />Compare side by side</Space>}
      styles={{ body: { height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' } }} destroyOnClose>
      <Space className="mb-2" wrap>
        <Typography.Text type="secondary">Wheel = zoom (both sides), drag = move. Compare line weight, eyes, fills and proportions — QA check G.</Typography.Text>
        <span className="label">zoom</span>
        <Slider className="w-40 !my-0" min={1} max={8} step={0.05} value={v.s} onChange={s => setV(o => ({ ...o, s }))} />
        <Button size="small" onClick={() => setV({ s: 1, x: 0, y: 0 })}>Reset</Button>
      </Space>
      <div className="flex gap-3 flex-1 min-h-0">
        {pane(left)}
        {pane({ label: '', url: right ?? '' }, <Select size="small" value={right} onChange={setRight} style={{ minWidth: 280 }} options={sources.map(s => ({ value: s.url, label: s.label }))} />)}
      </div>
    </Modal>
  )
}
