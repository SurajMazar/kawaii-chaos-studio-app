"""New-project wizard, the Tools page (repo scripts run as jobs) and Settings."""
import os, re, threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException
from .deps import authorize

from config import CONFIG
from security.context import min_role
from storage import get_ws

from . import jobs
from .core import (LOCAL_ONLY, MV, NAME_RE, PROJ, ROOT, SCRIPTS, backup, get_settings, read_text, safe_join, save_settings,
                   script_python, sha1_file, write_atomic)
from .library import invalidate

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)


# ---------------- new project ----------------
def strip_synopsis(name, couple, premise, panels, mood, lines, hashtags, tag):
    beats = [l.strip() for l in (lines or '').splitlines() if l.strip()]
    rows = '\n'.join(f'{i + 1}. {beats[i] if i < len(beats) else "(panel " + str(i + 1) + ": one short line + one clear action)"}'
                     for i in range(max(panels, len(beats))))
    tags = ' '.join(x for x in [tag, hashtags] if x).strip()
    return (f'# {name} — "{premise or "premise"}" ({couple or "couple"}{", " + mood if mood else ""})\n\n{rows}\n\n'
            f'**Caption:**\n\n(one sweet/funny line + emoji)\n\n{tags}\n\n**Pinned comment:** \n\n'
            f'**Song ideas (pick in the IG app):** \n')


def mv_synopsis(name, couple, premise, mood, lyric):
    kind = 'lyric edit' if lyric else 'music video'
    return (f'# {name} — {premise or "story"} ({couple or "couple"}, {kind}{", " + mood if mood else ""})\n\n'
            f'Story (must be NEW — not a scene or joke from an existing strip or reel):\n\n1. \n2. \n3. \n\n'
            f'Song: \n')


_new_lock = threading.Lock()
WIDTH = {'projects': 3, 'music_videos': 2}


def next_folder(top, name: str):
    """Same numbering as scripts/new_project.py: the next free number (3 digits for strips, 2 for music videos)."""
    nums = [int(m.group(1)) for p in top.iterdir() if (m := re.match(r'(\d+)_', p.name))]
    return top / f'{max(nums, default=0) + 1:0{WIDTH[top.key]}d}_{name}'


@router.post('/api/new')
def new_project(kind: str = Body(...), name: str = Body(...), couple: str = Body(''), tag: str = Body(''), premise: str = Body(''),
                panels: int = Body(4), seed: int | None = Body(None), layout: bool = Body(True), mood: str = Body(''),
                lines: str = Body(''), start: float = Body(0.0)):
    if kind not in ('strip', 'mv', 'lyric'): raise HTTPException(400, 'kind must be strip, mv or lyric')
    name = name.strip().lower().replace(' ', '_').replace('-', '_')
    if not NAME_RE.match(name): raise HTTPException(400, 'Use lowercase letters, numbers and _ only (e.g. rem_rainy_day)')
    top = PROJ if kind == 'strip' else MV
    panels = max(1, min(int(panels), 8))
    for v, lim in ((couple, 120), (tag, 80), (premise, 300), (mood, 80), (lines, 4000)):
        if len(v or '') > lim: raise HTTPException(400, 'One of the fields is too long.')
    with _new_lock:
        if any(re.fullmatch(r'\d+_' + re.escape(name), p.name) for p in top.iterdir()):
            raise HTTPException(409, f'A project called "{name}" already exists — pick another name.')
        d = next_folder(top, name); pid = d.name
        st = get_settings(); syn = d / 'synopsis.md'
        text = strip_synopsis(name, couple, premise, panels, mood, lines, st.get('hashtags', ''), tag) if kind == 'strip' else mv_synopsis(name, couple, premise, mood, kind == 'lyric')
        write_atomic(syn, text, history=False)
    log = d.key
    (d / 'raw').mkdir(exist_ok=True)
    if kind == 'strip':
        if layout:
            cmd = [script_python(), SCRIPTS / 'comic_layout.py', (d / 'layout').lpath, '--panels', str(panels)]
            if seed is not None: cmd += ['--seed', str(int(seed))]
            c2, o2 = jobs.run_sync(cmd, timeout=60, sync=dict(push=[f'{d.key}/layout/*'], scope=d.key)); log += '\n' + o2
            if c2: raise HTTPException(500, f'layout failed: {o2}')
    else:
        if kind == 'lyric':
            (d / 'edit_frames').mkdir(exist_ok=True)
            from .lyric import new_edit
            new_edit(pid, file='lyric_edit.json', mode='lyrics' if lines.strip() else 'blank', start=start, lines_text=lines,
                     src_pid='', src_file='', seconds_per_line=3.0, audio='', signature=None)
    invalidate()
    return dict(ok=True, kind='strip' if kind == 'strip' else 'mv', id=pid, log=log)


