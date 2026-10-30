"""Per-project endpoints shared by strips (projects/NNN_x) and music videos (music_videos/NN_x):
texts (synopsis / qa / prompts), images, uploads, Downloads import, files browser, QA gate, layout, prompt parts,
reference board, character-sheet heights, style check, export."""
import io, re, shutil, time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from .deps import authorize
from fastapi.responses import FileResponse

from config import CONFIG
from security.context import min_role
from security.validation import check_upload, sanitize_filename
from storage import SPath, get_ws

from . import jobs, native
from .core import (AUDIO_EXT, IMG_EXT, REFS, ROOT, SCRIPTS, UPLOAD, VIDEO_EXT, backup, font_file, get_settings,
                   natkey, piece_dir, read_text, safe_join, script_python, sha1_file, thumb_file, today,
                   write_atomic)
from .library import couple_guess, invalidate, mv_frames, mv_item, qa_status, strip_item, load_log, load_captions

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
TEXTS = {'synopsis.md', 'qa.md', 'prompt_final.txt', 'charsheet_prompt.txt', 'LYRIC_EDIT_README.md', 'layout/layout.txt'}


def ref_of(kind, pid): return f'{kind}/{pid}'


def need_local_features():
    if not CONFIG.local_features:
        raise HTTPException(403, 'This works only when the Studio runs on your own computer (STUDIO_LOCAL_FEATURES).')


def presign_ok() -> bool:
    try: from .integrations import settings_obj; return bool(settings_obj().effective().get('presign_downloads'))
    except Exception: return False


ACTIVE_TYPES = {'.html', '.htm', '.xhtml', '.svg', '.xml', '.js', '.mjs'}


def serve(p: SPath, request: Request, download: bool):
    if not p.is_file(): raise HTTPException(404, 'no such file')
    if p.suffix.lower() in ACTIVE_TYPES: download = True        # never render active content inline on our origin
    return get_ws().response(p.key, request, download=download, presign=download and presign_ok())


# ---------------- overview ----------------
@router.get('/api/p/{kind}/{pid}')
def overview(kind: str, pid: str):
    d = piece_dir(kind, pid)
    if kind == 'strip':
        log = load_log(); by = {}
        for p in log.get('posts', []): by.setdefault(p.get('project'), []).append(p)
        it = strip_item(d, by, load_captions())
    else:
        it = mv_item(d, load_log().get('music_video_posts', []))
    it['texts'] = {t: (d / t).exists() for t in TEXTS}
    return it


# ---------------- texts ----------------
def text_path(d: Path, name: str) -> Path:
    if name not in TEXTS: raise HTTPException(400, f'{name} cannot be edited here')
    return d / name


@router.get('/api/p/{kind}/{pid}/text')
def get_text(kind: str, pid: str, name: str):
    p = text_path(piece_dir(kind, pid), name)
    return dict(name=name, exists=p.exists(), text=read_text(p), mtime=p.stat().st_mtime if p.exists() else None)


@router.put('/api/p/{kind}/{pid}/text')
def put_text(kind: str, pid: str, name: str, text: str = Body(..., embed=True)):
    if name == 'layout/layout.txt': raise HTTPException(400, 'layout.txt is made by the layout generator')
    p = text_path(piece_dir(kind, pid), name)
    write_atomic(p, text if text.endswith('\n') or not text else text + '\n'); invalidate()
    return dict(ok=True, mtime=p.stat().st_mtime)


# ---------------- files / images ----------------
def kind_of(f: Path):
    e = f.suffix.lower()
    return 'image' if e in IMG_EXT else 'audio' if e in AUDIO_EXT else 'video' if e in VIDEO_EXT else \
        'text' if e in {'.md', '.txt', '.json', '.sh', '.lrc', '.py'} else 'other'


def entry(d: Path, f: Path):
    st = f.stat()
    return dict(name=f.name, path=str(f.relative_to(d)), is_dir=f.is_dir(), size=st.st_size, mtime=st.st_mtime, kind='dir' if f.is_dir() else kind_of(f))


