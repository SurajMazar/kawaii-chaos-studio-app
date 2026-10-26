"""Lyric edits (music_videos/NN_name/lyric_edit*.json): edit, preview stills, render jobs, new edits, fonts.
Rendering uses scripts/lyric_edit.py (load + write_video), so the preview is pixel-identical to the final video."""
import hashlib, io, json, re, threading, time
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from .deps import authorize
from fastapi.responses import Response

from security import ratelimit
from security.context import min_role
from security.validation import check_lyric_edit, check_upload, safe_rel
from storage import get_ws

from . import jobs
from .core import (AUDIO_EXT, CODE_FONTS, FONT_EXT, FONTS, IMG_EXT, MV, font_file, get_settings, natkey, piece_dir, read_json,
                   safe_join, write_atomic, write_json)
from .library import first_line_title, invalidate

import lyric_edit as le  # noqa: E402  (scripts/ is on sys.path via core)

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)


def mv_dir(pid): return piece_dir('mv', pid)


def mv_sync(d, extra_push=()):
    """Files the renderer needs (remote backends pull them into the work cache): the project minus drafts/renders."""
    return dict(pull=[f'{d.key}/**', 'fonts/*'], push=list(extra_push), scope=d.key,
                exclude=[f'{d.key}/raw/**', f'{d.key}/build/**', f'{d.key}/build100/**', f'{d.key}/*.mp4', f'{d.key}/**/*.mp4'])


def localize(edit: dict) -> dict:
    """Font paths 'fonts/X.ttf' -> the local file (uploaded font from storage, else the default shipped font)."""
    e = json.loads(json.dumps(edit))
    fonts = e.get('fonts')
    if isinstance(fonts, dict):
        for k, v in list(fonts.items()):
            if isinstance(v, str) and v.startswith('fonts/'):
                try: fonts[k] = str(font_file(v))
                except FileNotFoundError: fonts.pop(k)
    return e


def edit_file(d: Path, name: str) -> Path:
    if not re.fullmatch(r'lyric_edit[A-Za-z0-9_\-]*\.json', name or ''): raise HTTPException(400, 'Edit files are named lyric_edit….json (letters, numbers, _ and - only)')
    return d / name


@router.get('/api/lyric')
def lyric_projects(all: bool = False):
    out = []
    for d in sorted(MV.iterdir(), key=natkey):
        if not d.is_dir() or not re.match(r'^\d+_', d.name): continue
        files = sorted(f.name for f in d.glob('lyric_edit*.json'))
        if not files and not all: continue
        out.append(dict(id=d.name, title=first_line_title(d / 'synopsis.md', d.name), files=files))
    return out


@router.get('/api/lyric/{pid}/edit')
def get_edit(pid: str, file: str = 'lyric_edit.json'):
    p = edit_file(mv_dir(pid), file)
    if not p.exists(): raise HTTPException(404, 'no such edit file')
    return read_json(p)


@router.put('/api/lyric/{pid}/edit')
def put_edit(pid: str, file: str = 'lyric_edit.json', edit: dict = Body(...)):
    d = mv_dir(pid); p = edit_file(d, file)
    if not isinstance(edit.get('lines'), list) or not edit['lines']: raise HTTPException(400, 'edit needs at least one line')
    check_lyric_edit(edit)
    write_json(p, edit)                                   # previous version -> .studio_history/
    return dict(ok=True, saved=time.time())


@router.post('/api/lyric/{pid}/copy')
def copy_edit(pid: str, src: str = Body(...), dst: str = Body(...)):
    d = mv_dir(pid); a, b = edit_file(d, src), edit_file(d, dst)
    if b.exists(): raise HTTPException(409, f'{dst} already exists')
    j = read_json(a); j['output'] = b.stem + '.mp4'
    write_json(b, j, history=False); invalidate(); return dict(ok=True)


