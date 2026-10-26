"""Library / dashboard: every strip, music video and lyric edit with its status, plus account stats."""
import re, threading, time
from pathlib import Path

from fastapi import APIRouter, Depends
from .deps import authorize

from .core import IMG_EXT, MV, PROJ, ROOT, UPLOAD, first_line_title, natkey, read_json, read_text, sha1_file

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)

# couple from the project-name prefix (same table as scripts/update_trackers.py, plus a few more)
COUPLE: dict = {}      # optional shortcuts: project-name prefix -> couple, e.g. {'rem': 'Subaru x Rem'}


def bare(pid):
    return re.sub(r'^\d+_', '', pid)


def couple_guess(pid, log_couple=None, title=''):
    """The posting log's couple, else "(A x B)" in the synopsis title, else a COUPLE prefix shortcut, else 'Other'."""
    if log_couple and log_couple != '?': return log_couple
    m = re.search(r'\(([^(),]+?\s[x×]\s[^(),]+?)[,)]', title or '')
    if m: return m.group(1).replace('×', 'x').strip()
    return COUPLE.get(bare(pid).split('_')[0], 'Other')


def qa_status(qa_text: str, sha: str | None):
    """pass = a 'PASS <sha1>' line for the current file; revoked; stale = PASS lines exist but for an older image;
    none = qa.md has no PASS line; nofile = no qa.md at all (strips made before the QA gate)."""
    if sha is None: return 'noimage'
    if qa_text is None: return 'nofile'
    lines = qa_text.splitlines()
    if any(l.startswith('PASS ' + sha) for l in lines): return 'pass'
    if any(l.startswith('REVOKED ' + sha) for l in lines): return 'revoked'
    if any(l.startswith('PASS ') for l in lines): return 'stale'
    return 'none'


def load_log():
    return read_json(ROOT / 'posting_log.json', {'account': {}, 'posts': []}) or {'posts': []}


def load_captions():
    return read_json(ROOT / 'captions.json', {}) or {}


def caption_of(caps, pid):
    v = caps.get(pid)
    if isinstance(v, dict): return v.get('caption') or '', v.get('pinned') or ''
    return (v or ''), ''


def headline(title, name):
    m = re.search(r'["“](.+?)["”]', title)
    if m: return m.group(1)
    t = re.sub(r'^\S+\s+[—-]\s+', '', title).strip()
    return t if t and t != name else name.replace('_', ' ').capitalize()


def created(d: Path):
    st = d.stat()
    return getattr(st, 'st_birthtime', st.st_ctime)


def first_image(d: Path, names):
    for n in names:
        p = d / n
        if p.is_file(): return n
    return None


def strip_item(d: Path, log_by, caps):
    pid = d.name; strip = d / 'strip.png'
    sha = sha1_file(strip) if strip.exists() else None
    qa = d / 'qa.md'
    posts = log_by.get(pid, [])
    cap, pinned = caption_of(caps, pid)
    thumb = first_image(d, ['strip.png', 'charsheet.png', 'layout/layout.png'])
    if not thumb and (d / 'raw').is_dir():
        imgs = sorted((f for f in (d / 'raw').iterdir() if f.suffix.lower() in IMG_EXT), key=lambda f: f.stat().st_mtime)
        if imgs: thumb = 'raw/' + imgs[-1].name
    up_reel = UPLOAD / f'{pid}_strip_reel.mp4'
    up_img = next((UPLOAD / f'{pid}_strip{e}' for e in ('.png', '.jpg') if (UPLOAD / f'{pid}_strip{e}').exists()), None)
    st = dict(
        synopsis=(d / 'synopsis.md').exists(), charsheet=(d / 'charsheet.png').exists(),
        layout=(d / 'layout' / 'layout.png').exists(), strip=strip.exists(),
        qa=qa_status(read_text(qa, None) if qa.exists() else None, sha),
        reel=up_reel.exists(), upload_image=bool(up_img), caption=bool(cap.strip()), pinned=bool(pinned.strip()),
        posted_image=any(p.get('posted') and p.get('format') == 'image' for p in posts),
        posted_reel=any(p.get('posted') and p.get('format') == 'strip_reel' for p in posts),
        storyboard=(d / 'strip_reel' / 'storyboard.json').exists(),
        voiceover=(UPLOAD / f'{pid}_strip_reel_voiceover.mp4').exists(),
    )
    st['posted'] = st['posted_image'] or st['posted_reel']
    num = int(pid.split('_')[0])
    title = first_line_title(d / 'synopsis.md', bare(pid))
    return dict(kind='strip', type='strip', id=pid, num=num, name=bare(pid), title=title, headline=headline(title, bare(pid)),
                couple=couple_guess(pid, next((p.get('couple') for p in posts if p.get('couple')), None), title),
                thumb=thumb, mtime=max((d / n).stat().st_mtime for n in ('.',) + tuple(x for x in ('strip.png', 'synopsis.md') if (d / x).exists())),
                status=st, sha=sha, created=created(d))