@router.get('/api/p/{kind}/{pid}/files')
def files(kind: str, pid: str, dir: str = '', hidden: bool = False):
    d = piece_dir(kind, pid); base = safe_join(d, dir)
    if not base.is_dir(): raise HTTPException(404, 'no such folder')
    out = [entry(d, f) for f in sorted(base.iterdir(), key=lambda f: (not f.is_dir(), natkey(f.name)))
           if hidden or not f.name.startswith('.') or f.name == '.studio_history']
    return dict(dir=str(base.relative_to(d)) if base != d else '', entries=out)


@router.get('/api/p/{kind}/{pid}/file/{rel:path}')
def get_file(kind: str, pid: str, rel: str, request: Request, download: bool = False):
    return serve(safe_join(piece_dir(kind, pid), rel), request, download)


@router.post('/api/p/{kind}/{pid}/share')
@min_role('viewer')
def share_file(kind: str, pid: str, rel: str = Body(...), rect: list[float] = Body([0, 0, 0, 0])):
    """Mac app: the macOS share menu for one file of the piece, opened next to the button (rect = x, y, w, h)."""
    if native.share is None: raise HTTPException(404, 'Sharing to other apps works in the Mac app.')
    p = safe_join(piece_dir(kind, pid), rel)
    if not p.is_file(): raise HTTPException(404, 'no such file')
    x, y, w, h = (list(rect) + [0, 0, 0, 0])[:4]
    native.share(p.local(), (x, y, w, h))
    return dict(ok=True)


@router.get('/api/p/{kind}/{pid}/thumb/{rel:path}')
def get_thumb(kind: str, pid: str, rel: str, w: int = 240):
    p = safe_join(piece_dir(kind, pid), rel)
    if not p.is_file(): raise HTTPException(404, 'no such file')
    return FileResponse(thumb_file(p, w), headers={'Cache-Control': 'no-cache'})


ROOT_READ = ('upload', 'references', 'fonts', 'mascot')


@router.get('/api/root/{rel:path}')
def root_file(rel: str, request: Request, download: bool = False):
    p = safe_join(ROOT, rel)
    if rel.split('/')[0] not in ROOT_READ or not p.is_file(): raise HTTPException(404, 'no such file')
    return serve(p, request, download)


@router.get('/api/rthumb/{rel:path}')
def root_thumb(rel: str, w: int = 240):
    p = safe_join(ROOT, rel)
    if rel.split('/')[0] not in ROOT_READ or not p.is_file(): raise HTTPException(404, 'no such file')
    return FileResponse(thumb_file(p, w), headers={'Cache-Control': 'no-cache'})


@router.get('/api/refs')
def refs():
    return [dict(name=f.name, path='references/' + f.name) for f in sorted(REFS.iterdir(), key=natkey) if f.suffix.lower() in IMG_EXT and f.is_file()]


def img_list(d: Path, sub: str):
    b = d / sub if sub else d
    if not b.is_dir(): return []
    return [dict(path=str(f.relative_to(d)), name=f.name, mtime=f.stat().st_mtime, size=f.stat().st_size, sha=None)
            for f in sorted(b.iterdir(), key=lambda f: natkey(f.name)) if f.is_file() and f.suffix.lower() in IMG_EXT
            and not f.name.startswith('.') and '_stylecheck' not in f.name and not f.name.endswith('_orange.jpg')]


@router.get('/api/p/{kind}/{pid}/images')
def images(kind: str, pid: str):
    d = piece_dir(kind, pid)
    groups = [dict(key='main', title='Main pictures', items=img_list(d, ''))]
    if kind == 'mv': groups.append(dict(key='edit_frames', title='Lyric-edit pictures (edit_frames/)', items=img_list(d, 'edit_frames')))
    groups += [dict(key='raw', title='Drafts (raw/)', items=img_list(d, 'raw')),
               dict(key='rejected', title='Rejected (raw/rejected/)', items=img_list(d, 'raw/rejected')),
               dict(key='layout', title='Layout', items=img_list(d, 'layout'))]
    checks = [dict(path=str(f.relative_to(d)), name=f.name, mtime=f.stat().st_mtime) for f in sorted(d.rglob('*_stylecheck*.jpg')) if '.studio_history' not in str(f)]
    return dict(groups=groups, stylechecks=checks)


def unique(dst: Path) -> Path:
    k = 2; stem, ext = dst.stem, dst.suffix
    while dst.exists(): dst = dst.with_name(f'{stem}_{k}{ext}'); k += 1
    return dst