@router.post('/api/lyric/{pid}/new')
def new_edit(pid: str, file: str = Body('lyric_edit.json'), mode: str = Body('frames'), src_pid: str = Body(''), src_file: str = Body(''),
             start: float = Body(0.0), seconds_per_line: float = Body(3.0), audio: str = Body(''), signature: str | None = Body(None),
             lines_text: str = Body('')):
    if len(lines_text) > 20000: raise HTTPException(400, 'Too many lyrics lines.')
    """mode: blank (one line) | frames (one line per picture in edit_frames/ or frame*.png) | copy (copy another edit,
    pictures are kept only if they exist here) | lyrics (one line per row of lines_text)."""
    d = mv_dir(pid); p = edit_file(d, file)
    if p.exists(): raise HTTPException(409, f'{file} already exists in {pid}')
    sig = get_settings().get('signature') if signature is None else signature
    if audio: safe_rel(audio, 'song')
    start = round(max(0.0, float(start)), 2); spl = max(0.5, float(seconds_per_line))
    pics = [f'edit_frames/{f.name}' for f in sorted((d / 'edit_frames').glob('*'), key=natkey) if f.suffix.lower() in IMG_EXT] if (d / 'edit_frames').is_dir() else []
    if not pics: pics = [f.name for f in sorted(d.glob('frame*.png'), key=natkey)]
    base = dict(output=p.stem + '.mp4', size=[1080, 1920], fps=30, start=start, end=None, audio=audio or None, fit='cover', signature=sig or '')
    if mode == 'copy':
        sd = mv_dir(src_pid or pid); sp = edit_file(sd, src_file or 'lyric_edit.json')
        if not sp.exists(): raise HTTPException(404, 'the edit to copy was not found')
        j = read_json(sp); j['output'] = p.stem + '.mp4'
        if sd != d:
            for l in j.get('lines', []):
                for s in l.get('shots', []) or []:
                    if s.get('image') and not (d / s['image']).exists(): s.pop('image')
                if l.get('image') and not (d / l['image']).exists(): l.pop('image')
            j['audio'] = audio or None
        shift = start - j.get('start', 0) if start else 0
        if shift:
            j['start'] = start
            if j.get('end'): j['end'] = round(j['end'] + shift, 2)
            for l in j['lines']:
                l['start'] = round(l['start'] + shift, 2); l['end'] = round(l['end'] + shift, 2); l.pop('word_times', None)
                for s in l.get('shots', []) or []:
                    if 'at' in s: s['at'] = round(s['at'] + shift, 2)
        edit = j
    else:
        texts = [t.strip() for t in lines_text.splitlines() if t.strip()] if mode == 'lyrics' else []
        n = len(texts) if texts else (max(1, len(pics)) if mode == 'frames' else 1)
        lines = []
        for i in range(n):
            t0 = round(start + i * spl, 2)
            L = dict(start=t0, end=round(t0 + spl, 2), text=texts[i] if texts else ('*FIRST* / line' if i == 0 else f'*LINE* / {i + 1}'), style='block', y=0.15)
            if pics: L['shots'] = [dict(image=pics[i % len(pics)])]
            lines.append(L)
        edit = dict(base, lines=lines)
    write_json(p, edit, history=False); invalidate()
    return dict(ok=True, file=file)


@router.get('/api/lyric/{pid}/media')
def media(pid: str):
    d = mv_dir(pid); imgs = []
    for sub in ('edit_frames', '.'):
        for f in sorted((d / sub).glob('*'), key=natkey) if (d / sub).is_dir() else []:
            if f.suffix.lower() in IMG_EXT and not f.name.startswith(('still_', 'lyric_edit', 'studio_board')):
                imgs.append(dict(path=str(f.relative_to(d)), mtime=f.stat().st_mtime))
    audio = [dict(path=str(f.relative_to(d))) for f in sorted(d.rglob('*')) if f.suffix.lower() in AUDIO_EXT and '.studio' not in str(f)]
    videos = [dict(path=f.name, mtime=f.stat().st_mtime, size=f.stat().st_size) for f in sorted(d.glob('*.mp4')) if '.rendering' not in f.name]
    return dict(images=imgs, audio=audio, videos=videos)


# ---------------- fonts ----------------
@router.get('/api/fonts')
def fonts():
    out = {f.name: dict(name=f.name, path='fonts/' + f.name, size=f.stat().st_size) for f in FONTS.iterdir() if f.suffix.lower() in FONT_EXT}
    if CODE_FONTS.is_dir():                               # the default fonts shipped with the app
        for f in CODE_FONTS.iterdir():
            if f.suffix.lower() in FONT_EXT and f.name not in out: out[f.name] = dict(name=f.name, path='fonts/' + f.name, size=f.stat().st_size)
    return [out[k] for k in sorted(out, key=natkey)]