def mv_frames(d: Path):
    out = []
    for f in sorted(d.iterdir(), key=natkey):
        if f.suffix.lower() in IMG_EXT and re.fullmatch(r'(frame|p|chorus|tall)\d+[a-z]?', f.stem): out.append(f.name)
    if (d / 'edit_frames').is_dir():
        out += ['edit_frames/' + f.name for f in sorted((d / 'edit_frames').iterdir(), key=natkey) if f.suffix.lower() in IMG_EXT]
    return out


def mv_item(d: Path, mv_posts):
    pid = d.name
    edits = sorted(f.name for f in d.glob('lyric_edit*.json'))
    frames = mv_frames(d)
    thumb = (frames[0] if frames else None) or first_image(d, ['charsheet.png'])
    ups = sorted(f.name for f in (UPLOAD / 'music_videos').glob(f'{pid}_*') if f.suffix.lower() in {'.mp4', '.mov'}) if (UPLOAD / 'music_videos').is_dir() else []
    renders = sorted(f.name for f in d.glob('*.mp4') if '.rendering' not in f.name)
    qa = read_text(d / 'qa.md', None) if (d / 'qa.md').exists() else None
    passed = 0
    if qa is not None:
        for fr in frames:
            s = sha1_file(d / fr)
            if s and any(l.startswith('PASS ' + s) for l in qa.splitlines()): passed += 1
    posted = [p for p in mv_posts if p.get('project') == pid]
    st = dict(synopsis=(d / 'synopsis.md').exists(), charsheet=(d / 'charsheet.png').exists(), frames=len(frames),
              frames_pass=passed, qa_file=qa is not None, edits=len(edits), reel=bool(ups or renders),
              posted=any(p.get('posted') for p in posted), caption=False, qa='pass' if frames and passed == len(frames) else ('none' if qa is not None else 'nofile'))
    return dict(kind='mv', type='lyric_edit' if edits else 'music_video', id=pid, num=int(pid.split('_')[0]), name=bare(pid),
                title=first_line_title(d / 'synopsis.md', bare(pid)), headline=headline(first_line_title(d / 'synopsis.md', bare(pid)), bare(pid)),
                couple=couple_guess(pid), thumb=thumb,
                mtime=d.stat().st_mtime, created=created(d), status=st, edits=edits, uploads=ups, renders=renders)


_cache = {'t': 0, 'v': None}
_lock = threading.Lock()


def build_library():
    log = load_log(); caps = load_captions()
    log_by: dict = {}
    for p in log.get('posts', []): log_by.setdefault(p.get('project'), []).append(p)
    items = []
    for d in sorted(PROJ.iterdir(), key=natkey):
        if d.is_dir() and re.match(r'^\d+_', d.name):
            try: items.append(strip_item(d, log_by, caps))
            except Exception as e: items.append(dict(kind='strip', type='strip', id=d.name, num=0, name=d.name, title=d.name, couple='Other', thumb=None, mtime=0, status={}, error=str(e)))
    for d in sorted(MV.iterdir(), key=natkey):
        if d.is_dir() and re.match(r'^\d+_', d.name):
            try: items.append(mv_item(d, log.get('music_video_posts', [])))
            except Exception as e: items.append(dict(kind='mv', type='music_video', id=d.name, num=0, name=d.name, title=d.name, couple='Other', thumb=None, mtime=0, status={}, error=str(e)))
    return items, log


def account_stats(log, items):
    acc = log.get('account', {})
    def latest(prefix):
        ks = sorted(k for k in acc if k.startswith(prefix + '_'))
        return (acc[ks[-1]], ks[-1][len(prefix) + 1:].replace('_', '-')) if ks else (None, None)
    followers, fdate = latest('followers'); ig_posts, pdate = latest('posts')
    posts = log.get('posts', [])
    per = {}
    for p in posts:
        c = couple_guess(p.get('project') or '', p.get('couple'))
        e = per.setdefault(c, dict(couple=c, posted=0, ready=0))
        if p.get('posted'): e['posted'] += 1
        else: e['ready'] += 1
    strips = [i for i in items if i['kind'] == 'strip']
    last = sorted((p for p in posts if p.get('posted') and p.get('date')), key=lambda p: p['date'])
    return dict(handle=acc.get('handle'), display_name=acc.get('display_name'), followers=followers, followers_date=fdate,
                ig_posts=ig_posts, ig_posts_date=pdate, posted=sum(1 for p in posts if p.get('posted')),
                mv_posted=sum(1 for p in log.get('music_video_posts', []) if p.get('posted')),
                ready=sum(1 for p in posts if not p.get('posted')), per_couple=sorted(per.values(), key=lambda e: -(e['posted'] + e['ready'])),
                strips=len(strips), strips_done=sum(1 for i in strips if i['status'].get('strip')),
                reels=sum(1 for i in strips if i['status'].get('reel')),
                music_videos=sum(1 for i in items if i['kind'] == 'mv'), last_posted=last[-1] if last else None)


@router.get('/api/library')
def library():
    with _lock:
        if _cache['v'] is None or time.time() - _cache['t'] > 2:
            items, log = build_library()
            _cache.update(t=time.time(), v=dict(items=items, stats=account_stats(log, items)))
        return _cache['v']


def invalidate():
    _cache['v'] = None