UPLOAD_DIRS = {'raw', 'raw/rejected', 'edit_frames', 'audio', '.', 'refs'}


@router.post('/api/p/{kind}/{pid}/upload')
async def upload(kind: str, pid: str, file: UploadFile = File(...), dest: str = Form('raw'), role: str = Form('')):
    d = piece_dir(kind, pid); ext = Path(file.filename or '').suffix.lower()
    if dest not in UPLOAD_DIRS: raise HTTPException(400, 'bad destination')
    if ext not in IMG_EXT | AUDIO_EXT: raise HTTPException(400, 'Only pictures (png, jpg, webp) or songs (mp3, m4a, wav…) can be added here.')
    if ext in AUDIO_EXT: dest = 'audio'
    data = await file.read()
    name = check_upload(file.filename or f'upload{ext}', data, IMG_EXT | AUDIO_EXT)
    sub = d if dest == '.' else d / dest
    dst = unique(sub / name)
    write_atomic(dst, data, history=False)
    rel = str(dst.relative_to(d))
    if role: set_role(kind, pid, rel, role)
    invalidate()
    return dict(path=rel)


ROLES = {'strip': 'strip.png', 'charsheet': 'charsheet.png'}


@router.post('/api/p/{kind}/{pid}/set-role')
def set_role(kind: str, pid: str, src: str = Body(...), role: str = Body(...)):
    d = piece_dir(kind, pid); s = safe_join(d, src)
    if role not in ROLES or (role == 'strip' and kind != 'strip'): raise HTTPException(400, 'bad role')
    if not s.is_file() or s.suffix.lower() not in IMG_EXT: raise HTTPException(404, 'no such picture')
    dst = d / ROLES[role]
    if s.resolve() == dst.resolve(): return dict(ok=True, path=dst.name)
    from PIL import Image
    if s.suffix.lower() == '.png':
        data = s.read_bytes()
    else:
        buf = io.BytesIO()
        with Image.open(s.local()) as im: im.convert('RGB').save(buf, 'PNG')
        data = buf.getvalue()
    write_atomic(dst, data)                      # the old strip/charsheet is kept in .studio_history/
    invalidate()
    return dict(ok=True, path=dst.name, sha=sha1_file(dst))


@router.post('/api/p/{kind}/{pid}/reject')
def reject(kind: str, pid: str, src: str = Body(...), reason: str = Body('')):
    d = piece_dir(kind, pid); s = safe_join(d, src)
    if not s.is_file(): raise HTTPException(404, 'no such picture')
    if s.parent.resolve() not in {(d / 'raw').resolve(), (d / 'edit_frames').resolve()}:
        raise HTTPException(400, 'Only drafts in raw/ (or edit_frames/) can be moved to Rejected.')
    tag = re.sub(r'[^A-Za-z0-9]+', '_', reason).strip('_')[:40]
    rej = d / 'raw' / 'rejected'; rej.mkdir(parents=True, exist_ok=True)
    dst = unique(rej / (f'{s.stem}_{tag}{s.suffix}' if tag else s.name))
    get_ws().move(s.key, dst.key); invalidate()
    return dict(ok=True, path=str(dst.relative_to(d)))


@router.post('/api/p/{kind}/{pid}/restore')
def restore(kind: str, pid: str, src: str = Body(..., embed=True)):
    d = piece_dir(kind, pid); s = safe_join(d, src)
    if not s.is_file() or s.parent.resolve() != (d / 'raw' / 'rejected').resolve(): raise HTTPException(400, 'only rejected pictures can be restored')
    dst = unique(d / 'raw' / s.name); get_ws().move(s.key, dst.key); invalidate()
    return dict(ok=True, path=str(dst.relative_to(d)))


# ---------------- Downloads import ----------------
def downloads_dir() -> Path:
    need_local_features()
    p = Path(get_settings()['downloads']).expanduser()
    if not p.is_dir(): raise HTTPException(404, f'Downloads folder not found: {p} (change it in Settings)')
    return p


@router.get('/api/downloads')
@min_role('editor')
def list_downloads(limit: int = 80):
    dd = downloads_dir(); out = []
    for f in dd.iterdir():
        if f.is_file() and (f.suffix.lower() in IMG_EXT or re.search(r'_bundle.*\.bin$', f.name)):
            out.append(dict(name=f.name, size=f.stat().st_size, mtime=f.stat().st_mtime, bundle=f.suffix == '.bin'))
    out.sort(key=lambda e: -e['mtime'])
    return dict(dir=str(dd), items=out[:limit])