@router.post('/api/fonts')
async def upload_font(file: UploadFile = File(...)):
    data = await file.read()
    name = check_upload(file.filename or '', data, FONT_EXT)
    from PIL import ImageFont
    try: ImageFont.truetype(io.BytesIO(data), 40)
    except Exception: raise HTTPException(400, 'This file is not a font the renderer can read')
    dst = FONTS / name
    if dst.exists(): raise HTTPException(409, f'{name} already exists in fonts/')
    write_atomic(dst, data, history=False)
    return dict(ok=True, path='fonts/' + name)


@router.get('/api/fonts/sample')
def font_sample(path: str, text: str = 'Kawaii Chaos', size: int = 64):
    from PIL import Image, ImageDraw, ImageFont
    if not re.fullmatch(r'fonts/[A-Za-z0-9._\-]{1,120}', path or ''): raise HTTPException(404)
    try: fp = font_file(path)
    except FileNotFoundError: raise HTTPException(404)
    text = text[:60]; size = max(8, min(int(size), 160))
    f = ImageFont.truetype(str(fp), size); d0 = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, t, r, b = d0.textbbox((0, 0), text, font=f)
    im = Image.new('RGBA', (r - l + 20, b - t + 20), (0, 0, 0, 0)); ImageDraw.Draw(im).text((10 - l, 10 - t), text, font=f, fill=(255, 255, 255, 255))
    buf = io.BytesIO(); im.save(buf, 'PNG'); return Response(buf.getvalue(), media_type='image/png', headers={'Cache-Control': 'max-age=3600'})


# ---------------- preview stills ----------------
_eds: 'OrderedDict[str, object]' = OrderedDict(); _ed_lock = threading.Lock()


