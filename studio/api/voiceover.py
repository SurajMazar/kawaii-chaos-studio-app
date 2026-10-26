"""Voiced strip reels: character voices (ElevenLabs or your own recordings) on the silent strip reel.

Per strip: projects/<pid>/voiceover/voiceover.json = voice lines placed on the silent reel (clip files in voiceover/), a
music bed and the loudness. scripts/voiceover_mix.py mixes it onto upload/<pid>_strip_reel.mp4 ->
upload/<pid>_strip_reel_voiceover.mp4.
The voice cast (which ElevenLabs voice each character speaks with) is voices.json at the content root.
Lines are made with the ElevenLabs API (Settings → Integrations → ElevenLabs; the key is stored encrypted like the storage
secret and never sent to the browser) or recorded on the ElevenLabs website and uploaded.
"""
import json, os, re, tempfile, threading, time  # nosec B404 - argument lists only
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from .deps import authorize

from config import CONFIG
from security import ratelimit
from security.context import min_role
from security.validation import check_upload, safe_rel

from . import jobs
from .core import AUDIO_EXT, ROOT, SCRIPTS, piece_dir, read_json, read_text, safe_join, script_python, write_atomic, write_json
from .library import invalidate

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
CAST = ROOT / 'voices.json'
API = 'https://api.elevenlabs.io'
MODELS = {'eleven_v3': 'Eleven v3 — most expressive, understands [tags] like [deadpan]',
          'eleven_multilingual_v2': 'Multilingual v2 — steady and natural',
          'eleven_flash_v2_5': 'Flash v2.5 — fast and cheap',
          'eleven_turbo_v2_5': 'Turbo v2.5 — fast'}
VOICE_ID = re.compile(r'^[A-Za-z0-9]{8,40}$')
CLIP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]{0,119}$')
MAX_AUDIO = 25 << 20


# ---------------- ElevenLabs key (encrypted in <config>/elevenlabs.json; ELEVENLABS_API_KEY wins) ----------------
def _key_file() -> Path:
    return CONFIG.config_dir / 'elevenlabs.json'


def _fernet():
    from storage.settings import _fernet as mk
    if not CONFIG.secret_key:
        raise HTTPException(400, 'STUDIO_SECRET_KEY is not set, so the key cannot be stored safely — set ELEVENLABS_API_KEY on the server instead.')
    return mk(CONFIG.secret_key, os.environ.get('STUDIO_SECRET_KEY_OLD', ''))


def api_key() -> str:
    env = os.environ.get('ELEVENLABS_API_KEY', '').strip()
    if env: return env
    try: enc = json.loads(_key_file().read_text()).get('api_key_enc')
    except (FileNotFoundError, json.JSONDecodeError, OSError): return ''
    if not enc or not CONFIG.secret_key: return ''
    try: return _fernet().decrypt(enc.encode()).decode()
    except Exception: return ''    # nosec B110 - wrong/rotated secret key: treated as "not connected"


def _save_key(key: str | None):
    f = _key_file(); f.parent.mkdir(parents=True, exist_ok=True)
    data = {'api_key_enc': _fernet().encrypt(key.encode()).decode(), 'saved': time.time()} if key else {}
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix='.elevenlabs.', suffix='.tmp')
    with os.fdopen(fd, 'w') as fh: json.dump(data, fh)
    os.chmod(tmp, 0o600); os.replace(tmp, f)


def _err_text(e: urllib.error.HTTPError) -> str:
    try:
        d = json.loads(e.read(20000) or b'{}').get('detail')
        if isinstance(d, dict): return str(d.get('message') or d.get('status') or '')[:300]
        if isinstance(d, str): return d[:300]
        if isinstance(d, list) and d: return str(d[0].get('msg', ''))[:300]
    except Exception: pass  # nosec B110 - best effort
    return ''