@router.get('/api/downloads/thumb')
@min_role('editor')
def downloads_thumb(name: str, w: int = 240):
    dd = downloads_dir(); p = dd / Path(name).name
    if not p.is_file() or p.suffix.lower() not in IMG_EXT: raise HTTPException(404)
    return FileResponse(thumb_file(p, w), headers={'Cache-Control': 'no-cache'})


@router.post('/api/p/{kind}/{pid}/import')
def import_downloads(kind: str, pid: str, names: list[str] = Body(..., embed=True)):
    d = piece_dir(kind, pid); dd = downloads_dir(); raw = d / 'raw'; raw.mkdir(exist_ok=True); out = []
    for n in names:
        s = dd / Path(n).name
        if not s.is_file() or s.suffix.lower() not in IMG_EXT: raise HTTPException(400, f'not a picture in Downloads: {n}')
        data = s.read_bytes(); check_upload(s.name, data, IMG_EXT)
        dst = unique(raw / sanitize_filename(s.name)); write_atomic(dst, data, history=False); out.append(str(dst.relative_to(d)))
    invalidate()
    return dict(paths=out)


@router.post('/api/p/{kind}/{pid}/import-bundles')
def import_bundles(kind: str, pid: str, prefix: str = Body('', embed=True)):
    need_local_features()
    piece_dir(kind, pid)
    if prefix and not re.fullmatch(r'[A-Za-z0-9_]{1,60}', prefix): raise HTTPException(400, 'bad prefix')
    py = script_python()
    if kind == 'strip':
        cmd = [py, SCRIPTS / 'unpack_bundles.py']; title = 'Import ChatGPT bundles (all strips)'
        sync = dict(pull=['projects/*/synopsis.md'], push=['projects/*/raw/*'], scope='projects')
    else:
        cmd = [py, SCRIPTS / 'unpack_mv.py', pid] + ([prefix] if prefix else []); title = f'Import ChatGPT bundles into {pid}'
        sync = dict(pull=[f'music_videos/{pid}/*'], push=[f'music_videos/{pid}/**'], scope=f'music_videos/{pid}')
    job = jobs.start_steps('import', title, [dict(cmd=cmd, label='Unpacking bundles')], ref=ref_of(kind, pid), on_done=lambda j: invalidate(), sync=sync)
    return jobs.public(job)


# ---------------- QA ----------------
CHECK_RE = re.compile(r'^\*\*([A-Z]\d?)\.\s*(.+?)\*\*\s*(.*)$')


def qa_checklist():
    out = []; cur = None
    for line in read_text(ROOT / 'qa_rules.md').splitlines():
        m = CHECK_RE.match(line)
        if m:
            cur = dict(key=m.group(1), title=m.group(2).rstrip('.'), text=m.group(3).strip()); out.append(cur)
        elif cur and line.startswith('   ') and line.strip():
            cur['text'] += ' ' + line.strip()
        elif not line.strip() or line.startswith('##'):
            cur = None
    return out


def qa_targets(kind, d: Path):
    if kind == 'strip':
        names = ['strip.png'] + (['charsheet.png'] if (d / 'charsheet.png').exists() else [])
    else:
        names = mv_frames(d) + (['charsheet.png'] if (d / 'charsheet.png').exists() else [])
    return names


@router.get('/api/p/{kind}/{pid}/qa')
def qa(kind: str, pid: str):
    d = piece_dir(kind, pid); q = d / 'qa.md'; text = read_text(q, None) if q.exists() else None
    targets = []
    for n in qa_targets(kind, d):
        sha = sha1_file(d / n) if (d / n).exists() else None
        st = qa_status(text if text is not None else '', sha)
        if n == 'charsheet.png' and sha and text and re.search(r'SHEET PASS(?: sha1)? ' + sha, text): st = 'pass'
        targets.append(dict(file=n, sha=sha, status=st if text is not None or sha is None else 'nofile'))
    return dict(exists=q.exists(), text=text or '', checklist=qa_checklist(), targets=targets)