# ---------------- tools ----------------
TOOLS = [
    dict(key='make_pdf', script='make_pdf.py', title='Make the PDF book', icon='book',
         desc='Every finished (QA-passed) strip in one PDF: cover, contents, a divider per couple, captions and posted status.',
         args=[dict(name='out', label='Save as', default='upload/comics_book.pdf', kind='path')]),
    dict(key='style_check', script='style_check.py', title='Style check a picture', icon='eye',
         desc='Puts the master style crop next to the picture\'s characters at the same scale, to judge the style by eye.',
         args=[dict(name='image', label='Picture (path in your content folder)', default='', kind='image', required=True)]),
    dict(key='upload_encode', script='upload_encode.py', title='Small upload copies (<10 MB)', icon='compress',
         desc='Re-encodes rendered reels to Instagram-web-friendly copies (2-pass H.264, ~9.3 MB) in upload/.',
         args=[dict(name='projects', label='Only these projects (space separated, empty = all)', default='', kind='list')]),
    dict(key='build_missing', script='build_missing.sh', title='Build every missing strip reel', icon='video',
         desc='Builds a silent strip reel for each strip that has strip.png but no upload copy yet (QA-PASS only), then updates the trackers.', args=[]),
    dict(key='update_trackers', script='update_trackers.py', title='Update trackers', icon='sync',
         desc='Syncs captions.json, posting_log.json and the README table with every strip that has a reel. A backup is kept first.', args=[]),
    dict(key='unpack_bundles', script='unpack_bundles.py', title='Import ChatGPT bundles (strips)', icon='import',
         desc='Unpacks ~/Downloads/*_bundle*.bin files into each strip\'s raw/ folder.', args=[]),
]


@router.get('/api/tools')
def list_tools():
    return [t for t in TOOLS if (SCRIPTS / t['script']).exists()]


TRACKER_SYNC = dict(pull=['projects/*/synopsis.md', 'captions.json', 'posting_log.json', 'README.md'],
                    stubs=['projects/*/strip.png', 'upload/*_strip_reel.mp4', 'upload/*_strip.png'],
                    push=['captions.json', 'posting_log.json', 'README.md'], scope='global')


def _build_missing_remote(job):
    """S3/R2: the same as scripts/build_missing.sh, project by project (each one synced into the work cache)."""
    from .pieces import reel_sync
    ws = get_ws(); built = []
    todo = []
    for d in sorted(PROJ.iterdir(), key=lambda p: p.name):
        if re.match(r'^\d+_', d.name) and (d / 'strip.png').is_file() and not (ROOT / 'upload' / f'{d.name}_strip_reel.mp4').is_file():
            sha = sha1_file(d / 'strip.png')
            if any(l.startswith('PASS ' + sha) for l in read_text(d / 'qa.md').splitlines()): todo.append(d.name)
            else: jobs.log(job, f'REFUSED {d.name}: no QA pass for current strip.png (see qa_rules.md)')
    job['total'] = len(todo)
    for i, pid in enumerate(todo):
        if job['cancel']: raise KeyboardInterrupt
        jobs.log(job, f'building {pid}')
        s = reel_sync(pid)
        with ws.job_sync(pull=s['pull'], push=s['push'], scope=s['scope'], exclude=s['exclude']) as root:
            code, out = _run([ 'bash', SCRIPTS / 'build_reel.sh', pid], root)
        jobs.log(job, out[-400:]); job['done'] = i + 1; job['progress'] = round((i + 1) / max(1, len(todo)), 4)
        if code == 0: built.append(pid)
    with ws.job_sync(**{k: v for k, v in TRACKER_SYNC.items()}) as root:
        code, out = _run([script_python(), SCRIPTS / 'update_trackers.py'], root)
        jobs.log(job, out[-400:])
    invalidate()
    return dict(built=built)


def _run(cmd, cwd):
    import subprocess  # nosec B404 - argument lists only
    from .core import script_env
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=script_env(), capture_output=True, text=True, timeout=3600, errors='replace')  # nosec B603
    return p.returncode, (p.stdout + p.stderr).strip()


