import { useEffect, useState } from 'react'
import { Button, Tooltip, Tour, type TourProps } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export interface TourStep { target?: string; title: string; description: React.ReactNode; placement?: TourProps['placement'] }

const key = (k: string) => `kcs.tour.${k}`
const seen = (k: string) => { try { return localStorage.getItem(key(k)) === 'done' } catch { return true } }
const markSeen = (k: string) => { try { localStorage.setItem(key(k), 'done') } catch { /* private window */ } }

/** First-run tour for a page. Steps point at elements with data-tour="<target>". Replay with the returned button. */
export function usePageTour(page: string, steps: TourStep[], ready = true) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!ready || seen(page)) return
    const id = setTimeout(() => setOpen(true), 700)
    return () => clearTimeout(id)
  }, [page, ready])
  const tourSteps: TourProps['steps'] = steps.map(s => ({
    title: s.title, description: s.description, placement: s.placement,
    target: s.target ? () => document.querySelector(`[data-tour="${s.target}"]`) as HTMLElement : null,
  }))
  const close = () => { setOpen(false); markSeen(page) }
  const tour = <Tour open={open} onClose={close} onFinish={close} steps={tourSteps} indicatorsRender={(cur, total) => <span>{cur + 1} / {total}</span>} />
  const button = (
    <Tooltip title="Take the tour of this page">
      <Button icon={<QuestionCircleOutlined />} onClick={() => setOpen(true)} data-tour="tour-button">Tour</Button>
    </Tooltip>
  )
  return { tour, button, open: () => setOpen(true) }
}

export function resetTours() {
  try { Object.keys(localStorage).filter(k => k.startsWith('kcs.tour.')).forEach(k => localStorage.removeItem(k)) } catch { /* ignore */ }
}