@router.post('/api/p/{kind}/{pid}/qa/pass')
def qa_pass(kind: str, pid: str, file: str = Body(...), checks: dict = Body(default={}), notes: dict = Body(default={}),
            stranger: str = Body('')):
    d = piece_dir(kind, pid); f = safe_join(d, file)
    if len(stranger) > 2000 or any(len(str(v)) > 1000 for v in notes.values()): raise HTTPException(400, 'Notes are too long.')
    if file not in qa_targets(kind, d) or not f.is_file(): raise HTTPException(400, f'{file} is not a picture that needs QA here')
    keys = [c['key'] for c in qa_checklist()]
    missing = [k for k in keys if not checks.get(k)]
    if missing: raise HTTPException(400, f'Tick every check first — still open: {", ".join(missing)}')
    sha = sha1_file(f); q = d / 'qa.md'
    text = read_text(q, f'# QA — {pid}\n')
    label = 'Strip' if file == 'strip.png' else file
    lines = [f'\n## Studio QA {today()} — {label} (sha1 {sha[:10]}) — judged alone']
    if stranger.strip(): lines.append(f'Stranger: {stranger.strip()}')
    for c in qa_checklist():
        n = (notes.get(c['key']) or '').strip()
        lines.append(f"- {c['key']} {c['title']} — PASS" + (f': {n}' if n else ''))
    lines.append(f'PASS {sha} {file}')
    if any(l.startswith(f'PASS {sha}') for l in text.splitlines()): raise HTTPException(409, 'This exact picture already has a PASS line.')
    write_atomic(q, text.rstrip('\n') + '\n' + '\n'.join(lines) + '\n'); invalidate()
    return dict(ok=True, sha=sha)


@router.post('/api/p/{kind}/{pid}/qa/fail')
def qa_fail(kind: str, pid: str, file: str = Body(...), failed: dict = Body(default={}), stranger: str = Body('')):
    """Write a FAIL section (failed = {key: reason}) — no PASS line."""
    d = piece_dir(kind, pid); f = safe_join(d, file)
    if not f.is_file(): raise HTTPException(404, 'no such picture')
    if not failed: raise HTTPException(400, 'Untick the checks that fail and say why.')
    if len(stranger) > 2000 or len(failed) > 40 or any(len(str(k)) > 8 or len(str(v)) > 1000 for k, v in failed.items()): raise HTTPException(400, 'Notes are too long.')
    failed = {re.sub(r'[^A-Z0-9]', '', str(k))[:4]: v for k, v in failed.items()}
    sha = sha1_file(f); q = d / 'qa.md'; text = read_text(q, f'# QA — {pid}\n')
    lines = [f'\n## Studio QA {today()} — {file} (sha1 {sha[:10]}) → FAIL alone']
    if stranger.strip(): lines.append(f'Stranger: {stranger.strip()}')
    for k, why in failed.items(): lines.append(f'- {k} — FAIL: {(why or "").strip() or "see image"}')
    write_atomic(q, text.rstrip('\n') + '\n' + '\n'.join(lines) + '\n'); invalidate()
    return dict(ok=True)


@router.post('/api/p/{kind}/{pid}/qa/revoke')
def qa_revoke(kind: str, pid: str, file: str = Body(..., embed=True)):
    d = piece_dir(kind, pid); f = safe_join(d, file); q = d / 'qa.md'
    sha = sha1_file(f)
    if not sha or not q.exists(): raise HTTPException(404, 'nothing to revoke')
    lines = read_text(q).splitlines(); n = 0
    for i, l in enumerate(lines):
        if l.startswith('PASS ' + sha): lines[i] = 'REVOKED ' + l[5:]; n += 1
    if not n: raise HTTPException(404, 'no PASS line for the current picture')
    write_atomic(q, '\n'.join(lines) + '\n'); invalidate()
    return dict(ok=True, revoked=n)