@router.post('/api/tools/{key}/run')
@min_role('admin')
def run_tool(key: str, args: dict = Body(default={}, embed=True)):
    t = next((t for t in list_tools() if t['key'] == key), None)
    if not t: raise HTTPException(404, 'no such tool')
    if not isinstance(args, dict): raise HTTPException(400, 'bad arguments')
    py = script_python(); s = SCRIPTS / t['script']
    cmd = ['bash', s] if s.suffix == '.sh' else [py, s]
    result = None; sync = None
    if key == 'make_pdf':
        out = str(args.get('out') or 'upload/comics_book.pdf').strip()
        if not re.fullmatch(r'upload/[A-Za-z0-9_\-]{1,80}\.pdf', out): raise HTTPException(400, 'Save the PDF inside upload/ (name ending in .pdf)')
        p = safe_join(ROOT, out); cmd += [p.lpath, '--handle', get_settings().get('handle') or '']; result = dict(download=out)
        sync = dict(pull=['projects/*/strip.png', 'projects/*/qa.md', 'projects/*/synopsis.md', 'music_videos/*/*.png', 'music_videos/*/qa.md',
                          'music_videos/*/synopsis.md', 'captions.json', 'posting_log.json', 'fonts/*', 'mascot/*'], push=[out], scope='global')
    elif key == 'style_check':
        img = str(args.get('image') or '').strip()
        p = safe_join(ROOT, img)
        if img.split('/')[0] not in ('projects', 'music_videos', 'references') or not p.is_file() or p.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise HTTPException(400, 'Pick a picture inside projects/ or music_videos/')
        o = p.with_name(p.stem + '_stylecheck.jpg')
        cmd += [p.lpath, o.lpath]; result = dict(output=o.key)
        sync = dict(pull=[p.key, 'references/*'], push=[o.key], scope=p.parent.key)
    elif key == 'upload_encode':
        names = [n for n in re.split(r'[\s,]+', str(args.get('projects') or '')) if n]
        for n in names:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_\-]{0,80}', n): raise HTTPException(400, f'bad project name {n}')
        cmd += names
        sync = dict(pull=['projects/*/reel.mp4', 'projects/*/strip_reel/strip_reel.mp4'], push=['upload/*'], scope='global')
    elif key == 'update_trackers':
        for n in ('captions.json', 'posting_log.json', 'README.md'): backup(ROOT / n)
        sync = TRACKER_SYNC
    elif key == 'build_missing':
        if get_ws().remote:
            job = jobs.start_fn('tool', t['title'], _build_missing_remote, ref=f'tool/{key}')
            return jobs.public(job)
    elif key == 'unpack_bundles':
        if not CONFIG.local_features: raise HTTPException(403, 'This works only when the Studio runs on your own computer.')
        sync = dict(pull=['projects/*/synopsis.md'], push=['projects/*/raw/*'], scope='global')
    job = jobs.start_steps('tool', t['title'], [dict(cmd=cmd, label=t['title'])], ref=f'tool/{key}',
                           on_done=lambda j: (invalidate(), result)[1], sync=sync)
    return jobs.public(job)


# ---------------- settings ----------------
@router.get('/api/settings')
def settings():
    s = get_settings()
    s['local_features'] = CONFIG.local_features
    return s


def _check_settings(s: dict):
    for k in ('handle', 'signature', 'style_ref', 'chatgpt_url'):
        if k in s and (not isinstance(s[k], str) or len(s[k]) > 200): raise HTTPException(400, f'{k} is too long')
    if 'art_source' in s and s['art_source'] not in ('chatgpt', 'own'): raise HTTPException(400, 'art_source must be chatgpt or own')
    if 'hashtags' in s and (not isinstance(s['hashtags'], str) or len(s['hashtags']) > 1000): raise HTTPException(400, 'hashtags are too long')
    if s.get('chatgpt_url'):
        u = urlparse(s['chatgpt_url'])
        if u.scheme != 'https' or not u.netloc: raise HTTPException(400, 'The ChatGPT link must start with https://')
    if 'style_ref' in s and s['style_ref'] and s['style_ref'] != Path(s['style_ref']).name: raise HTTPException(400, 'Pick a file from references/')
    for k in LOCAL_ONLY:
        if k not in s: continue
        if not CONFIG.local_features: s.pop(k); continue
        v = s[k]
        if not isinstance(v, str) or not v.strip() or not Path(v).expanduser().is_absolute(): raise HTTPException(400, f'{k} must be an absolute path')
        if k == 'python' and not (Path(v).is_file() and os.access(v, os.X_OK) and re.search(r'python[0-9.]*$', Path(v).name)):
            raise HTTPException(400, 'The Python for the scripts must be an existing python executable')


@router.put('/api/settings')
@min_role('admin')
def put_settings(s: dict = Body(...)):
    s = {k: v for k, v in s.items() if k != 'local_features'}
    if 'reel_seconds_per_panel' in s:
        try: s['reel_seconds_per_panel'] = max(1.0, min(float(s['reel_seconds_per_panel']), 10.0))
        except (TypeError, ValueError): raise HTTPException(400, 'seconds per panel must be a number')
    _check_settings(s)
    out = save_settings(s); out['local_features'] = CONFIG.local_features
    return out


@router.get('/api/style-header')
def style_header():
    return dict(text=read_text(ROOT / 'style.md'))
