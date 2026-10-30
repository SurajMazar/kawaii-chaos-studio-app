import type {
  AuthState, Box, Couple, Edit, FileEntry, ImgItem, Item, Job, Kind, LyricProject, Media, PostEntry, QaCheck, QaTarget, ReelInfo,
  SessionInfo, Settings, Song, Stats, StorageConfig, StorageStatus, Storyboard, Tool, User,
  ElSubscription, ElVoice, VoiceCast, VoiceoverConfig, VoiceoverInfo,
} from './types'

/** The CSRF token: read from the (non-HttpOnly) cookie each time, so a sign-in in another tab is picked up. */
let csrfMemo = ''
export function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)(?:__Host-kcs_csrf|kcs_csrf)=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : csrfMemo
}
export function setCsrf(t: string) { csrfMemo = t }

/** Fired when the server says the session is gone (401) — the AuthGate shows the sign-in page. */
export const AUTH_EVENT = 'kcs:auth-required'

export class ApiError extends Error {
  status: number; code?: string
  constructor(msg: string, status: number, code?: string) { super(msg); this.status = status; this.code = code }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = r.statusText, code: string | undefined
    try {
      const b = await r.json()
      const d = b.detail
      if (typeof d === 'string') msg = d
      else if (d && typeof d === 'object' && 'message' in d) { msg = String(d.message); code = d.code }
      else msg = JSON.stringify(d ?? b)
      code = code ?? b.code
    } catch { /* not json */ }
    if (r.status === 401 && !r.url.includes('/api/auth/')) window.dispatchEvent(new CustomEvent(AUTH_EVENT))
    if (r.status === 413) msg = msg || 'The file or request is too large.'
    throw new ApiError(msg || `HTTP ${r.status}`, r.status, code)
  }
  return r.json()
}
const send = (method: string, url: string, body?: unknown, signal?: AbortSignal) =>
  fetch(url, {
    method, credentials: 'same-origin', signal,
    headers: { 'content-type': 'application/json', 'x-csrf-token': csrfToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
const get = <T,>(url: string) => fetch(url, { credentials: 'same-origin' }).then(j<T>)
const post = <T,>(url: string, body?: unknown) => send('POST', url, body ?? {}).then(j<T>)
const put = <T,>(url: string, body: unknown) => send('PUT', url, body).then(j<T>)
const patch = <T,>(url: string, body: unknown) => send('PATCH', url, body).then(j<T>)
const del = <T,>(url: string) => send('DELETE', url).then(j<T>)
const upload = <T,>(url: string, fd: FormData) =>
  fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'x-csrf-token': csrfToken() } }).then(j<T>)
const q = encodeURIComponent
const P = (k: Kind, id: string) => `/api/p/${k}/${id}`

