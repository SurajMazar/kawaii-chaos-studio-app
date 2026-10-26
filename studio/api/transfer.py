"""Move projects between Studios: export one strip / music video as a .zip, import a .zip as a new project.

The zip holds kcs_project.json (what it is + its caption and posting history), project/… (the project folder, without
the .studio_history backups) and upload/… (its finished files). Importing never overwrites anything: the project gets
the next free number (and _2, _3… if the name is taken), the files are checked one by one (type by content, sizes,
no paths outside the project, no links, zip-bomb limits) and the render documents are validated like any edit.
"""
import json, os, re, stat, tempfile, time, zipfile
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from .deps import authorize

from config import CONFIG
from security.context import min_role
from security.validation import check_lyric_edit, check_storyboard, check_upload

from .core import AUDIO_EXT, IMG_EXT, KINDS, MV, NAME_RE, PROJ, ROOT, UPLOAD, VIDEO_EXT, piece_dir, read_json, write_atomic, write_json
from .library import invalidate, load_captions, load_log
from .tools import _new_lock

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
FORMAT = 'kawaii-chaos-studio/project'
TEXT_EXT = {'.md', '.txt', '.json', '.lrc', '.srt'}
ART_EXT = {'.psd', '.kra', '.clip', '.mdp', '.procreate', '.xcf', '.ora', '.tif', '.tiff', '.gif', '.afphoto', '.csp'}  # drawing files: kept, never opened
ALLOWED = IMG_EXT | AUDIO_EXT | VIDEO_EXT | TEXT_EXT | ART_EXT
MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_RATIO = 5000, 1 << 30, 4 << 30, 200
SKIP = re.compile(r'(^|/)(\.studio_history|__pycache__)(/|$)|(^|/)\.DS_Store$|\.rendering|\.tmp$')
WIDTH = {'strip': 3, 'mv': 2}


def _uploads(kind, pid):
    base = UPLOAD if kind == 'strip' else UPLOAD / 'music_videos'
    if not base.is_dir(): return []
    return [f for f in base.iterdir() if f.is_file() and f.name.startswith(pid + '_')]