# ---------------- layout ----------------
@router.post('/api/p/strip/{pid}/layout')
def make_layout(pid: str, panels: int = Body(4), seed: int | None = Body(None), punch: bool = Body(True)):
    d = piece_dir('strip', pid)
    if not 1 <= panels <= 8: raise HTTPException(400, 'panels must be 1-8')
    lay = d / 'layout'
    for n in ('layout.png', 'layout.json', 'layout.txt'): backup(lay / n)
    cmd = [script_python(), SCRIPTS / 'comic_layout.py', lay.lpath, '--panels', str(panels)]
    if seed is not None: cmd += ['--seed', str(int(seed))]
    if not punch: cmd += ['--no-punch']
    code, out = jobs.run_sync(cmd, timeout=60, sync=dict(push=[f'{lay.key}/*'], scope=d.key))
    if code: raise HTTPException(500, f'layout failed: {out[-600:]}')
    invalidate()
    return dict(ok=True, log=out, text=read_text(lay / 'layout.txt'), mtime=time.time())


@router.get('/api/p/strip/{pid}/layout')
def get_layout(pid: str):
    d = piece_dir('strip', pid); lay = d / 'layout'
    return dict(exists=(lay / 'layout.png').exists(), text=read_text(lay / 'layout.txt'),
                mtime=(lay / 'layout.png').stat().st_mtime if (lay / 'layout.png').exists() else None,
                panels=len((__import__('json').loads(read_text(lay / 'layout.json', '{"panels": []}')) or {}).get('panels', [])))


# ---------------- prompt builder ----------------
def md_sections(text):
    secs = []; cur = None
    for line in text.splitlines():
        if line.startswith('## '):
            cur = dict(title=line[3:].strip(), lines=[]); secs.append(cur)
        elif cur is not None: cur['lines'].append(line)
    return secs


LOCK_DEFAULT = ('OUTFIT LOCK', 'ANATOMY LOCK', "REM'S EYES", 'HEIGHT LOCK')


@router.get('/api/p/strip/{pid}/prompt-parts')
def prompt_parts(pid: str):
    d = piece_dir('strip', pid); style = read_text(ROOT / 'style.md')
    header, locks = '', []
    for s in md_sections(style):
        body = '\n'.join(s['lines']).strip()
        if s['title'].lower().startswith('prompt header'):
            header = '\n'.join(l[2:] if l.startswith('> ') else l[1:] for l in s['lines'] if l.startswith('>')).strip()
        elif any(k in s['title'].upper() for k in ('LOCK', 'EYES', 'CHECK', 'DRIFT')):
            keep = [l for l in body.splitlines() if l.strip() and not l.startswith(('QA every image', 'Then ', 'If ChatGPT'))]
            short = s['title'].split('(')[0].strip()
            locks.append(dict(key=short, title=s['title'], text='\n'.join(keep), default=any(short.upper().startswith(x) for x in LOCK_DEFAULT)))
    syn = read_text(d / 'synopsis.md')
    panels = [dict(n=int(m.group(1)), text=m.group(2).strip()) for m in re.finditer(r'^\s*(\d+)\.\s+(.+)$', syn, re.M)]
    couple = couple_guess(pid)
    a, _, b = couple.partition(' x ')
    return dict(header=header, layout=read_text(d / 'layout' / 'layout.txt').strip(), panels=panels, locks=locks,
                couple=couple, couple_rule=(f'COUPLE RULE: {b} & {a} are THE couple; every other character is a cameo only and never '
                                            f'drawn as either one\'s love interest.' if b else ''),
                prompt_final=read_text(d / 'prompt_final.txt'), charsheet_prompt=read_text(d / 'charsheet_prompt.txt'),
                has_charsheet=(d / 'charsheet.png').exists(), has_layout=(d / 'layout' / 'layout.png').exists(),
                chatgpt_url=get_settings().get('chatgpt_url'), style_ref=get_settings().get('style_ref'))