export const api = {
  // library
  library: () => get<{ items: Item[]; stats: Stats }>('/api/library'),
  piece: (k: Kind, id: string) => get<Item>(P(k, id)),
  // files
  fileUrl: (k: Kind, id: string, rel: string, bust?: number) => `${P(k, id)}/file/${rel.split('/').map(q).join('/')}${bust ? `?v=${Math.round(bust)}` : ''}`,
  downloadUrl: (k: Kind, id: string, rel: string) => `${P(k, id)}/file/${rel.split('/').map(q).join('/')}?download=1`,
  thumbUrl: (k: Kind, id: string, rel: string, w = 240, bust?: number) => `${P(k, id)}/thumb/${rel.split('/').map(q).join('/')}?w=${w}${bust ? `&v=${Math.round(bust)}` : ''}`,
  rootUrl: (rel: string, download = false) => `/api/root/${rel.split('/').map(q).join('/')}${download ? '?download=1' : ''}`,
  rootThumb: (rel: string, w = 240) => `/api/rthumb/${rel.split('/').map(q).join('/')}?w=${w}`,
  files: (k: Kind, id: string, dir: string) => get<{ dir: string; entries: FileEntry[] }>(`${P(k, id)}/files?dir=${q(dir)}`),
  share: (k: Kind, id: string, rel: string, rect: number[]) => post<{ ok: boolean }>(`${P(k, id)}/share`, { rel, rect }),   // Mac app: macOS share menu
  text: (k: Kind, id: string, name: string) => get<{ name: string; exists: boolean; text: string; mtime: number | null }>(`${P(k, id)}/text?name=${q(name)}`),
  saveText: (k: Kind, id: string, name: string, text: string) => put<{ ok: boolean }>(`${P(k, id)}/text?name=${q(name)}`, { text }),
  images: (k: Kind, id: string) => get<{ groups: { key: string; title: string; items: ImgItem[] }[]; stylechecks: { path: string; name: string; mtime: number }[] }>(`${P(k, id)}/images`),
  upload: (k: Kind, id: string, file: File, dest = 'raw', role = '') => {
    const fd = new FormData(); fd.append('file', file); fd.append('dest', dest); fd.append('role', role)
    return upload<{ path: string }>(`${P(k, id)}/upload`, fd)
  },
  setRole: (k: Kind, id: string, src: string, role: 'strip' | 'charsheet') => post<{ ok: boolean; sha?: string }>(`${P(k, id)}/set-role`, { src, role }),
  reject: (k: Kind, id: string, src: string, reason: string) => post<{ path: string }>(`${P(k, id)}/reject`, { src, reason }),
  restore: (k: Kind, id: string, src: string) => post<{ path: string }>(`${P(k, id)}/restore`, { src }),
  refs: () => get<{ name: string; path: string }[]>('/api/refs'),
  downloads: () => get<{ dir: string; items: { name: string; size: number; mtime: number; bundle: boolean }[] }>('/api/downloads'),
  downloadsThumb: (name: string, w = 200) => `/api/downloads/thumb?name=${q(name)}&w=${w}`,
  importDownloads: (k: Kind, id: string, names: string[]) => post<{ paths: string[] }>(`${P(k, id)}/import`, { names }),
  importBundles: (k: Kind, id: string, prefix = '') => post<Job>(`${P(k, id)}/import-bundles`, { prefix }),
  exportFile: (path: string) => post<{ path: string }>('/api/export', { path }),
  // qa
  qa: (k: Kind, id: string) => get<{ exists: boolean; text: string; checklist: QaCheck[]; targets: QaTarget[] }>(`${P(k, id)}/qa`),
  qaPass: (k: Kind, id: string, file: string, checks: Record<string, boolean>, notes: Record<string, string>, stranger: string) =>
    post<{ sha: string }>(`${P(k, id)}/qa/pass`, { file, checks, notes, stranger }),
  qaFail: (k: Kind, id: string, file: string, failed: Record<string, string>, stranger: string) => post(`${P(k, id)}/qa/fail`, { file, failed, stranger }),
  qaRevoke: (k: Kind, id: string, file: string) => post(`${P(k, id)}/qa/revoke`, { file }),
  // strip tools
  layout: (id: string) => get<{ exists: boolean; text: string; mtime: number | null; panels: number }>(`${P('strip', id)}/layout`),
  makeLayout: (id: string, panels: number, seed: number | null, punch: boolean) => post<{ text: string }>(`${P('strip', id)}/layout`, { panels, seed, punch }),
  promptParts: (id: string) => get<{
    header: string; layout: string; panels: { n: number; text: string }[]; locks: { key: string; title: string; text: string; default: boolean }[]
    couple: string; couple_rule: string; prompt_final: string; charsheet_prompt: string; has_charsheet: boolean; has_layout: boolean
    chatgpt_url: string; style_ref: string
  }>(`${P('strip', id)}/prompt-parts`),
  board: (k: Kind, id: string, style: string) => post<{ path: string; parts: string[]; mtime: number }>(`${P(k, id)}/board`, { style }),
  sheetHeights: (k: Kind, id: string, src: string, ratios: string, ref: number | null) => post<Job>(`${P(k, id)}/sheet-heights`, { src, ratios, ref }),
  styleCheck: (k: Kind, id: string, src: string) => post<Job>(`${P(k, id)}/style-check`, { src }),
  reelStatus: (id: string) => get<Record<string, { path: string; size: number; mtime: number } | null>>(`${P('strip', id)}/reel-status`),
  reelAuto: (id: string) => post<Job>(`${P('strip', id)}/reel/auto`),
  // posts
  post: (k: Kind, id: string) => get<{ caption: string; pinned: string; in_captions_json: boolean; synopsis_caption: string; song_ideas: string[]; posts: PostEntry[]; couple: string; hashtags: string; handle: string }>(`${P(k, id)}/post`),
  saveCaption: (k: Kind, id: string, caption: string, pinned: string) => put(`${P(k, id)}/caption`, { caption, pinned }),
  markPosted: (k: Kind, id: string, b: { format: string; date: string; song: string; url: string; note: string }) => post(`${P(k, id)}/posted`, b),
  unmarkPosted: (k: Kind, id: string, format: string) => post(`${P(k, id)}/unposted`, { format }),
  songs: () => get<Song[]>('/api/songs'),
  couples: () => get<Couple[]>('/api/couples'),
  saveCouples: (couples: Pick<Couple, 'name' | 'tag' | 'series' | 'looks' | 'dynamic'>[]) => put<Couple[]>('/api/couples', { couples }),
  exportUrl: (k: Kind, id: string, videos = true) => `${P(k, id)}/export.zip${videos ? '' : '?videos=false'}`,
  importProject: (file: File, posts = true) => { const fd = new FormData(); fd.append('file', file); return upload<{ kind: Kind; id: string; files: number; renamed_from: string; skipped: string[] }>(`/api/import?posts=${posts}`, fd) },
  // reel editor
  reel: (id: string) => get<ReelInfo>(`/api/reel/${id}`),
  reelDetect: (id: string) => post<{ boxes: Box[]; log: string }>(`/api/reel/${id}/detect`),
  reelSaveBoxes: (id: string, boxes: Box[]) => put(`/api/reel/${id}/boxes`, { boxes }),
  reelMakeStoryboard: (id: string, per: number) => post<{ storyboard: Storyboard }>(`/api/reel/${id}/storyboard`, { per }),
  reelRecrop: (id: string) => post<{ storyboard: Storyboard }>(`/api/reel/${id}/recrop`),
  reelSave: (id: string, storyboard: Storyboard) => put(`/api/reel/${id}/storyboard`, { storyboard }),
  reelStill: async (id: string, storyboard: Storyboard, t: number, scale: number, signal?: AbortSignal) => {
    const r = await send('POST', `/api/reel/${id}/still`, { storyboard, t, scale }, signal)
    if (!r.ok) { if (r.status === 401) window.dispatchEvent(new CustomEvent(AUTH_EVENT)); throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText) }
    return r.blob()
  },
  reelBuild: (id: string, storyboard: Storyboard | null) => post<Job>(`/api/reel/${id}/build`, { storyboard }),
  // voiceover (voiced strip reel) + ElevenLabs
  voiceover: (id: string) => get<VoiceoverInfo>(`${P('strip', id)}/voiceover`),
  saveVoiceover: (id: string, config: VoiceoverConfig) => put<{ ok: boolean; config: VoiceoverConfig }>(`${P('strip', id)}/voiceover`, { config }),
  uploadVoiceClip: (id: string, file: File) => { const fd = new FormData(); fd.append('file', file); return upload<{ name: string; duration: number | null }>(`${P('strip', id)}/voiceover/clip`, fd) },
  generateLine: (id: string, b: { text: string; voice_id: string; character: string; model: string; stability?: number | null }) =>
    post<{ name: string; duration: number | null; characters: number }>(`${P('strip', id)}/voiceover/generate`, b),
  mixVoiceover: (id: string, config: VoiceoverConfig) => post<Job>(`${P('strip', id)}/voiceover/mix`, { config }),
  voiceStatus: (credits = false) => get<{ configured: boolean; models: { value: string; label: string }[]; subscription: ElSubscription | null }>(`/api/voice/status${credits ? '?credits=true' : ''}`),
  myVoices: (refresh = false) => get<ElVoice[]>(`/api/voice/voices${refresh ? '?refresh=true' : ''}`),
  voiceLibrary: (search: string) => get<ElVoice[]>(`/api/voice/library?search=${q(search)}`),
  addLibraryVoice: (v: { public_owner_id: string; voice_id: string; name: string }) => post<{ voice_id: string }>('/api/voice/library/add', v),
  voicePreviewUrl: (voiceId: string) => `/api/voice/preview/${q(voiceId)}`,
  cast: () => get<VoiceCast>('/api/voice/cast'),
  saveCast: (cast: VoiceCast) => put<VoiceCast>('/api/voice/cast', { cast }),
  eleven: () => get<{ set: boolean; locked: boolean; can_store: boolean }>('/api/integrations/elevenlabs'),
  saveEleven: (api_key: string) => put<{ ok: boolean; subscription: ElSubscription }>('/api/integrations/elevenlabs', { api_key }),
  removeEleven: () => del<{ ok: boolean; set: boolean }>('/api/integrations/elevenlabs'),
  // lyric
  lyricProjects: (all = false) => get<LyricProject[]>(`/api/lyric${all ? '?all=true' : ''}`),
  edit: (pid: string, file: string) => get<Edit>(`/api/lyric/${pid}/edit?file=${q(file)}`),
  save: (pid: string, file: string, edit: Edit) => put<{ ok: boolean }>(`/api/lyric/${pid}/edit?file=${q(file)}`, edit),
  copy: (pid: string, src: string, dst: string) => post(`/api/lyric/${pid}/copy`, { src, dst }),
  newEdit: (pid: string, b: { file: string; mode: string; src_pid?: string; src_file?: string; start: number; seconds_per_line?: number; audio?: string; lines_text?: string; signature?: string }) =>
    post<{ file: string }>(`/api/lyric/${pid}/new`, b),
  media: (pid: string) => get<Media>(`/api/lyric/${pid}/media`),
  still: async (pid: string, edit: Edit, t: number, scale: number, signal?: AbortSignal) => {
    const r = await send('POST', `/api/lyric/${pid}/still`, { edit, t, scale }, signal)
    if (!r.ok) { if (r.status === 401) window.dispatchEvent(new CustomEvent(AUTH_EVENT)); throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText) }
    return r.blob()
  },
  /** Smooth Play: a small rendered video of this exact edit (cached server-side per edit version). */
  playback: (pid: string, edit: Edit) =>
    post<{ state: 'ready' | 'rendering' | 'queued' | 'error'; key: string; url?: string; progress: number; error?: string }>(`/api/lyric/${pid}/playback`, { edit }),
  render: (pid: string, edit: Edit, file: string, quality: 'preview' | 'final', bake_audio: boolean) =>
    post<Job>(`/api/lyric/${pid}/render`, { edit, file, quality, bake_audio }),
  fonts: () => get<{ name: string; path: string; size: number }[]>('/api/fonts'),
  uploadFont: (file: File) => { const fd = new FormData(); fd.append('file', file); return upload<{ path: string }>('/api/fonts', fd) },
  fontSample: (path: string, text = 'Kawaii Chaos') => `/api/fonts/sample?path=${q(path)}&text=${q(text)}`,
  // jobs
  jobs: (active = false) => get<Job[]>(`/api/jobs${active ? '?active=true' : ''}`),
  job: (id: string, since?: number) => get<Job>(`/api/jobs/${id}${since !== undefined ? `?since=${since}` : ''}`),
  cancel: (id: string) => post(`/api/jobs/${id}/cancel`),
  // new / tools / settings
  newProject: (b: { kind: string; name: string; couple: string; tag: string; premise: string; panels: number; seed: number | null; layout: boolean; mood: string; lines: string; start: number }) =>
    post<{ kind: Kind; id: string; log: string }>('/api/new', b),
  tools: () => get<Tool[]>('/api/tools'),
  runTool: (key: string, args: Record<string, string>) => post<Job>(`/api/tools/${key}/run`, { args }),
  settings: () => get<Settings>('/api/settings'),
  saveSettings: (s: Partial<Settings>) => put<Settings>('/api/settings', s),
  // auth (own account)
  authState: () => get<AuthState>('/api/auth/state'),
  setup: (b: { email: string; password: string; name: string; setup_token?: string }) => post<{ user: User; csrf: string }>('/api/auth/setup', b),
  login: (b: { email: string; password: string; totp?: string }) => post<{ user: User; csrf: string }>('/api/auth/login', b),
  logout: () => post('/api/auth/logout'),
  logoutAll: () => post('/api/auth/logout-all'),
  me: () => get<User>('/api/auth/me'),
  changePassword: (current_password: string, new_password: string) => post<{ user: User; csrf: string }>('/api/auth/password', { current_password, new_password }),
  mySessions: () => get<SessionInfo[]>('/api/auth/sessions'),
  revokeMySession: (sid: string) => del(`/api/auth/sessions/${q(sid)}`),
  totpSetup: (password: string) => post<{ secret: string; uri: string }>('/api/auth/totp/setup', { password }),
  totpConfirm: (code: string) => post('/api/auth/totp/confirm', { code }),
  totpDisable: (password: string) => post('/api/auth/totp/disable', { password }),
  // users (admin)
  users: () => get<User[]>('/api/users'),
  createUser: (b: { email: string; name: string; role: string; password?: string }) => post<{ user: User; temporary_password: string | null }>('/api/users', b),
  updateUser: (id: number, b: { role?: string; disabled?: boolean; name?: string }) => patch<User>(`/api/users/${id}`, b),
  resetPassword: (id: number) => post<{ temporary_password: string }>(`/api/users/${id}/reset-password`),
  disable2fa: (id: number) => post(`/api/users/${id}/disable-2fa`),
  deleteUser: (id: number) => del(`/api/users/${id}`),
  userSessions: (id: number) => get<SessionInfo[]>(`/api/users/${id}/sessions`),
  revokeSession: (id: number, sid: string) => del(`/api/users/${id}/sessions/${q(sid)}`),
  revokeAllSessions: (id: number) => del(`/api/users/${id}/sessions`),
  // storage integration (admin)
  storage: () => get<{ config: StorageConfig; status: StorageStatus; allow_insecure: boolean; running_jobs: number }>('/api/integrations/storage'),
  storageTest: (c: Partial<StorageConfig>) => post<{ ok: boolean; error?: string; steps?: string[]; ms?: number; backend?: string }>('/api/integrations/storage/test', c),
  storagePlan: (c: Partial<StorageConfig>) => post<{ source: string; target: string; objects: number; bytes: number; existing_same_size: number; target_objects: number }>('/api/integrations/storage/migrate/plan', c),
  storageMigrate: (c: Partial<StorageConfig>) => post<Job>('/api/integrations/storage/migrate', c),
  storageSave: (c: Partial<StorageConfig>) => put<{ ok: boolean; config: StorageConfig; status: StorageStatus }>('/api/integrations/storage', c),
}