@router.get('/api/p/{kind}/{pid}/export.zip')
def export_zip(kind: str, pid: str, videos: bool = True):
    """One project as a .zip (viewers may download it, like any file of the project)."""
    d = piece_dir(kind, pid)
    caps = load_captions(); log = load_log()
    posts = [p for p in log.get('posts' if kind == 'strip' else 'music_video_posts', []) if p.get('project') == pid]
    cap = caps.get(pid)
    files = [f for f in d.rglob('*') if f.is_file() and not SKIP.search(str(f.relative_to(d)))
             and (videos or f.suffix.lower() not in VIDEO_EXT)]
    ups = [f for f in _uploads(kind, pid) if videos or f.suffix.lower() not in VIDEO_EXT]
    manifest = dict(format=FORMAT, version=1, kind=kind, id=pid, name=re.sub(r'^\d+_', '', pid), exported=time.strftime('%Y-%m-%dT%H:%M:%S'),
                    caption=cap, posts=posts, files=len(files), uploads=[f.name for f in ups], videos=videos)
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG.cache_dir, prefix='export_', suffix='.zip'); os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr('kcs_project.json', json.dumps(manifest, indent=1, ensure_ascii=False))
            for f in files:
                stored = f.suffix.lower() in VIDEO_EXT | AUDIO_EXT | IMG_EXT       # already compressed
                z.write(f.local(), f'project/{f.relative_to(d)}', compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
            for f in ups: z.write(f.local(), f'upload/{f.name}', compress_type=zipfile.ZIP_STORED)
    except Exception:
        os.unlink(tmp); raise
    return FileResponse(tmp, media_type='application/zip', filename=f'{pid}.zip', background=BackgroundTask(os.unlink, tmp),
                        headers={'Cache-Control': 'no-store'})


def _clean_name(rel: str) -> str:
    rel = rel.replace('\\', '/')
    p = PurePosixPath(rel)
    if rel.startswith('/') or p.is_absolute() or any(x in ('..', '.', '') for x in p.parts) or '\x00' in rel or ':' in rel:
        raise HTTPException(400, f'The zip contains a bad path: {rel[:80]!r}')
    return str(p)


def _check_file(name: str, data: bytes):
    ext = PurePosixPath(name).suffix.lower()
    if ext in ART_EXT: return
    if ext in IMG_EXT | AUDIO_EXT:
        check_upload(PurePosixPath(name).name, data, IMG_EXT | AUDIO_EXT)
    elif ext in VIDEO_EXT:
        if not (data[4:8] == b'ftyp' or data[:4] == b'\x1aE\xdf\xa3'): raise HTTPException(400, f'{name[:80]} is not a video file.')
    else:
        try: text = data.decode('utf-8')
        except UnicodeDecodeError: raise HTTPException(400, f'{name[:80]} is not a text file.')
        if ext == '.json':
            try: doc = json.loads(text or 'null')
            except json.JSONDecodeError: raise HTTPException(400, f'{name[:80]} is not valid JSON.')
            base = PurePosixPath(name).name
            if base.startswith('lyric_edit') and isinstance(doc, dict): check_lyric_edit(doc)
            if base == 'storyboard.json' and isinstance(doc, dict): check_storyboard(doc)


def _new_id(kind: str, name: str) -> str:
    top = PROJ if kind == 'strip' else MV
    taken = {re.sub(r'^\d+_', '', p.name) for p in top.iterdir()} if top.is_dir() else set()
    base, k = name, 2
    while name in taken: name = f'{base}_{k}'; k += 1
    nums = [int(m.group(1)) for p in (top.iterdir() if top.is_dir() else []) if (m := re.match(r'(\d+)_', p.name))]
    return f'{max(nums, default=0) + 1:0{WIDTH[kind]}d}_{name}'


@router.post('/api/import')
@min_role('editor')
def import_zip(file: UploadFile = File(...), posts: bool = Query(True)):
    """A project .zip (from Export) becomes a new project; nothing existing is overwritten."""
    try: z = zipfile.ZipFile(file.file)
    except zipfile.BadZipFile: raise HTTPException(400, 'That is not a .zip file.')
    with z:
        infos = z.infolist()
        if len(infos) > MAX_FILES: raise HTTPException(400, 'The zip has too many files.')
        try: man = json.loads(z.read('kcs_project.json').decode())
        except KeyError: raise HTTPException(400, 'This zip was not exported by the Studio (kcs_project.json is missing).')
        except (json.JSONDecodeError, UnicodeDecodeError): raise HTTPException(400, 'kcs_project.json is damaged.')
        if man.get('format') != FORMAT or man.get('kind') not in KINDS: raise HTTPException(400, 'This zip is not a Studio project.')
        kind = man['kind']; old = str(man.get('id') or '')
        name = re.sub(r'[^a-z0-9_]+', '_', str(man.get('name') or re.sub(r'^\d+_', '', old)).lower()).strip('_')[:50] or 'imported'
        if not NAME_RE.match(name): name = 'imported'
        plan, total, skipped = [], 0, []
        for i in infos:
            if i.is_dir() or i.filename == 'kcs_project.json': continue
            mode = (i.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode): raise HTTPException(400, 'The zip contains a link, which is not allowed.')
            rel = _clean_name(i.filename)
            if SKIP.search(rel): continue
            if i.file_size > MAX_FILE: raise HTTPException(400, f'{rel[:80]} is too large.')
            if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > (1 << 20):
                raise HTTPException(400, 'The zip looks like a zip bomb.')
            total += i.file_size
            if total > MAX_TOTAL: raise HTTPException(400, 'The project is too large to import.')
            top, _, sub = rel.partition('/')
            if PurePosixPath(rel).suffix.lower() not in ALLOWED: skipped.append(rel); continue   # scripts, svg, unknown types
            if top == 'project' and sub: plan.append((i, 'project', sub))
            elif top == 'upload' and sub and '/' not in sub and old and sub.startswith(old + '_'): plan.append((i, 'upload', sub))
            else: raise HTTPException(400, f'Unexpected file in the zip: {rel[:80]}')
        if not any(w == 'project' for _, w, _ in plan): raise HTTPException(400, 'The zip has no project files.')
        for i, _, sub in plan: _check_file(sub, z.read(i))          # everything is checked before anything is written
        with _new_lock:
            pid = _new_id(kind, name)
            d = (PROJ if kind == 'strip' else MV) / pid
            up = UPLOAD if kind == 'strip' else UPLOAD / 'music_videos'
            for i, where, sub in plan:
                dst = d / sub if where == 'project' else up / (pid + sub[len(old):])
                write_atomic(dst, z.read(i), history=False)
    fix = d / 'voiceover' / 'voiceover.json'                         # its paths name the old project
    if fix.is_file() and old:
        cfg = read_json(fix, {}) or {}
        for k in ('video', 'output'):
            if isinstance(cfg.get(k), str): cfg[k] = cfg[k].replace(f'upload/{old}_', f'upload/{pid}_').replace(f'projects/{old}/', f'projects/{pid}/')
        write_json(fix, cfg, history=False)
    if man.get('caption') and isinstance(man['caption'], (str, dict)):
        caps = load_captions()
        if pid not in caps: caps[pid] = man['caption']; write_json(ROOT / 'captions.json', caps)
    if posts and isinstance(man.get('posts'), list) and man['posts']:
        log = load_log(); key = 'posts' if kind == 'strip' else 'music_video_posts'
        for p in man['posts'][:50]:
            if isinstance(p, dict): log.setdefault(key, []).append({**p, 'project': pid, 'note': f'imported from {old}'[:200]})
        write_json(ROOT / 'posting_log.json', log)
    invalidate()
    return dict(ok=True, kind=kind, id=pid, files=len(plan), renamed_from=old, skipped=skipped[:50])