def el(method: str, path: str, body=None, query=None, audio=False, key=None, timeout=90):
    """One ElevenLabs API call (fixed host). Their 401 is never passed on as 401 (that would sign the user out)."""
    key = key or api_key()
    if not key: raise HTTPException(409, 'ElevenLabs is not connected yet — an admin adds the API key in Settings → Integrations → ElevenLabs.')
    url = API + path + ('?' + urllib.parse.urlencode(query) if query else '')
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={'xi-api-key': key, 'content-type': 'application/json', 'accept': 'audio/mpeg' if audio else 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed https host
            data = r.read(MAX_AUDIO + 1)
    except urllib.error.HTTPError as e:
        why = _err_text(e)
        if e.code in (401, 403): raise HTTPException(400, f'ElevenLabs refused the API key{": " + why if why else ""}.')
        if e.code == 402 or 'quota' in why.lower() or 'credits' in why.lower(): raise HTTPException(409, f'Not enough ElevenLabs credits{": " + why if why else ""}.')
        if e.code == 429: raise HTTPException(429, 'ElevenLabs is busy (too many requests) — try again in a minute.')
        if e.code in (400, 404, 422): raise HTTPException(400, f'ElevenLabs: {why or "bad request"}')
        raise HTTPException(502, f'ElevenLabs error {e.code}{": " + why if why else ""}')
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HTTPException(502, 'Could not reach ElevenLabs — check the internet connection.')
    if len(data) > MAX_AUDIO: raise HTTPException(502, 'ElevenLabs sent an unexpectedly large answer.')
    return data if audio else json.loads(data or b'{}')


def _subscription(key=None):
    s = el('GET', '/v1/user/subscription', key=key, timeout=20)
    return dict(tier=s.get('tier'), used=s.get('character_count'), limit=s.get('character_limit'),
                resets=s.get('next_character_count_reset_unix'))


@router.get('/api/integrations/elevenlabs')
@min_role('admin')
def get_eleven():
    return dict(set=bool(api_key()), locked=bool(os.environ.get('ELEVENLABS_API_KEY', '').strip()), can_store=bool(CONFIG.secret_key))


@router.put('/api/integrations/elevenlabs')
@min_role('admin')
def put_eleven(api_key_: str = Body(..., embed=True, alias='api_key')):
    key = (api_key_ or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_\-]{20,200}', key): raise HTTPException(400, 'That does not look like an ElevenLabs API key (Profile → API keys → Create).')
    sub = _subscription(key)                       # test before saving
    _save_key(key); _VOICES.clear()
    return dict(ok=True, set=True, subscription=sub)


@router.delete('/api/integrations/elevenlabs')
@min_role('admin')
def delete_eleven():
    _save_key(None); _VOICES.clear()
    return dict(ok=True, set=bool(api_key()))


# ---------------- voices (account + Voice Library) ----------------
_VOICES: dict = {}          # 'mine' -> (time, list); voice_id -> preview url
_vlock = threading.Lock()


def _voice(v, library=False):
    lab = v if library else (v.get('labels') if isinstance(v.get('labels'), dict) else {})
    out = dict(voice_id=v.get('voice_id'), name=v.get('name'), category=v.get('category'),
               description=(v.get('description') or '')[:300], has_preview=bool(v.get('preview_url')),
               labels=', '.join(str(lab[k]) for k in ('gender', 'age', 'accent', 'use_case') if lab.get(k))[:200])
    if library: out['public_owner_id'] = v.get('public_owner_id')
    if v.get('preview_url') and v.get('voice_id'): _VOICES['p:' + v['voice_id']] = v['preview_url']
    return out


@router.get('/api/voice/status')
def voice_status(credits: bool = False):
    on = bool(api_key())
    return dict(configured=on, models=[dict(value=k, label=v) for k, v in MODELS.items()],
                subscription=_subscription() if on and credits else None)


@router.get('/api/voice/voices')
@min_role('editor')
def my_voices(refresh: bool = False):
    with _vlock:
        hit = _VOICES.get('mine')
        if hit and not refresh and time.time() - hit[0] < 120: return hit[1]
    vs = [_voice(v) for v in el('GET', '/v1/voices', timeout=30).get('voices', [])]
    vs.sort(key=lambda v: (v['category'] == 'premade', (v['name'] or '').lower()))
    with _vlock: _VOICES['mine'] = (time.time(), vs)
    return vs


@router.get('/api/voice/library')
@min_role('editor')
def library_search(search: str = ''):
    if len(search) > 80: raise HTTPException(400, 'search is too long')
    ratelimit.hit(ratelimit.user_key('voicelib'), 10, 0.5, 'voice searches')
    r = el('GET', '/v1/shared-voices', query=dict(page_size=30, search=search) if search else dict(page_size=30), timeout=30)
    return [_voice(v, library=True) for v in r.get('voices', [])]


@router.post('/api/voice/library/add')
@min_role('editor')
def library_add(public_owner_id: str = Body(...), voice_id: str = Body(...), name: str = Body(...)):
    if not VOICE_ID.match(voice_id) or not re.fullmatch(r'[A-Za-z0-9]{8,80}', public_owner_id or ''): raise HTTPException(400, 'bad voice')
    name = re.sub(r'[\x00-\x1f]', '', name or '')[:100] or 'Library voice'
    r = el('POST', f'/v1/voices/add/{public_owner_id}/{voice_id}', body=dict(new_name=name), timeout=30)
    _VOICES.pop('mine', None)
    return dict(ok=True, voice_id=r.get('voice_id') or voice_id)


@router.get('/api/voice/preview/{voice_id}')
def voice_preview(voice_id: str):
    """Plays a voice's sample through the Studio (the page may only load media from itself)."""
    url = _VOICES.get('p:' + voice_id)
    if not VOICE_ID.match(voice_id) or not url: raise HTTPException(404, 'no preview for this voice (list the voices again)')
    u = urllib.parse.urlparse(url)
    if u.scheme != 'https' or not (u.hostname or '').endswith(('.googleapis.com', '.elevenlabs.io')): raise HTTPException(404, 'no preview')
    try:
        with urllib.request.urlopen(url, timeout=20) as r: data = r.read(5 << 20)  # nosec B310 - https + host allow-list
    except (urllib.error.URLError, TimeoutError, OSError): raise HTTPException(502, 'Could not load the voice sample.')
    return Response(data, media_type='audio/mpeg', headers={'Cache-Control': 'private, max-age=3600'})


# ---------------- voice cast (voices.json) ----------------
def load_cast():
    c = read_json(CAST, None) or {}
    return dict(model=c.get('model') if c.get('model') in MODELS else 'eleven_v3', note=c.get('note', ''), characters=c.get('characters', []))


def _s(v, n, what):
    if v is None: return ''
    if not isinstance(v, str) or len(v) > n or '\x00' in v: raise HTTPException(400, f'{what} is too long')
    return v.strip()


@router.get('/api/voice/cast')
def get_cast():
    return load_cast()


@router.put('/api/voice/cast')
def put_cast(cast: dict = Body(..., embed=True)):
    chars = cast.get('characters') or []
    if not isinstance(chars, list) or len(chars) > 100: raise HTTPException(400, 'At most 100 characters.')
    out = []
    for c in chars:
        if not isinstance(c, dict): raise HTTPException(400, 'bad character')
        vid = _s(c.get('voice_id'), 40, 'voice id')
        if vid and not VOICE_ID.match(vid): raise HTTPException(400, f'Bad voice id for {c.get("name")!r}')
        name = _s(c.get('name'), 60, 'name')
        if not name: raise HTTPException(400, 'Every character needs a name.')
        out.append({k: v for k, v in dict(name=name, series=_s(c.get('series'), 60, 'series'), voice_name=_s(c.get('voice_name'), 120, 'voice name'),
                                         voice_id=vid, notes=_s(c.get('notes'), 500, 'notes')).items() if v or k in ('voice_id', 'voice_name')})
    model = cast.get('model') if cast.get('model') in MODELS else 'eleven_v3'
    prev = read_json(CAST, None) or {}
    write_json(CAST, dict(model=model, note=prev.get('note', ''), characters=out))
    return load_cast()


# ---------------- per strip: voiceover.json ----------------
def vo_dir(pid): return piece_dir('strip', pid) / 'voiceover'


def default_cfg(pid):
    return dict(video=f'upload/{pid}_strip_reel.mp4', output=f'upload/{pid}_strip_reel_voiceover.mp4', lines=[],
                music=dict(file='', gain_db=-10, start=0, fade_in=0.6, fade_out=1.8, duck=True), loudness=-16, model=load_cast()['model'])


def _num(v, lo, hi, what, default=0.0):
    if v is None or v == '': return default
    try: x = float(v)
    except (TypeError, ValueError): raise HTTPException(400, f'{what} must be a number')
    if not lo <= x <= hi: raise HTTPException(400, f'{what} must be between {lo} and {hi}')
    return round(x, 3)


def _clip(v, what='clip'):
    if not v: return ''
    if not isinstance(v, str) or not CLIP_NAME.match(v) or Path(v).suffix.lower() not in AUDIO_EXT:
        raise HTTPException(400, f'Bad {what}: {str(v)[:60]!r} (an audio file inside voiceover/)')
    return v


def check_cfg(pid, c: dict) -> dict:
    if not isinstance(c, dict): raise HTTPException(400, 'bad voiceover')
    video = safe_rel(c.get('video') or f'upload/{pid}_strip_reel.mp4', 'video')
    if not video.endswith('.mp4') or not (video.startswith('upload/') or video.startswith(f'projects/{pid}/')):
        raise HTTPException(400, 'The video must be an .mp4 in upload/ or in this project.')
    output = safe_rel(c.get('output') or f'upload/{pid}_strip_reel_voiceover.mp4', 'output')
    if not output.startswith('upload/') or not output.endswith('.mp4') or output == video: raise HTTPException(400, 'The output must be a new .mp4 in upload/.')
    lines = c.get('lines') or []
    if not isinstance(lines, list) or len(lines) > 60: raise HTTPException(400, 'At most 60 lines.')
    out = []
    for i, ln in enumerate(lines):
        if not isinstance(ln, dict): raise HTTPException(400, 'bad line')
        lid = str(ln.get('id') or f'l{i + 1}')
        if not re.fullmatch(r'[A-Za-z0-9_\-]{1,20}', lid): raise HTTPException(400, 'bad line id')
        takes = ln.get('takes') or []
        if not isinstance(takes, list) or len(takes) > 30: raise HTTPException(400, 'too many takes')
        vid = _s(ln.get('voice_id'), 40, 'voice id')
        if vid and not VOICE_ID.match(vid): raise HTTPException(400, 'bad voice id')
        out.append(dict(id=lid, character=_s(ln.get('character'), 60, 'character'), text=_s(ln.get('text'), 1000, 'line text'),
                        at=_num(ln.get('at'), 0, 600, 'start time'), clip=_clip(ln.get('clip')), gain_db=_num(ln.get('gain_db'), -30, 12, 'line volume'),
                        takes=[_clip(t, 'take') for t in takes if t], **({'voice_id': vid} if vid else {})))
    m = c.get('music') or {}
    music = dict(file=_clip(m.get('file'), 'music file'), gain_db=_num(m.get('gain_db'), -40, 6, 'music volume', -10),
                 start=_num(m.get('start'), 0, 600, 'music start'), fade_in=_num(m.get('fade_in'), 0, 10, 'fade in', 0.6),
                 fade_out=_num(m.get('fade_out'), 0, 10, 'fade out', 1.8), duck=bool(m.get('duck', True)))
    res = dict(video=video, output=output, lines=out, music=music, loudness=_num(c.get('loudness'), -30, -8, 'loudness', -16),
               model=c.get('model') if c.get('model') in MODELS else 'eleven_v3')
    if c.get('source_take'): res['source_take'] = _s(c.get('source_take'), 200, 'source take')
    return res


_DUR: dict = {}


def duration(p) -> float | None:
    try:
        st = p.stat(); k = (p.key, st.st_mtime, st.st_size)
    except (FileNotFoundError, OSError): return None
    if k in _DUR: return _DUR[k]
    try:
        from media_info import duration as media_duration      # scripts/ (ffprobe, or ffmpeg alone in the Mac app)
        d = round(media_duration(p.local()), 3)
    except Exception: d = None
    if len(_DUR) > 5000: _DUR.clear()
    _DUR[k] = d
    return d


def file_info(p):
    if not p.is_file(): return None
    st = p.stat(); return dict(path=p.key, size=st.st_size, mtime=st.st_mtime)


@router.get('/api/p/strip/{pid}/voiceover')
def get_voiceover(pid: str):
    d = vo_dir(pid); f = d / 'voiceover.json'
    cfg = read_json(f, None) if f.is_file() else None
    cfg = cfg or default_cfg(pid)
    clips = []
    if d.is_dir():
        for x in sorted(d.iterdir(), key=lambda x: x.name.lower()):
            if x.is_file() and x.suffix.lower() in AUDIO_EXT and not x.name.startswith('.'):
                st = x.stat(); clips.append(dict(name=x.name, size=st.st_size, mtime=st.st_mtime, duration=duration(x)))
    video = safe_join(ROOT, cfg.get('video') or f'upload/{pid}_strip_reel.mp4')
    out = safe_join(ROOT, cfg.get('output') or f'upload/{pid}_strip_reel_voiceover.mp4')
    vi = file_info(video)
    if vi: vi['duration'] = duration(video)
    return dict(exists=f.is_file(), config=cfg, clips=clips, video=vi, video_path=video.key, output=file_info(out), output_path=out.key,
                readme=read_text(d / 'README.md'), eleven=bool(api_key()), suggestions=script_lines(pid))


@router.put('/api/p/strip/{pid}/voiceover')
def put_voiceover(pid: str, config: dict = Body(..., embed=True)):
    cfg = check_cfg(pid, config)
    write_json(vo_dir(pid) / 'voiceover.json', cfg)
    invalidate()
    return dict(ok=True, config=cfg)


@router.post('/api/p/strip/{pid}/voiceover/clip')
async def upload_clip(pid: str, file: UploadFile = File(...)):
    d = vo_dir(pid); data = await file.read()
    if len(data) > MAX_AUDIO: raise HTTPException(413, 'That audio file is too large (25 MB max).')
    name = check_upload(file.filename or 'clip.mp3', data, AUDIO_EXT)
    dst = _unique(d / name)
    write_atomic(dst, data, history=False); invalidate()
    return dict(name=dst.name, duration=duration(dst))


def _unique(p):
    k = 2; stem, ext = p.stem, p.suffix
    while p.exists(): p = p.with_name(f'{stem}_{k}{ext}'); k += 1
    return p


@router.post('/api/p/strip/{pid}/voiceover/generate')
@min_role('editor')
def generate(pid: str, text: str = Body(...), voice_id: str = Body(...), character: str = Body(''), model: str = Body('eleven_v3'),
             stability: float | None = Body(None)):
    """One line with ElevenLabs text-to-speech -> voiceover/<character>_<time>.mp3 (a new take; nothing is overwritten)."""
    d = vo_dir(pid)
    text = (text or '').strip()
    if not text or len(text) > 1000: raise HTTPException(400, 'Write the line first (max 1000 characters).')
    if not VOICE_ID.match(voice_id or ''): raise HTTPException(400, 'Choose a voice for this character first (Voice cast).')
    if model not in MODELS: raise HTTPException(400, 'unknown model')
    ratelimit.hit(ratelimit.user_key('tts'), 6, 0.2, 'voice generations')
    body = dict(text=text, model_id=model)
    if stability is not None:
        s = float(stability)
        if model == 'eleven_v3': s = min((0.0, 0.5, 1.0), key=lambda x: abs(x - s))     # v3: Creative / Natural / Robust
        body['voice_settings'] = dict(stability=max(0.0, min(1.0, s)), similarity_boost=0.75)
    audio = el('POST', f'/v1/text-to-speech/{voice_id}', body=body, query=dict(output_format='mp3_44100_128'), audio=True, timeout=120)
    if len(audio) < 200: raise HTTPException(502, 'ElevenLabs sent no audio.')
    slug = re.sub(r'[^a-z0-9]+', '_', (character or 'line').lower()).strip('_')[:24] or 'line'
    dst = _unique(d / f'{slug}_{time.strftime("%m%d_%H%M%S")}.mp3')
    write_atomic(dst, audio, history=False); invalidate()
    return dict(name=dst.name, duration=duration(dst), characters=len(text))


@router.post('/api/p/strip/{pid}/voiceover/mix')
@min_role('editor')
def mix(pid: str, config: dict | None = Body(None, embed=True)):
    d = piece_dir('strip', pid); vd = d / 'voiceover'
    if config is not None: write_json(vd / 'voiceover.json', check_cfg(pid, config))
    cfg = read_json(vd / 'voiceover.json', None)
    if not cfg: raise HTTPException(409, 'Add a line or music first.')
    cfg = check_cfg(pid, cfg)
    if not safe_join(ROOT, cfg['video']).is_file(): raise HTTPException(409, 'The silent strip reel is missing — build it in the Reel tab first.')
    if not any(ln.get('clip') for ln in cfg['lines']) and not cfg['music']['file']: raise HTTPException(409, 'Give at least one line a voice clip (or choose music) first.')
    for ln in cfg['lines']:
        if ln.get('clip') and not (vd / ln['clip']).is_file(): raise HTTPException(409, f'The clip {ln["clip"]} of line {ln["id"]} is missing.')
    cmd = [script_python(), SCRIPTS / 'voiceover_mix.py', d.lpath]
    sync = dict(pull=[f'{vd.key}/**', cfg['video']], push=[f'{vd.key}/final_mix.wav', cfg['output']], scope=d.key)
    job = jobs.start_steps('voiceover', f'Mix the voiceover ({pid})', [dict(cmd=cmd, label='Mixing voices and music')], ref=f'strip/{pid}',
                           on_done=lambda j: (invalidate(), file_info(safe_join(ROOT, cfg['output'])))[1], sync=sync)
    return jobs.public(job)


# ---------------- "fill from the script" ----------------
SAY = re.compile(r'(?:^|(?<=[.!?)\]"”])\s+|;\s*)([A-Z][A-Za-z\'\- ]{0,30}?)(?:\s*\([^)]*\))?\s*:\s*[“"]([^”"]{1,300})[”"]')


def script_lines(pid):
    """Caption / dialogue lines from the synopsis panels, placed on the panel's time in the storyboard."""
    d = piece_dir('strip', pid)
    syn = read_text(d / 'synopsis.md')
    sb = read_json(d / 'strip_reel' / 'storyboard.json', None) or {}
    starts = {}
    for s in sb.get('shots', []) or []:
        m = re.fullmatch(r'p(\d+)', str(s.get('id', '')))
        if m and m.group(1) not in starts: starts[m.group(1)] = float(s.get('start', 0))
    out = []
    for m in re.finditer(r'^\s*(?:Panel\s*)?(\d+)[.:]\s+(.+)$', syn, re.M):
        n, body = m.group(1), m.group(2)
        t = starts.get(n, (int(n) - 1) * 3.6) + 0.4
        cap = re.search(r'(?:Caption|\[caption)[^"“]*[“"]([^”"]{1,200})[”"]', body, re.I)
        if cap: out.append(dict(panel=int(n), character='Narrator', text=cap.group(1), at=round(t, 2))); t += 1.8
        for s in SAY.finditer(body):
            who = s.group(1).strip()
            if who.lower() in ('caption', 'text', 'sign', 'note', 'punchline'): continue
            out.append(dict(panel=int(n), character=who, text=s.group(2), at=round(t, 2))); t += 1.6
    return out[:40]
