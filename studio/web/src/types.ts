export type Cut = 'ghost' | 'hard' | 'flash' | 'shake' | 'whoosh'
export type Style = 'block' | 'verse' | 'stack' | 'chorus'
export type Anim = 'type' | 'rise' | 'slam' | 'pop' | 'drop' | 'wave' | 'slide'

export interface Shot {
  image?: string
  at?: number
  zoom?: number
  focus?: [number, number]
  cut?: Cut
}

export interface Line {
  start: number
  end: number
  text: string
  style?: Style
  anim?: Anim
  image?: string
  shots?: Shot[]
  y?: number
  align?: 'left' | 'center' | 'right'
  flash?: boolean
  emoji?: string
  stripe?: string | null
  word_times?: number[]
}

export interface Edit {
  output?: string
  size?: [number, number]
  fps?: number
  start: number
  end?: number | null
  audio?: string | null
  fit?: 'cover' | 'extend'
  signature?: string
  signature_seconds?: number
  block_big?: number
  block_small?: number
  y?: number
  fonts?: Partial<Record<'verse' | 'heavy' | 'marker' | 'script' | 'emoji', string>>
  palette?: string[]
  accent?: string
  ink?: string
  block_fill?: string
  lines: Line[]
  [k: string]: unknown
}

export interface LyricProject { id: string; title: string; files: string[] }
export interface Media {
  images: { path: string; mtime: number }[]
  audio: { path: string }[]
  videos: { path: string; mtime: number; size: number }[]
}

export type JobState = 'queued' | 'running' | 'done' | 'error' | 'cancelled'
export interface Job {
  id: string; kind: string; title: string; ref?: string | null
  state: JobState; progress: number; done: number; total: number
  started: number; finished?: number | null; error?: string | null
  result?: Record<string, unknown> | null; step?: string
  log?: string[]; log_total: number
  quality?: 'preview' | 'final'; pid?: string; edit_hash?: string; owner?: string | null
}

export type Kind = 'strip' | 'mv'
export type QaState = 'pass' | 'stale' | 'none' | 'nofile' | 'revoked' | 'noimage'

export interface PieceStatus {
  synopsis?: boolean; charsheet?: boolean; layout?: boolean; strip?: boolean; qa?: QaState
  reel?: boolean; upload_image?: boolean; caption?: boolean; pinned?: boolean
  posted_image?: boolean; posted_reel?: boolean; posted?: boolean; storyboard?: boolean
  frames?: number; frames_pass?: number; qa_file?: boolean; edits?: number; voiceover?: boolean
}

export interface Item {
  kind: Kind; type: 'strip' | 'music_video' | 'lyric_edit'
  id: string; num: number; name: string; title: string; headline: string; couple: string
  thumb: string | null; mtime: number; created?: number; status: PieceStatus; sha?: string | null
  edits?: string[]; uploads?: string[]; renders?: string[]; error?: string
  texts?: Record<string, boolean>
}

export interface Stats {
  handle?: string; display_name?: string; followers?: number | null; followers_date?: string | null
  ig_posts?: number | null; ig_posts_date?: string | null; posted: number; mv_posted: number; ready: number
  per_couple: { couple: string; posted: number; ready: number }[]
  strips: number; strips_done: number; reels: number; music_videos: number
  last_posted?: { project: string; date?: string; format?: string; url?: string } | null
}

export interface FileEntry { name: string; path: string; is_dir: boolean; size: number; mtime: number; kind: string }
export interface ImgItem { path: string; name: string; mtime: number; size: number }
export interface QaCheck { key: string; title: string; text: string }
export interface QaTarget { file: string; sha: string | null; status: QaState }

export interface PostEntry {
  project: string; couple?: string; format: string; posted: boolean; date?: string; url?: string
  song?: string | null; song_ideas?: string; status?: string; file?: string
}
export interface Song { title: string; artist: string; group: string }
export interface Couple { name: string; tag: string; series: string; looks: string; short: string; dynamic: string }

export interface Settings {
  handle: string; signature: string; hashtags: string; python: string; downloads: string
  export_dir: string; chatgpt_url: string; style_ref: string; reel_seconds_per_panel: number
  art_source?: 'chatgpt' | 'own'
  local_features?: boolean
}

