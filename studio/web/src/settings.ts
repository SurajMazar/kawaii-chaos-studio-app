import { useEffect, useState } from 'react'
import { api } from './api'
import type { Settings } from './types'

/** App settings shared by every page (loaded once; the Settings page pushes changes here). */
let cache: Settings | null = null
const subs = new Set<(s: Settings) => void>()

export function setAppSettings(s: Settings) { cache = s; subs.forEach(f => f(s)) }

export function useAppSettings() {
  const [s, setS] = useState<Settings | null>(cache)
  useEffect(() => {
    subs.add(setS)
    if (!cache) api.settings().then(setAppSettings).catch(() => {})
    return () => { subs.delete(setS) }
  }, [])
  return s
}

/** true when the pictures are your own drawings (no ChatGPT prompt / board / bundle steps). */
export const useOwnArt = () => useAppSettings()?.art_source === 'own'