@router.post('/api/p/{kind}/{pid}/board')
def board(kind: str, pid: str, style: str = Body('style_ref.png'), sheet: str = Body('charsheet.png'), layout: str = Body('layout/layout.png')):
    """Reference board like the ones we attach to ChatGPT: A = art style (top), B = character sheet, C = layout."""
    from PIL import Image, ImageDraw, ImageFont
    d = piece_dir(kind, pid)
    sp = safe_join(REFS, Path(style).name)
    if not sp.is_file(): raise HTTPException(404, f'style reference not found: {style}')
    parts = [('A', 'OUR ART STYLE - copy this look exactly', sp)]
    if sheet and safe_join(d, sheet).is_file(): parts.append(('B', 'CHARACTER SHEET - designs only', safe_join(d, sheet)))
    if layout and safe_join(d, layout).is_file(): parts.append(('C', 'PANEL LAYOUT - follow it', safe_join(d, layout)))
    W, gap, band = 1600, 24, 64
    try: font = ImageFont.truetype(str(font_file('fonts/Baloo2.ttf')), 40)
    except OSError: font = ImageFont.load_default()
    ims = []
    for k, t, p in parts:
        with Image.open(p.local()) as im: ims.append((k, t, im.convert('RGB')))
    top = ims[0][2]; top = top.resize((W, round(top.height * W / top.width)), Image.LANCZOS)
    if top.height > 1100: top = top.resize((round(top.width * 1100 / top.height), 1100), Image.LANCZOS)
    bottom = ims[1:]
    bh = 0; scaled = []
    if bottom:
        colw = (W - gap * (len(bottom) - 1)) // len(bottom)
        hs = [round(im.height * colw / im.width) for _, _, im in bottom]
        bh = min(max(hs), 1100)
        for (k, t, im) in bottom:
            s = min(colw / im.width, bh / im.height); scaled.append((k, t, im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS), colw))
    H = band + top.height + ((gap + band + bh) if bottom else 0) + gap
    out = Image.new('RGB', (W + 2 * gap, H), (255, 255, 255)); dr = ImageDraw.Draw(out)
    dr.text((gap, 10), f'{ims[0][0]}  {ims[0][1]}', fill=(40, 30, 40), font=font)
    out.paste(top, (gap + (W - top.width) // 2, band))
    y = band + top.height + gap
    x = gap
    for k, t, im, colw in scaled:
        dr.text((x, y + 10), f'{k}  {t}', fill=(40, 30, 40), font=font)
        out.paste(im, (x + (colw - im.width) // 2, y + band)); x += colw + gap
    dst = d / 'studio_board.jpg'; buf = io.BytesIO(); out.save(buf, 'JPEG', quality=90)
    write_atomic(dst, buf.getvalue(), history=False)
    return dict(ok=True, path=dst.name, parts=[p[0] for p in parts], mtime=dst.stat().st_mtime)


# ---------------- character sheet tools / style check ----------------
@router.post('/api/p/{kind}/{pid}/sheet-heights')
def sheet_heights(kind: str, pid: str, src: str = Body('charsheet.png'), ratios: str = Body(...), ref: int | None = Body(None)):
    d = piece_dir(kind, pid); s = safe_join(d, src)
    if not s.is_file(): raise HTTPException(404, 'no such picture')
    try: rs = [float(x) for x in ratios.replace(' ', '').split(',') if x]
    except ValueError: raise HTTPException(400, 'Heights must be numbers separated by commas, e.g. 1.0,0.84')
    if len(rs) < 1: raise HTTPException(400, 'Give one height per figure')
    if len(rs) > 16 or any(not 0.05 <= r <= 5 for r in rs): raise HTTPException(400, 'Heights must be between 0.05 and 5 (at most 16 figures)')
    if ref is None and 1.0 not in rs: raise HTTPException(400, 'One figure needs height 1.0 (or choose the reference figure)')
    raw = d / 'raw'
    out = unique(raw / f'{s.stem}_heights_{time.strftime("%H%M%S")}.png')
    get_ws().mkdir(raw.key) if get_ws().remote else raw.mkdir()
    cmd = [script_python(), SCRIPTS / 'sheet_heights.py', s.lpath, out.lpath, '--ratios', ','.join(map(str, rs))]
    if ref is not None: cmd += ['--ref', str(int(ref))]
    job = jobs.start_steps('sheet_heights', f'Fix sheet heights ({pid})', [dict(cmd=cmd, label='Measuring and scaling figures')],
                           ref=ref_of(kind, pid), on_done=lambda j: dict(output=str(out.relative_to(d))),
                           sync=dict(pull=[s.key], push=[out.key], scope=d.key))
    return jobs.public(job)


@router.post('/api/p/{kind}/{pid}/style-check')
def style_check(kind: str, pid: str, src: str = Body(..., embed=True)):
    d = piece_dir(kind, pid); s = safe_join(d, src)
    if not s.is_file(): raise HTTPException(404, 'no such picture')
    out = s.with_name(s.stem + '_stylecheck.jpg')
    cmd = [script_python(), SCRIPTS / 'style_check.py', s.lpath, out.lpath]
    job = jobs.start_steps('style_check', f'Style check {src}', [dict(cmd=cmd, label='Comparing with the master')], ref=ref_of(kind, pid),
                           on_done=lambda j: dict(output=str(out.relative_to(d))),
                           sync=dict(pull=[s.key, 'references/*'], push=[out.key], scope=d.key))
    return jobs.public(job)


# ---------------- strip reel (automatic build, same as scripts/build_reel.sh) ----------------
def reel_status(pid):
    out = {}
    for key, n in (('reel', f'{pid}_strip_reel.mp4'), ('image_png', f'{pid}_strip.png'), ('image_jpg', f'{pid}_strip.jpg')):
        p = UPLOAD / n
        out[key] = dict(path='upload/' + n, size=p.stat().st_size, mtime=p.stat().st_mtime) if p.exists() else None
    return out


def qa_gate(d: Path):
    strip = d / 'strip.png'
    if not strip.exists(): raise HTTPException(409, 'There is no strip.png yet — add or choose the final strip picture first (Pictures tab).')
    sha = sha1_file(strip)
    if not any(l.startswith('PASS ' + sha) for l in read_text(d / 'qa.md').splitlines()):
        raise HTTPException(409, 'QA PASS missing: the current strip.png has no "PASS <sha1>" line in qa.md. '
                                 'Check it in the QA tab and press "Mark PASS" first.')
    return sha


@router.get('/api/p/strip/{pid}/reel-status')
def get_reel_status(pid: str):
    piece_dir('strip', pid); return reel_status(pid)


@router.post('/api/p/strip/{pid}/reel/auto')
def build_reel_auto(pid: str):
    d = piece_dir('strip', pid); qa_gate(d)
    for n in ('layout_actual.json',): backup(d / 'layout' / n)
    backup(d / 'strip_reel' / 'storyboard.json')
    t0 = time.time()
    la, sbp, up = d / 'layout' / 'layout_actual.json', d / 'strip_reel' / 'storyboard.json', UPLOAD / f'{pid}_strip_reel.mp4'

    la, sbp, up = la.lpath, sbp.lpath, up.lpath          # watched in the working tree while the job runs

    def prog(job):
        """build_reel.sh prints nothing while it works, so estimate: panels found -> storyboard -> rendering (~6.5x
        the reel length on this Mac) -> encoded."""
        fresh = lambda p: p.exists() and p.stat().st_mtime >= t0 - 1
        if fresh(up): return 0.97
        if fresh(sbp):
            try: dur = __import__('json').loads(sbp.read_text())['output']['duration']
            except Exception: dur = 18
            return 0.1 + 0.85 * min(1.0, (time.time() - sbp.stat().st_mtime) / (dur * 6.5))
        return 0.05 if fresh(la) else 0.02
    job = jobs.start_steps('reel', f'Build strip reel ({pid})', [dict(cmd=['bash', SCRIPTS / 'build_reel.sh', pid], label='Building the reel')],
                           ref=ref_of('strip', pid), progress_fn=prog, fail_patterns=('REFUSED',),
                           on_done=lambda j: (invalidate(), reel_status(pid))[1], sync=reel_sync(pid))
    return jobs.public(job)


def reel_sync(pid):
    d = f'projects/{pid}'
    return dict(pull=[f'{d}/strip.png', f'{d}/qa.md', f'{d}/layout/**', f'{d}/strip_reel/**'],
                push=[f'{d}/layout/**', f'{d}/strip_reel/**', f'upload/{pid}_strip_reel.mp4', f'upload/{pid}_strip.png'],
                exclude=[f'{d}/strip_reel/*.mp4'], scope=d)


# ---------------- export ----------------
@router.post('/api/export')
def export(path: str = Body(..., embed=True)):
    need_local_features()
    src = safe_join(ROOT, path)
    if path.split('/')[0] not in ('upload', 'projects', 'music_videos') or not src.is_file(): raise HTTPException(404, 'no such file')
    dst_dir = Path(get_settings()['export_dir']).expanduser(); dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / sanitize_filename(src.name); shutil.copy2(src.local(), dst)
    return dict(ok=True, path=str(dst))