def edit_key(d, edit: dict, scale: float) -> str:
    """Content key of a rendered edit: the edit JSON + every picture's mtime/size (redrawn frames show up)."""
    stamp = ''.join(f'{f.name}{f.stat().st_mtime_ns}{f.stat().st_size}' for f in sorted(d.rglob('*'), key=natkey)
                    if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') and '.studio' not in str(f) and 'raw' not in f.parts)
    return hashlib.sha1((str(d) + json.dumps(edit, sort_keys=True) + str(scale) + stamp).encode()).hexdigest()  # nosec B324 - cache key


def get_renderer(d, edit: dict, scale: float):
    check_lyric_edit(edit)
    # include every picture's mtime/size: a redrawn frame with the same file name must show up (owner 2026-10-24)
    key = edit_key(d, edit, scale)
    with _ed_lock:
        if key in _eds: _eds.move_to_end(key); return _eds[key]
    s = mv_sync(d); get_ws().pull(s['pull'], s['exclude'])
    ed = le.load(localize(edit), str(d.lpath), scale)
    with _ed_lock:
        _eds[key] = ed
        while len(_eds) > 4: _eds.popitem(last=False)
    return ed


@router.post('/api/lyric/{pid}/still')
@min_role('viewer')
def still(pid: str, t: float = Body(...), edit: dict = Body(...), scale: float = Body(0.5)):
    ratelimit.hit(ratelimit.user_key('still'), 60, 20, 'preview frames')
    d = mv_dir(pid)
    try: ed = get_renderer(d, edit, max(0.2, min(scale, 1.0)))
    except Exception as e: raise HTTPException(400, f'cannot build edit: {e}')
    t = max(0.0, min(t, ed.end - ed.start - 1e-3))
    im = ed.render(ed.start + t, int(t * ed.fps)).convert('RGB'); buf = io.BytesIO(); im.save(buf, 'JPEG', quality=86)
    return Response(buf.getvalue(), media_type='image/jpeg')


# ---------------- playback video (smooth Play in the editor) ----------------
# Play used to stream single JPEG frames (~12 req/s): stuttery and it tripped the preview rate limit (owner 2026-10-25:
# "the player auto pauses"). Now Play shows a small real video of the edit, rendered once per edit version in the
# background (cached by the same key as the still renderer: edit JSON + picture stamps) and kept in sync with the song.
_PB_SCALE, _PB_FPS = 0.4, 24
_pb_lock = threading.Lock()
_pb: dict = {}            # key -> {'state': 'rendering'|'ready'|'error', 'progress': float, 'error': str}


def _pb_dir() -> Path:
    from config import CONFIG
    p = CONFIG.cache_dir / 'playback'; p.mkdir(parents=True, exist_ok=True); return p


def _pb_prune(keep: int = 24):
    files = sorted(_pb_dir().glob('*.mp4'), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        try: f.unlink()
        except OSError: pass


@router.post('/api/lyric/{pid}/playback')
@min_role('viewer')
def playback(pid: str, edit: dict = Body(..., embed=True)):
    """Ensure a playback video exists for this exact edit; returns its state and (when ready) its URL."""
    ratelimit.hit(ratelimit.user_key('playback'), 20, 2, 'playback requests')
    d = mv_dir(pid)
    check_lyric_edit(edit)
    try: get_renderer(d, edit, _PB_SCALE)              # validates the edit + pulls pictures (remote storage)
    except Exception as e: raise HTTPException(400, f'cannot build edit: {e}')
    key = edit_key(d, edit, _PB_SCALE)[:24]
    out = _pb_dir() / f'{key}.mp4'
    url = f'/api/lyric/{pid}/playback/{key}.mp4'
    if out.is_file(): return dict(state='ready', key=key, url=url, progress=1.0)
    with _pb_lock:
        st = _pb.get(key)
        if st and st['state'] == 'rendering': return dict(state='rendering', key=key, progress=st['progress'])
        busy = sum(1 for v in _pb.values() if v['state'] == 'rendering')
        if busy >= 2: return dict(state='queued', key=key, progress=0.0)
        st = _pb[key] = dict(state='rendering', progress=0.0, error='')
    edit_l = localize(edit)

    def go():
        try:
            e2 = le.load(edit_l, str(d.lpath), _PB_SCALE, _PB_FPS)
            def prog(done, total): st['progress'] = round(done / max(1, total), 3)
            le.write_video(e2, str(out), prog, None, preset='veryfast', crf=26)
            st['state'] = 'ready'; _pb_prune()
        except Exception as e:  # noqa: BLE001 - report to the client
            st.update(state='error', error=str(e)[:300])
        finally:
            with _pb_lock:
                if len(_pb) > 200: [_pb.pop(k) for k in list(_pb)[:100] if _pb[k]['state'] != 'rendering']
    threading.Thread(target=go, daemon=True, name=f'playback-{key[:8]}').start()
    return dict(state='rendering', key=key, progress=0.0)


@router.get('/api/lyric/{pid}/playback/{key}.mp4')
@min_role('viewer')
def playback_file(pid: str, key: str):
    if not re.fullmatch(r'[0-9a-f]{24}', key): raise HTTPException(400, 'bad key')
    mv_dir(pid)                                            # project must exist and be readable
    f = _pb_dir() / f'{key}.mp4'
    if not f.is_file(): raise HTTPException(404, 'not rendered yet')
    from fastapi.responses import FileResponse
    return FileResponse(f, media_type='video/mp4', headers={'Cache-Control': 'private, max-age=86400'})


@router.post('/api/lyric/{pid}/render')
def render(pid: str, edit: dict = Body(...), file: str = Body('lyric_edit.json'), quality: str = Body('preview'), bake_audio: bool = Body(False)):
    d = mv_dir(pid)
    check_lyric_edit(edit)
    if quality not in ('preview', 'final'): raise HTTPException(400, 'quality is preview or final')
    stem = edit_file(d, file).stem
    out = d / (f'{stem}_preview.mp4' if quality == 'preview' else Path(edit.get('output') or f'{stem}.mp4').name)
    audio = None
    if bake_audio and edit.get('audio'):
        a = safe_join(d, safe_rel(edit['audio'], 'song'))
        if a.is_file(): audio = a
    scale, fps = (0.5, 15) if quality == 'preview' else (1.0, None)
    sync = mv_sync(d, extra_push=[out.key])
    if audio is not None: sync['pull'].append(audio.key)
    edit_l = localize(edit)

    def go(job):
        ed = le.load(edit_l, str(d.lpath), scale, fps)
        job['total'] = int(round((ed.end - ed.start) * ed.fps))
        def prog(done, total): job['done'] = done; job['progress'] = round(done / max(1, total), 4)
        le.write_video(ed, str(out.lpath), prog, str(audio.lpath) if audio is not None else None, cancel=lambda: job['cancel'])
        invalidate()
        return dict(output=out.name)
    job = jobs.start_fn('lyric_render', f"{'Quick preview' if quality == 'preview' else 'Final video'} — {pid}/{file}", go,
                        ref=f'mv/{pid}', meta=dict(pid=pid, quality=quality, edit_hash=hashlib.sha1(json.dumps(edit, sort_keys=True).encode()).hexdigest()),  # nosec B324
                        sync=sync)
    return jobs.public(job)