export type Role = 'viewer' | 'editor' | 'admin'
export interface User {
  id: number; email: string; name: string; role: Role; disabled: boolean; must_change_password: boolean
  totp_enabled: boolean; created_at: number; last_login_at?: number | null; last_login_ip?: string | null; locked?: boolean
}
export interface AuthState {
  setup_required: boolean; setup_token_required: boolean; user: User | null; csrf: string; env: string
  local_features: boolean; two_factor_available: boolean
}
export interface SessionInfo { sid: string; created_at: number; last_seen: number; expires_at: number; ip: string; user_agent: string; current?: boolean }
export type Backend = 'local' | 's3' | 'r2' | 's3compat'
export interface StorageConfig {
  backend: Backend; local_path?: string | null; endpoint?: string | null; region?: string | null; bucket?: string | null
  prefix?: string | null; access_key_id?: string | null; access_key_id_hint?: string; secret_access_key?: { set: boolean } | string
  force_path_style?: boolean; public_base_url?: string | null; presign_downloads?: boolean; account_id?: string | null
  locked?: string[]; can_store_secrets?: boolean; error?: string
}
export interface StorageStatus {
  active: string | null; remote: boolean | null; error: string | null; kind?: string
  objects?: number; index_age?: number; cache_bytes?: number; cache_dir?: string
}

export interface Tool { key: string; script: string; title: string; icon: string; desc: string; args: { name: string; label: string; default: string; kind: string; required?: boolean }[] }

// strip-reel storyboard (scripts/render.py)
export interface CamKey { t: number; x?: number; y?: number; zoom?: number; rot?: number; ease?: string }
export interface SbShot {
  id: string; image: string; start: number; end: number; mode?: 'card' | 'full'
  card?: { width?: number; aspect?: number; y?: number; intro?: boolean; radius?: number; border?: number; border_color?: number[]; bg_dark?: number }
  camera?: CamKey[]; ease?: string
  transition_in?: { type: string; dur?: number; dir?: string }
  [k: string]: unknown
}
export interface SbEvent { t: number; type?: string; sfx?: string; amp?: number; decay?: number; dur?: number; strength?: number; gain?: number; [k: string]: unknown }
export interface Storyboard {
  output: { width?: number; height?: number; fps?: number; duration?: number; file?: string; fade_in?: number; fade_out?: number }
  grade?: Record<string, number>
  shots: SbShot[]
  events?: SbEvent[]
  [k: string]: unknown
}
export type Box = [number, number, number, number]
export interface ReelInfo {
  has_strip: boolean; strip_size: [number, number] | null; strip_mtime: number | null
  boxes: Box[]; boxes_source: 'actual' | 'wireframe' | null; storyboard: Storyboard | null
  images: string[]; upload: Record<string, { path: string; size: number; mtime: number } | null>; per: number
}

// voiced strip reels (projects/<pid>/voiceover/voiceover.json + voices.json)
export interface VoiceLine { id: string; character: string; text: string; at: number; clip: string; gain_db: number; takes: string[]; voice_id?: string }
export interface VoiceMusic { file: string; gain_db: number; start: number; fade_in: number; fade_out: number; duck: boolean }
export interface VoiceoverConfig { video: string; output: string; lines: VoiceLine[]; music: VoiceMusic; loudness: number; model: string; source_take?: string }
export interface VoiceClip { name: string; size: number; mtime: number; duration: number | null }
export interface VoiceFile { path: string; size: number; mtime: number; duration?: number | null }
export interface VoiceoverInfo {
  exists: boolean; config: VoiceoverConfig; clips: VoiceClip[]; video: VoiceFile | null; video_path: string
  output: VoiceFile | null; output_path: string; readme: string; eleven: boolean
  suggestions: { panel: number; character: string; text: string; at: number }[]
}
export interface CastMember { name: string; series?: string; voice_name: string; voice_id: string; notes?: string }
export interface VoiceCast { model: string; note?: string; characters: CastMember[] }
export interface ElVoice { voice_id: string; name: string; category?: string; description?: string; labels?: string; has_preview: boolean; public_owner_id?: string }
export interface ElSubscription { tier?: string; used?: number; limit?: number; resets?: number | null }
